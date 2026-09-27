<?php
// Копие на този файл отива ИЗВЪН public_html — например ~/.organizer/<slug>.php
// (родителят на DOCUMENT_ROOT + /.organizer/). Попълва се на сървъра, никога в репото.
return [
    'db' => [
        'host'   => 'localhost',
        'name'   => 'ИМЕ_НА_БАЗАТА',
        'user'   => 'ПОТРЕБИТЕЛ',
        'pass'   => 'ПАРОЛА',
        'prefix' => '',  // напр. 'ev_' → таблица ev_responses; само a-z0-9_
    ],
];
