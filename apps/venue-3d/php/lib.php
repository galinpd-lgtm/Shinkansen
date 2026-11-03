<?php
// Сграда в 3D — формата за входа: общата логика. Не се вика отвън (.htaccess го забранява).
// ПИН-овете НЕ са тук: config файлът стои извън public_html (виж config.sample.php).
// Пише status.json до страницата на сградата — същия, който <venue-3d status="status.json"> чете.

declare(strict_types=1);

const V3D_STATES = ['open', 'busy', 'closed'];
const V3D_NOTE_MAX = 140;            // знака на бележка
const V3D_MAX_FAILS = 5;             // грешни ПИН-а от един адрес …
const V3D_FAIL_WINDOW = 900;         // … за 15 минути → пауза до края на прозореца
const V3D_ID = '/^[a-z0-9_]{1,40}$/';

// Config: VENUE3D_CONFIG от средата, иначе ~/venue3d_config.php — папката над DOCUMENT_ROOT,
// на споделен хостинг това е домашната папка, извън public_html.
function v3d_config_path(): string
{
    $env = getenv('VENUE3D_CONFIG');
    if ($env) {
        return $env;
    }
    return dirname(rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/')) . '/venue3d_config.php';
}

function v3d_config(): array
{
    $path = v3d_config_path();
    if (!is_file($path)) {
        throw new RuntimeException('липсва config извън публичната папка');
    }
    $cfg = require $path;
    foreach (['venue_json', 'status_json', 'state_dir', 'people'] as $k) {
        if (empty($cfg[$k])) {
            throw new RuntimeException("config: липсва $k");
        }
    }
    $cfg['timezone'] = $cfg['timezone'] ?? 'Europe/Sofia';
    $cfg['max_age_min'] = array_key_exists('max_age_min', $cfg) ? $cfg['max_age_min'] : 30;
    return $cfg;
}

function v3d_read_json(string $path): ?array
{
    $raw = @file_get_contents($path);
    $data = $raw === false ? null : json_decode($raw, true);
    return is_array($data) ? $data : null;
}

/** Точките от venue.json: [id => ['name' => име на български (или английски), 'kind' => вид]]. */
function v3d_hotspots(array $venue): array
{
    $out = [];
    foreach ($venue['hotspots'] ?? [] as $h) {
        if (!is_array($h) || !is_string($h['id'] ?? null) || !preg_match(V3D_ID, $h['id'])) {
            continue;
        }
        $name = $h['name'] ?? $h['id'];
        if (is_array($name)) {
            $name = $name['bg'] ?? $name['en'] ?? $h['id'];
        }
        $out[$h['id']] = ['name' => (string)$name, 'kind' => (string)($h['kind'] ?? '')];
    }
    return $out;
}

/** Човекът с този ПИН: [име, запис] или null. ПИН-овете са само като хеш (password_hash). */
function v3d_find_person(array $people, string $pin): ?array
{
    if ($pin === '' || strlen($pin) > 64) {
        return null;
    }
    foreach ($people as $name => $p) {
        if (is_array($p) && is_string($p['pin'] ?? null) && password_verify($pin, $p['pin'])) {
            return [(string)$name, $p];
        }
    }
    return null;
}

/** Кои точки може да пипа човекът: списък от id, или '*' — всички от venue.json. */
function v3d_allowed(array $person, array $hotspots): array
{
    $points = $person['points'] ?? [];
    if ($points === '*') {
        return array_keys($hotspots);
    }
    return array_values(array_filter((array)$points, fn($id) => is_string($id) && isset($hotspots[$id])));
}

/** Бележка: без управляващи знаци, без излишни интервали, до V3D_NOTE_MAX знака. */
function v3d_clean_note($v): string
{
    $s = is_string($v) ? $v : '';
    $s = preg_replace('/[\x00-\x1F\x7F]+/u', ' ', $s) ?? '';
    $s = trim(preg_replace('/\s+/u', ' ', $s) ?? '');
    return mb_substr($s, 0, V3D_NOTE_MAX);
}

/**
 * Едно действие върху status.json. Не пише нищо — връща [новото съдържание, грешка или ''].
 *   set     — точка `id` получава `state` (open/busy/closed) и бележка note_bg/note_en, час сега;
 *   clear   — записът на точка `id` се маха (няма данни — нищо не се показва);
 *   confirm — „нищо не се е променило“: всички записани точки на човека получават час сега.
 * Записите за точки, които вече ги няма във venue.json, отпадат.
 */
function v3d_apply(array $status, string $action, array $in, array $allowed, array $hotspots,
                   DateTimeImmutable $now, $maxAgeMin): array
{
    $stamp = $now->format('Y-m-d\TH:i:sP');
    $points = [];
    foreach (($status['hotspots'] ?? []) as $id => $v) {
        if (isset($hotspots[$id]) && is_array($v) && in_array($v['state'] ?? null, V3D_STATES, true)) {
            $points[$id] = $v;
        }
    }
    $id = is_string($in['id'] ?? null) ? $in['id'] : '';
    if ($action === 'set' || $action === 'clear') {
        if (!in_array($id, $allowed, true)) {
            return [$status, 'Тази точка не е твоя.'];
        }
    }
    if ($action === 'set') {
        $state = $in['state'] ?? '';
        if (!in_array($state, V3D_STATES, true)) {
            return [$status, 'Непознато състояние.'];
        }
        $entry = ['state' => $state, 'updated' => $stamp];
        $note = array_filter(['bg' => v3d_clean_note($in['note_bg'] ?? ''), 'en' => v3d_clean_note($in['note_en'] ?? '')],
            fn($s) => $s !== '');
        if ($note) {
            $entry['note'] = $note;
        }
        $points[$id] = $entry;
    } elseif ($action === 'clear') {
        unset($points[$id]);
    } elseif ($action === 'confirm') {
        $touched = 0;
        foreach ($allowed as $a) {
            if (isset($points[$a])) {
                $points[$a]['updated'] = $stamp;
                $touched++;
            }
        }
        if (!$touched) {
            return [$status, 'Няма записано състояние за потвърждаване.'];
        }
    } else {
        return [$status, 'Непознато действие.'];
    }
    $out = ['schema_version' => '1', 'updated' => $stamp, 'max_age_min' => $maxAgeMin, 'hotspots' => (object)$points];
    return [$out, ''];
}

/** Запис наведнъж: временен файл до целта и rename — четящият никога не вижда половин файл. */
function v3d_write_json(string $path, array $data): void
{
    $json = json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
    $tmp = $path . '.' . bin2hex(random_bytes(4)) . '.tmp';
    $ok = file_put_contents($tmp, $json . "\n") !== false;
    if ($ok) {
        @chmod($tmp, 0644);                 // страницата го чете през уеб сървъра
        $ok = rename($tmp, $path);
    }
    if (!$ok) {
        @unlink($tmp);
        throw new RuntimeException('не успях да запиша ' . basename($path));
    }
}

/** Действието под ключалка: двама на входа едновременно не си губят записите. */
function v3d_update(array $cfg, string $action, array $in, array $allowed, array $hotspots, DateTimeImmutable $now): string
{
    v3d_state_dir($cfg);
    $lock = fopen($cfg['state_dir'] . '/status.lock', 'c');
    if (!$lock || !flock($lock, LOCK_EX)) {
        throw new RuntimeException('няма ключалка');
    }
    try {
        $status = v3d_read_json($cfg['status_json']) ?? [];
        [$new, $err] = v3d_apply($status, $action, $in, $allowed, $hotspots, $now, $cfg['max_age_min']);
        if ($err === '') {
            v3d_write_json($cfg['status_json'], $new);
        }
        return $err;
    } finally {
        flock($lock, LOCK_UN);
        fclose($lock);
    }
}

function v3d_state_dir(array $cfg): void
{
    if (!is_dir($cfg['state_dir']) && !@mkdir($cfg['state_dir'], 0700, true)) {
        throw new RuntimeException('няма папка за състоянието');
    }
}

// ------------------------------------------------------------ опити за ПИН (по адрес, без да се пази самият адрес)

function v3d_fail_key(array $cfg, string $ip): string
{
    return hash_hmac('sha256', $ip, (string)($cfg['salt'] ?? 'venue3d'));
}

function v3d_fails(array $cfg, string $ip, int $now): array
{
    $all = v3d_read_json($cfg['state_dir'] . '/pin_fails.json') ?? [];
    return array_values(array_filter($all[v3d_fail_key($cfg, $ip)] ?? [], fn($t) => $t > $now - V3D_FAIL_WINDOW));
}

function v3d_pin_blocked(array $cfg, string $ip, int $now): bool
{
    return count(v3d_fails($cfg, $ip, $now)) >= V3D_MAX_FAILS;
}

function v3d_pin_failed(array $cfg, string $ip, int $now): void
{
    v3d_state_dir($cfg);
    $path = $cfg['state_dir'] . '/pin_fails.json';
    $all = v3d_read_json($path) ?? [];
    foreach ($all as $k => $times) {       // старите опити не се пазят
        $all[$k] = array_values(array_filter((array)$times, fn($t) => $t > $now - V3D_FAIL_WINDOW));
        if (!$all[$k]) {
            unset($all[$k]);
        }
    }
    $all[v3d_fail_key($cfg, $ip)][] = $now;
    v3d_write_json($path, $all);
}

/** Дневник: кой, кога, какво — извън public_html, ред JSON на промяна. */
function v3d_log(array $cfg, array $entry): void
{
    v3d_state_dir($cfg);
    @file_put_contents($cfg['state_dir'] . '/vhod.log',
        json_encode($entry, JSON_UNESCAPED_UNICODE) . "\n", FILE_APPEND | LOCK_EX);
}

/** „преди 12 мин.“ / „изтекло — провери“ за формата. */
function v3d_age_text(?string $iso, $maxAgeMin, DateTimeImmutable $now): array
{
    $t = $iso ? strtotime($iso) : false;
    if ($t === false) {
        return ['', false];
    }
    $min = (int)floor(($now->getTimestamp() - $t) / 60);
    $fresh = $min >= -5 && ($maxAgeMin === null || $min <= $maxAgeMin);
    $text = $min < 1 ? 'току-що' : ($min < 120 ? "преди $min мин." : 'преди ' . intdiv($min, 60) . ' ч.');
    return [$text, $fresh];
}
