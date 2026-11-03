<?php
// Сграда в 3D — формата за входа: човекът на входа казва „отворен / опашка / затворен“ от телефона.
// Пише status.json до страницата на сградата; посетителите го виждат до минута (<venue-3d status=… refresh=60>).
// Вход с ПИН (всеки човек свой, в config извън public_html); всеки вижда само своите точки.
// Без JavaScript: обикновени формуляри, работи на всеки телефон. Бисквитка само за сесията на служителя.

declare(strict_types=1);
require __DIR__ . '/lib.php';

header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'");

$STATE_WORD = ['open' => 'Отворен', 'busy' => 'Опашка', 'closed' => 'Затворен'];

function h($s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

function page(string $body, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html lang="bg"><head><meta charset="utf-8">'
        . '<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
        . '<title>Вход · състояние</title><style>' . STYLE . '</style></head><body><main>' . $body . '</main></body></html>';
    exit;
}

const STYLE = <<<'CSS'
:root { --bg: #f3f5f8; --fg: #1d232b; --muted: #5f6b78; --panel: #fff; --border: rgba(20,30,40,.14);
  --open: #2f9e5b; --busy: #d99a1e; --closed: #c8412f; color-scheme: light dark; }
@media (prefers-color-scheme: dark) { :root { --bg: #0e1217; --fg: #e6eaef; --muted: #9aa6b2; --panel: #171c23; --border: rgba(255,255,255,.12); } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 17px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 560px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.25rem; margin: 4px 0 12px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px; margin: 0 0 14px; }
.card h2 { font-size: 1.1rem; margin: 0 0 4px; }
.now { color: var(--muted); margin: 0 0 10px; font-size: .95rem; }
.now b { color: var(--fg); }
.old { color: var(--closed); font-weight: 600; }
.states { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 8px 0; }
button, input { font: inherit; }
.states button { min-height: 58px; border-radius: 12px; border: 2px solid var(--c); background: transparent; color: var(--fg); font-weight: 700; cursor: pointer; }
.states button[aria-pressed="true"] { background: var(--c); color: #fff; }
.b-open { --c: var(--open); } .b-busy { --c: var(--busy); } .b-closed { --c: var(--closed); }
label { display: block; font-size: .9rem; color: var(--muted); margin-top: 6px; }
input[type=text], input[type=password] { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg); color: var(--fg); }
input[type=password] { font-size: 1.6rem; letter-spacing: .3em; text-align: center; }
.wide { width: 100%; min-height: 54px; border-radius: 12px; border: 0; background: var(--fg); color: var(--bg); font-weight: 700; cursor: pointer; margin-top: 10px; }
.quiet { background: transparent; border: 1px solid var(--border); color: var(--muted); border-radius: 10px; padding: 8px 12px; cursor: pointer; }
.msg { padding: 10px 12px; border-radius: 10px; margin: 0 0 14px; background: #e6f4ea; color: #1e5631; }
.err { background: #fdecea; color: #7a1d14; }
.enter { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
details summary { color: var(--muted); font-size: .9rem; cursor: pointer; margin-top: 6px; }
CSS;

// ------------------------------------------------------------ сесия

try {
    $cfg = v3d_config();
    date_default_timezone_set($cfg['timezone']);
} catch (Throwable $e) {
    error_log('venue3d vhod: ' . $e->getMessage());
    page('<h1>Формата не е настроена</h1><p>Липсва config извън публичната папка.</p>', 500);
}

$https = ($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? '') !== 'off';
session_name('v3dvhod');
session_set_cookie_params(['lifetime' => 0, 'path' => dirname($_SERVER['SCRIPT_NAME'] ?? '/') ?: '/',
    'secure' => $https, 'httponly' => true, 'samesite' => 'Strict']);
session_start();
$_SESSION['csrf'] ??= bin2hex(random_bytes(16));

$venue = v3d_read_json($cfg['venue_json']);
if (!$venue) {
    page('<h1>Няма venue.json</h1><p>Пътят в config не сочи към сградата.</p>', 500);
}
$hotspots = v3d_hotspots($venue);
$ip = (string)($_SERVER['REMOTE_ADDR'] ?? '');
$now = new DateTimeImmutable('now');
$self = h(basename($_SERVER['SCRIPT_NAME'] ?? 'vhod.php'));

function back(string $flash = '', bool $error = false): void
{
    $_SESSION['flash'] = [$flash, $error];
    header('Location: ' . basename($_SERVER['SCRIPT_NAME'] ?? 'vhod.php'), true, 303);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    if (!hash_equals($_SESSION['csrf'], (string)($_POST['csrf'] ?? ''))) {
        back('Формата е остаряла — опитай пак.', true);
    }
    $act = (string)($_POST['act'] ?? '');
    if ($act === 'login') {
        if (v3d_pin_blocked($cfg, $ip, time())) {
            back('Твърде много грешни ПИН-ове. Опитай пак след 15 минути.', true);
        }
        $found = v3d_find_person($cfg['people'], trim((string)($_POST['pin'] ?? '')));
        if (!$found) {
            v3d_pin_failed($cfg, $ip, time());
            back('Грешен ПИН.', true);
        }
        session_regenerate_id(true);
        $_SESSION['who'] = $found[0];
        back();
    }
    if ($act === 'logout') {
        $_SESSION = [];
        session_regenerate_id(true);
        back('Излезе.');
    }
    $who = $_SESSION['who'] ?? null;
    $person = $who !== null ? ($cfg['people'][$who] ?? null) : null;
    if (!$person) {
        back('Влез с ПИН.', true);
    }
    $allowed = v3d_allowed($person, $hotspots);
    try {
        $err = v3d_update($cfg, $act, $_POST, $allowed, $hotspots, $now);
    } catch (Throwable $e) {
        error_log('venue3d vhod: ' . $e->getMessage());
        back('Не успях да запиша. Опитай пак след малко.', true);
    }
    if ($err !== '') {
        back($err, true);
    }
    $id = (string)($_POST['id'] ?? '');
    v3d_log($cfg, ['t' => $now->format('c'), 'who' => $who, 'act' => $act, 'id' => $id ?: null,
        'state' => $act === 'set' ? $_POST['state'] : null]);
    $name = $hotspots[$id]['name'] ?? '';
    back(match ($act) {
        'set' => "Записано: $name — " . $STATE_WORD[$_POST['state']] . '.',
        'clear' => "Изчистено: $name — посетителите не виждат състояние.",
        default => 'Потвърдено: нищо не се е променило.',
    });
}

// ------------------------------------------------------------ страница

[$flash, $isErr] = $_SESSION['flash'] ?? ['', false];
unset($_SESSION['flash']);
$msg = $flash !== '' ? '<p class="msg' . ($isErr ? ' err' : '') . '" role="status">' . h($flash) . '</p>' : '';
$csrf = '<input type="hidden" name="csrf" value="' . h($_SESSION['csrf']) . '">';
$title = h(is_array($venue['name'] ?? null) ? ($venue['name']['bg'] ?? $venue['name']['en'] ?? '') : ($venue['name'] ?? ''));

$who = $_SESSION['who'] ?? null;
$person = $who !== null ? ($cfg['people'][$who] ?? null) : null;
if (!$person) {
    page("<h1>$title · вход</h1>$msg<form class=\"card\" method=\"post\" action=\"$self\">$csrf"
        . '<input type="hidden" name="act" value="login"><label for="pin">ПИН</label>'
        . '<input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required autofocus>'
        . '<button class="wide" type="submit">Влез</button></form>');
}

$status = v3d_read_json($cfg['status_json']) ?? [];
$points = $status['hotspots'] ?? [];
$allowed = v3d_allowed($person, $hotspots);
$max = $cfg['max_age_min'];
$cards = '';
foreach ($allowed as $id) {
    $cur = is_array($points[$id] ?? null) ? $points[$id] : null;
    $state = $cur['state'] ?? '';
    [$ago, $fresh] = v3d_age_text($cur['updated'] ?? ($status['updated'] ?? null), $max, $now);
    $now_line = $cur
        ? 'Сега: <b>' . h($STATE_WORD[$state] ?? '?') . '</b> · ' . h($ago)
          . ($fresh ? '' : ' · <span class="old">изтекло — посетителите не го виждат</span>')
        : 'Сега: <b>няма състояние</b> — посетителите не виждат нищо';
    // Enter в бележката праща първия бутон във формата: този скрит бутон запазва текущото състояние
    // (без състояние е изключен — Enter не прави нищо), за да не стане входът „отворен“ по погрешка
    $buttons = '<button class="enter" name="state" value="' . h($state) . '" tabindex="-1" aria-hidden="true"'
        . ($state === '' ? ' disabled' : '') . '>Запази бележката</button>';
    $buttons .= '<div class="states">';
    foreach ($STATE_WORD as $k => $word) {
        $buttons .= "<button class=\"b-$k\" name=\"state\" value=\"$k\" aria-pressed=\"" . ($k === $state ? 'true' : 'false') . '">'
            . h($word) . '</button>';
    }
    $buttons .= '</div>';
    $note = $cur['note'] ?? [];
    $cards .= '<section class="card"><h2>' . h($hotspots[$id]['name']) . "</h2><p class=\"now\">$now_line</p>"
        . "<form method=\"post\" action=\"$self\">$csrf<input type=\"hidden\" name=\"act\" value=\"set\">"
        . '<input type="hidden" name="id" value="' . h($id) . '">'
        . '<label for="n-' . h($id) . '">Бележка за посетителите (по избор)</label>'
        . '<input id="n-' . h($id) . '" name="note_bg" type="text" maxlength="' . V3D_NOTE_MAX . '" value="' . h($note['bg'] ?? '')
        . '" placeholder="напр. опашка около 10 минути">'
        . '<details' . (!empty($note['en']) ? ' open' : '') . '><summary>и на английски</summary>'
        . '<input name="note_en" type="text" maxlength="' . V3D_NOTE_MAX . '" value="' . h($note['en'] ?? '') . '" lang="en"></details>'
        . "$buttons</form>"
        . ($cur ? "<form method=\"post\" action=\"$self\">$csrf<input type=\"hidden\" name=\"act\" value=\"clear\">"
            . '<input type="hidden" name="id" value="' . h($id) . '"><button class="quiet" type="submit">Не знам — изчисти</button></form>' : '')
        . '</section>';
}
if (!$allowed) {
    $cards = '<p class="card">Нямаш зададени точки. Помоли отговорника да ги добави в настройките.</p>';
}
$limit = $max === null ? '' : "Всяко състояние важи $max мин. — после изчезва за посетителите, докато не го потвърдиш.";
page("<div class=\"row\"><h1>$title</h1><form method=\"post\" action=\"$self\">$csrf"
    . '<input type="hidden" name="act" value="logout"><button class="quiet" type="submit">Изход</button></form></div>'
    . $msg . '<p class="now">' . h($who) . ($limit ? ' · ' . h($limit) : '') . '</p>' . $cards
    . ($allowed ? "<form method=\"post\" action=\"$self\">$csrf<input type=\"hidden\" name=\"act\" value=\"confirm\">"
        . '<button class="wide" type="submit">Нищо не се е променило — потвърди всичко</button></form>' : ''));
