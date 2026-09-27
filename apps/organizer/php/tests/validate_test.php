<?php
// Тестове на проверката без база и без сървър:  php php/tests/validate_test.php
declare(strict_types=1);
require __DIR__ . '/../lib.php';

$fails = 0;
function ok(bool $cond, string $name): void
{
    global $fails;
    echo ($cond ? "ok   " : "FAIL ") . $name . "\n";
    if (!$cond) {
        $fails++;
    }
}

$form = ['fields' => [
    ['id' => 'rolya', 'type' => 'single', 'label' => 'Роля', 'required' => true, 'options' => ['А', 'Б'], 'other' => true],
    ['id' => 'temi', 'type' => 'multi', 'label' => 'Теми', 'required' => false, 'options' => ['1', '2', '3'], 'max' => 2, 'other' => false],
    ['id' => 'ime', 'type' => 'text', 'label' => 'Име', 'required' => false, 'max_length' => 5],
    ['id' => 'email', 'type' => 'email', 'label' => 'Имейл', 'required' => false, 'max_length' => 254],
    ['id' => 'saglasie', 'type' => 'consent', 'label' => 'Съгласие', 'required' => false, 'required_if' => ['ime', 'email']],
]];

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'temi' => ['1', '2'], 'evil' => 'x']);
ok(!$e && $a === ['rolya' => 'А', 'temi' => ['1', '2']], 'валиден отговор; непознатото поле не се записва');

[$a, $e] = organizer_validate($form, []);
ok(isset($e['rolya']) && count($e) === 1, 'задължителното липсва');

[$a, $e] = organizer_validate($form, ['rolya' => 'В']);
ok(isset($e['rolya']), 'опция извън списъка се отхвърля');

[$a, $e] = organizer_validate($form, ['rolya' => '__other', 'rolya__other' => 'Архитект']);
ok(!$e && $a['rolya'] === 'Друго: Архитект', '„Друго“ с текст');

[$a, $e] = organizer_validate($form, ['rolya' => '__other']);
ok(isset($e['rolya']), '„Друго“ без текст');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'temi' => ['1', '2', '3']]);
ok(isset($e['temi']), 'повече от max');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'temi' => ['__other']]);
ok(isset($e['temi']), '„Друго“ не е позволено там, където го няма');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'ime' => 'Иванка']);
ok(isset($e['ime']), 'max_length се брои в знаци (6 > 5)');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'ime' => 'Иван']);
ok(isset($e['saglasie']), 'име без съгласие → съгласието е задължително');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'ime' => 'Иван', 'saglasie' => '1']);
ok(!$e && $a['saglasie'] === true, 'име със съгласие');

[$a, $e] = organizer_validate($form, ['rolya' => 'А', 'email' => 'не-имейл']);
ok(isset($e['email']), 'невалиден имейл');

[$a, $e] = organizer_validate($form, ['rolya' => ['А']]);
ok(isset($e['rolya']), 'масив вместо низ за single');

[$a, $e] = organizer_validate($form, ['rolya' => "  А\0 "]);
ok(!$e && $a['rolya'] === 'А', 'NUL и интервали се чистят');

ok(organizer_csv_cell('=HYPERLINK("x")') === "'=HYPERLINK(\"x\")", 'CSV: формула се обезврежда');
ok(organizer_csv_cell(['a', 'b']) === 'a; b', 'CSV: списък');
ok(organizer_csv_cell(true) === 'да', 'CSV: съгласие');
ok(organizer_csv_cell('-5') === "'-5", 'CSV: минус в началото');

echo $fails ? "\n$fails неуспешни\n" : "\nвсички минаха\n";
exit($fails ? 1 : 0);
