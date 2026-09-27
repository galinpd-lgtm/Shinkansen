<?php
// Shinkansen организатор — общата логика на въпросниците. Не се вика отвън (.htaccess го забранява).
// Паролата за базата НЕ е тук: config файлът стои извън public_html (виж config.example.php).

declare(strict_types=1);

const ORGANIZER_MAX_BODY = 65536;

function organizer_spec(): array
{
    $raw = @file_get_contents(__DIR__ . '/forms.json');
    $spec = $raw === false ? null : json_decode($raw, true);
    if (!is_array($spec) || !isset($spec['event'], $spec['forms'])) {
        throw new RuntimeException('forms.json липсва или е повреден');
    }
    return $spec;
}

// Config: ORGANIZER_CONFIG от средата, иначе <родителят на DOCUMENT_ROOT>/.organizer/<slug>.php —
// на споделен хостинг това е домашната папка, извън public_html.
function organizer_config_path(string $slug): string
{
    $env = getenv('ORGANIZER_CONFIG');
    if ($env) {
        return $env;
    }
    $docroot = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/');
    return dirname($docroot) . '/.organizer/' . $slug . '.php';
}

function organizer_config(string $slug): array
{
    $path = organizer_config_path($slug);
    if (!is_file($path)) {
        throw new RuntimeException('липсва config извън публичната папка');
    }
    $cfg = require $path;
    foreach (isset($cfg['db']['dsn']) ? [] : ['host', 'name', 'user', 'pass'] as $k) {
        if (!isset($cfg['db'][$k])) {
            throw new RuntimeException('config: липсва db.' . $k);
        }
    }
    $prefix = $cfg['db']['prefix'] ?? '';
    if (!preg_match('/^[a-z0-9_]{0,20}$/', $prefix)) {
        throw new RuntimeException('config: db.prefix само a-z0-9_');
    }
    return $cfg;
}

function organizer_pdo(array $cfg): PDO
{
    $db = $cfg['db'];
    // dsn е само за изпитване (SQLite в тестовете); на хостинга е MySQL от host/name/user/pass.
    $dsn = $db['dsn'] ?? sprintf('mysql:host=%s;dbname=%s;charset=utf8mb4', $db['host'], $db['name']);
    return new PDO($dsn, $db['user'] ?? null, $db['pass'] ?? null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
}

function organizer_table(array $cfg): string
{
    return ($cfg['db']['prefix'] ?? '') . 'responses';
}

function organizer_ensure_table(PDO $pdo, string $table): void
{
    if ($pdo->getAttribute(PDO::ATTR_DRIVER_NAME) === 'sqlite') {
        $pdo->exec("CREATE TABLE IF NOT EXISTS `$table` (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
            form TEXT NOT NULL, created_at TEXT NOT NULL, answers TEXT NOT NULL)");
        return;
    }
    $pdo->exec("CREATE TABLE IF NOT EXISTS `$table` (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        event VARCHAR(64) NOT NULL,
        form VARCHAR(40) NOT NULL,
        created_at DATETIME NOT NULL,
        answers MEDIUMTEXT NOT NULL,
        KEY event_form (event, form)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
}

function organizer_str($v): string
{
    if (!is_string($v)) {
        return '';
    }
    $v = str_replace("\0", '', $v);
    return trim(preg_replace('/\r\n?/', "\n", $v));
}

function organizer_len(string $s): int
{
    return function_exists('mb_strlen') ? mb_strlen($s, 'UTF-8') : (int)preg_match_all('/./us', $s);
}

// Чиста функция: връща [отговори, грешки]. Приема само полетата от спецификацията;
// всичко друго (вкл. опции извън списъка) се отхвърля, не се записва.
function organizer_validate(array $form, array $in): array
{
    $out = [];
    $err = [];
    foreach ($form['fields'] as $f) {
        $id = $f['id'];
        $type = $f['type'];
        $label = $f['label'];
        if ($type === 'single') {
            $v = organizer_str($in[$id] ?? '');
            if ($v === '__other' && !empty($f['other'])) {
                $o = organizer_str($in[$id . '__other'] ?? '');
                if ($o === '' || organizer_len($o) > 200) {
                    $err[$id] = $label . ': напиши кое е „Друго“ (до 200 знака)';
                    continue;
                }
                $v = 'Друго: ' . $o;
            } elseif ($v !== '' && !in_array($v, $f['options'], true)) {
                $err[$id] = $label . ': непознат отговор';
                continue;
            }
            if ($v !== '') {
                $out[$id] = $v;
            }
        } elseif ($type === 'multi') {
            $raw = $in[$id] ?? [];
            if (is_string($raw)) {
                $raw = [$raw];
            }
            if (!is_array($raw)) {
                $raw = [];
            }
            $vals = [];
            foreach ($raw as $v) {
                $v = organizer_str($v);
                if ($v === '__other' && !empty($f['other'])) {
                    $o = organizer_str($in[$id . '__other'] ?? '');
                    if ($o === '' || organizer_len($o) > 200) {
                        $err[$id] = $label . ': напиши кое е „Друго“ (до 200 знака)';
                        continue 2;
                    }
                    $vals[] = 'Друго: ' . $o;
                } elseif (in_array($v, $f['options'], true)) {
                    $vals[] = $v;
                } else {
                    $err[$id] = $label . ': непознат отговор';
                    continue 2;
                }
            }
            $vals = array_values(array_unique($vals));
            if (isset($f['max']) && count($vals) > $f['max']) {
                $err[$id] = $label . ': до ' . $f['max'] . ' отговора';
                continue;
            }
            if ($vals) {
                $out[$id] = $vals;
            }
        } elseif ($type === 'consent') {
            $v = $in[$id] ?? '';
            if ($v === '1' || $v === 1 || $v === true || $v === 'on') {
                $out[$id] = true;
            }
        } else {
            $v = organizer_str($in[$id] ?? '');
            $max = $f['max_length'] ?? 2000;
            if (organizer_len($v) > $max) {
                $err[$id] = $label . ': до ' . $max . ' знака';
                continue;
            }
            if ($type === 'email' && $v !== '' && !filter_var($v, FILTER_VALIDATE_EMAIL)) {
                $err[$id] = $label . ': невалиден имейл';
                continue;
            }
            if ($v !== '') {
                $out[$id] = $v;
            }
        }
    }
    foreach ($form['fields'] as $f) {
        $id = $f['id'];
        if (isset($err[$id]) || isset($out[$id])) {
            continue;
        }
        $need = !empty($f['required']);
        foreach ($f['required_if'] ?? [] as $dep) {
            if (isset($out[$dep])) {
                $need = true;
            }
        }
        if ($need) {
            $err[$id] = $f['label'] . ': задължително';
        }
    }
    return [$out, $err];
}

// Клетка за CSV: защита от формули в Excel (=, +, -, @, таб, CR в началото).
function organizer_csv_cell($v): string
{
    if (is_array($v)) {
        $v = implode('; ', $v);
    } elseif ($v === true) {
        $v = 'да';
    }
    $v = (string)$v;
    if ($v !== '' && strpbrk($v[0], "=+-@\t\r") !== false) {
        $v = "'" . $v;
    }
    return $v;
}
