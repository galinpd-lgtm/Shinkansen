<?php
// Приема отговор на въпросник: JSON (от forms.js) или обикновен POST (без JS).
// Записва само полетата от forms.json, всеки въпросник в своя таблица; паролата е в config извън public_html.
// Без имейли, без бисквитки, без IP адреси в отговорите.

declare(strict_types=1);
require __DIR__ . '/lib.php';

header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

$isJson = stripos($_SERVER['CONTENT_TYPE'] ?? '', 'application/json') === 0;

function reply(bool $ok, int $code, string $msg, array $extra = [], string $back = ''): void
{
    global $isJson;
    http_response_code($code);
    if ($isJson) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['ok' => $ok, 'error' => $ok ? null : $msg] + $extra, JSON_UNESCAPED_UNICODE);
    } elseif ($ok && $back !== '') {
        header('Location: ../' . $back . '.html?ok=1', true, 303);
    } else {
        header('Content-Type: text/html; charset=utf-8');
        echo '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>Въпросник</title>'
            . '<p>' . htmlspecialchars($ok ? 'Благодарим! Отговорите са записани.' : $msg, ENT_QUOTES, 'UTF-8') . '</p>'
            . '<p><a href="../index.html">Към началото</a></p>';
    }
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    reply(false, 405, 'Само POST.');
}
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > ORGANIZER_MAX_BODY) {
    reply(false, 413, 'Отговорът е твърде голям.');
}

if ($isJson) {
    $in = json_decode((string)file_get_contents('php://input', false, null, 0, ORGANIZER_MAX_BODY), true);
    if (!is_array($in)) {
        reply(false, 400, 'Повреден отговор.');
    }
} else {
    $in = $_POST;
}

try {
    $spec = organizer_spec();
} catch (Throwable $e) {
    error_log('organizer: ' . $e->getMessage());
    reply(false, 500, 'Въпросникът не е настроен.');
}

$formId = is_string($in['_form'] ?? null) ? $in['_form'] : '';
if (!isset($spec['forms'][$formId])) {
    reply(false, 400, 'Непознат въпросник.');
}
$form = $spec['forms'][$formId];

// Капан за ботове: скритото поле е попълнено или формулярът е изпратен за под 3 секунди.
// Отговаряме „добре“, за да не учим бота, но нищо не записваме.
$t = $in['_t'] ?? '';
if (organizer_str($in['_hp'] ?? '') !== '' || ($t !== '' && (int)$t < 3)) {
    reply(true, 200, '', [], $form['slug']);
}

[$answers, $errors] = organizer_validate($form, $in);
if ($errors) {
    reply(false, 422, implode(' · ', $errors), ['fields' => array_keys($errors)]);
}

try {
    $cfg = organizer_config($spec);
    $pdo = organizer_pdo($cfg);
    organizer_auto_create($pdo, $cfg, $spec);
    if (!organizer_rate_ok($pdo, $cfg, $spec, (string)($_SERVER['REMOTE_ADDR'] ?? ''))) {
        reply(false, 429, 'Твърде много изпращания от този адрес. Опитай пак след час.');
    }
    $table = organizer_safe_table($form['table']);
    [$general, $personal] = organizer_split($form, $answers);
    $now = gmdate('Y-m-d H:i:s');
    $pdo->beginTransaction();
    $st = $pdo->prepare("INSERT INTO `$table` (created_at, answers) VALUES (?, ?)");
    $st->execute([$now, json_encode((object)$general, JSON_UNESCAPED_UNICODE)]);
    if ($personal) {
        $id = (int)$pdo->lastInsertId();
        $contact = organizer_safe_table($form['contact_table']);
        $pdo->prepare("INSERT INTO `$contact` (response_id, created_at, data) VALUES (?, ?, ?)")
            ->execute([$id, $now, json_encode($personal, JSON_UNESCAPED_UNICODE)]);
    }
    $pdo->commit();
} catch (Throwable $e) {
    if (isset($pdo) && $pdo->inTransaction()) {
        $pdo->rollBack();
    }
    error_log('organizer: ' . $e->getMessage());
    reply(false, 500, 'Не успях да запиша отговорите. Опитай пак след малко.');
}

reply(true, 200, '', [], $form['slug']);
