<?php
// Износ на отговорите в CSV. Папката admin/ се заключва с парола от cPanel („Directory Privacy“).
// Без заключване страницата отказва: проверяваме, че сървърът е поискал вход (REMOTE_USER).
// PHP_AUTH_USER не се ползва — при някои сървъри идва направо от заглавката на заявката, без проверка.

declare(strict_types=1);
require __DIR__ . '/../api/lib.php';

header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow');
header('Cache-Control: no-store');

$user = $_SERVER['REMOTE_USER'] ?? $_SERVER['REDIRECT_REMOTE_USER'] ?? '';
if ($user === '') {
    http_response_code(403);
    header('Content-Type: text/plain; charset=utf-8');
    echo "Папката admin/ не е заключена с парола. Заключи я от cPanel → Directory Privacy и опитай пак.\n";
    exit;
}

try {
    $spec = organizer_spec();
    $cfg = organizer_config($spec);
    $pdo = organizer_pdo($cfg);
    organizer_auto_create($pdo, $cfg, $spec);
} catch (Throwable $e) {
    error_log('organizer export: ' . $e->getMessage());
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo "Базата не е настроена.\n";
    exit;
}

$formId = is_string($_GET['form'] ?? null) ? $_GET['form'] : '';
if (!isset($spec['forms'][$formId])) {
    $counts = [];
    foreach ($spec['forms'] as $id => $f) {
        $t = organizer_safe_table($f['table']);
        try {
            $counts[$id] = $pdo->query("SELECT COUNT(*) n, MAX(created_at) last FROM `$t`")->fetch();
        } catch (Throwable $e) {
            $counts[$id] = ['n' => 0, 'last' => 'няма таблица — пусни sql/schema.sql'];
        }
    }
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex"><title>Износ</title>'
        . '<style>body{font:16px/1.5 system-ui;margin:2em}td,th{padding:.4em 1em;text-align:left}</style>'
        . '<h1>Отговори: ' . htmlspecialchars($spec['event'], ENT_QUOTES, 'UTF-8') . '</h1><table><tr><th>Въпросник</th><th>Брой</th><th>Последен (UTC)</th><th></th></tr>';
    foreach ($spec['forms'] as $id => $f) {
        $c = $counts[$id] ?? ['n' => 0, 'last' => '—'];
        echo '<tr><td>' . htmlspecialchars($f['title'], ENT_QUOTES, 'UTF-8') . '</td><td>' . (int)$c['n'] . '</td><td>'
            . htmlspecialchars((string)$c['last'], ENT_QUOTES, 'UTF-8') . '</td><td><a href="?form=' . rawurlencode($id) . '">CSV</a></td></tr>';
    }
    echo '</table>';
    exit;
}

$form = $spec['forms'][$formId];
header('Content-Type: text/csv; charset=utf-8');
header('Content-Disposition: attachment; filename="' . $spec['event'] . '_' . $formId . '_' . gmdate('Y-m-d') . '.csv"');
$out = fopen('php://output', 'w');
fwrite($out, "\xEF\xBB\xBF");  // BOM — Excel да познае UTF-8
$head = ['№', 'Кога (UTC)'];
foreach ($form['fields'] as $f) {
    $head[] = $f['label'];
}
fputcsv($out, $head);
$table = organizer_safe_table($form['table']);
$st = $pdo->query("SELECT id, created_at, answers FROM `$table` ORDER BY id");
foreach ($st as $r) {
    $a = json_decode($r['answers'], true) ?: [];
    $row = [$r['id'], $r['created_at']];
    foreach ($form['fields'] as $f) {
        $row[] = organizer_csv_cell($a[$f['id']] ?? '');
    }
    fputcsv($out, $row);
}
fclose($out);
