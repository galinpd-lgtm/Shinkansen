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

// Config: ORGANIZER_CONFIG от средата, иначе config_file от forms.json спрямо родителя на DOCUMENT_ROOT —
// на споделен хостинг това е домашната папка, извън public_html (напр. ~/ai_start_config.php).
function organizer_config_path(array $spec): string
{
    $env = getenv('ORGANIZER_CONFIG');
    if ($env) {
        return $env;
    }
    $rel = (string)($spec['config_file'] ?? '');
    if ($rel === '' || strpos($rel, '..') !== false || $rel[0] === '/') {
        throw new RuntimeException('forms.json: невалиден config_file');
    }
    $docroot = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/');
    return dirname($docroot) . '/' . $rel;
}

function organizer_config(array $spec): array
{
    $path = organizer_config_path($spec);
    if (!is_file($path)) {
        throw new RuntimeException('липсва config извън публичната папка');
    }
    $cfg = require $path;
    foreach (isset($cfg['db']['dsn']) ? [] : ['host', 'name', 'user', 'pass'] as $k) {
        if (!isset($cfg['db'][$k])) {
            throw new RuntimeException('config: липсва db.' . $k);
        }
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

function organizer_safe_table(string $t): string
{
    if (!preg_match('/^[a-z][a-z0-9_]{0,50}$/', $t)) {
        throw new RuntimeException('невалидно име на таблица');
    }
    return $t;
}

// На живо таблиците се създават от sql/schema.sql (пуска ги човек). auto_create е само за изпитване.
function organizer_auto_create(PDO $pdo, array $cfg, array $spec): void
{
    if (empty($cfg['auto_create'])) {
        return;
    }
    foreach ($spec['forms'] as $f) {
        $t = organizer_safe_table($f['table']);
        $pdo->exec("CREATE TABLE IF NOT EXISTS `$t` (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, answers TEXT NOT NULL)");
    }
    $r = organizer_safe_table($spec['rate_table']);
    $pdo->exec("CREATE TABLE IF NOT EXISTS `$r` (ip_hash TEXT NOT NULL, created_at TEXT NOT NULL)");
}

// Ограничение по брой изпращания за час. Пазим HMAC на IP (не самия адрес) и само за последния час.
function organizer_rate_ok(PDO $pdo, array $cfg, array $spec, string $ip): bool
{
    $limit = (int)($spec['rate_limit_per_hour'] ?? 10);
    if ($limit <= 0) {
        return true;
    }
    $key = (string)($cfg['salt'] ?? ($cfg['db']['pass'] ?? $spec['event']));
    $hash = hash_hmac('sha256', $ip, $key);
    $t = organizer_safe_table($spec['rate_table']);
    $cut = gmdate('Y-m-d H:i:s', time() - 3600);
    $pdo->prepare("DELETE FROM `$t` WHERE created_at < ?")->execute([$cut]);
    $st = $pdo->prepare("SELECT COUNT(*) FROM `$t` WHERE ip_hash = ? AND created_at >= ?");
    $st->execute([$hash, $cut]);
    if ((int)$st->fetchColumn() >= $limit) {
        return false;
    }
    $pdo->prepare("INSERT INTO `$t` (ip_hash, created_at) VALUES (?, ?)")->execute([$hash, gmdate('Y-m-d H:i:s')]);
    return true;
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
                $v = ($f['other_label'] ?? 'Друго') . ': ' . $o;
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
                    $vals[] = ($f['other_label'] ?? 'Друго') . ': ' . $o;
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
