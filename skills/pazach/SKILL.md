---
name: pazach
description: Пазач — чете готови състояния (monitor_lite /api/now, probe_device, произволен status.json, дати на изтичане), пише обобщен status.json за лентата и вика по webhook само при смяна на нивото и при възстановяване. Използвай при „следи машините“, „кажи ми, ако нещо падне“, „кога изтича сертификатът/домейнът“, „сутрешна сводка“, rip/off, настройка на таймерите на пазача.
---

# pazach — вика само когато нещо се промени

## Какво иска
- `--config ФАЙЛ` — JSON **извън репото** (виж `config.example.json`): `status_file`, `state_file`, по желание
  `webhook` (`url`, `timeout`, `headers`), `timeout_seconds`, `digest_expiry_days` и списък `checks`.
- режим: `--once` (един ход — таймер на 15 мин) или `--digest` (ход + сутрешна сводка); `--dry-run` — без webhook.

Проверки (всяка с `name`, по желание `link` и `"enabled": false` → `off`):

| `type` | Чете | Нива |
|---|---|---|
| `monitor` | `url` към `/api/now` на `monitor_lite.py` или `probe_device.py` | не отговаря или данните са по-стари от `stale_seconds` (300) → **rip**; `temp_warn_c`/`temp_crit_c` (80/90); `disk_warn_percent`/`disk_crit_percent` (85/95); RAID degraded → crit; паднали услуги → warn; задача над `task_max_hours` (6) → warn; последен успех по-стар от `success_max_hours` → warn; устройство недостъпно → rip, затворен порт → warn |
| `status_json` | `url` или `path`, `field` (прост път: `tasks.summary.last_success`, `items.0.level`) | `expect`; `warn_above`/`crit_above`/`warn_below`/`crit_below`; `warn_age_hours`/`crit_age_hours` за поле-време (epoch или ISO). Недостъпен → rip, липсващо поле → crit |
| `expiry` | `date` (ГГГГ-ММ-ДД), `what` | `warn_days` (30) → warn, `crit_days` (7) → crit, изтекло → crit |

## Какво връща
- **`status_file`** — атомарно (временен файл + подмяна), точно във формата на лентата:
  `{"generated", "overall": "ok|warn|crit", "counts": {"ok","warn","crit","rip","off"}, "items": [{"level","name","msg","link"}]}`.
  `rip` се брои към `crit` в `overall`; `off` не се брои. `link` е `null`, когато не е зададен.
- **Известия** — `POST` JSON към `webhook.url`: `{"level", "check", "message", "since"}`, само при смяна на нивото
  (ok→warn, warn→crit, crit→rip…) и при възстановяване (`"level": "ok"`, `"възстановено: …"`). Същото ниво с
  различни числа не вика. `since` е кога е започнало текущото ниво. Спирането (`off`) не вика.
  Неизпратено известие се опитва пак следващия ход. Сводката (`--digest`) е едно известие с `"check": "digest"`:
  всичко нередно + изтичащото до `digest_expiry_days` (14) дни.
- **`state_file`** — нивото, откога е и какво е изпратено за всяка проверка.
- Ред в `$SHINKANSEN_RUNS/pazach.jsonl` (под `bin/shinkansen` — чрез диспечера).

Код на изход: 0 — всичко ok · 4 — има warn/crit/rip · 1 — известие не мина или конфигурацията е счупена · 2 — грешна употреба.

## Ниво
действа — изпраща известия, но **само** към webhook-а, който човекът е записал в конфигурацията. Без `webhook`
(или с `--dry-run`) само пише `status_file` и `state_file` — тогава е чернови. Нищо не управлява на
наблюдаваните машини; към тях прави само `GET`.

## Къде тече
На машината, която вижда наблюдаваните (локалната). Python 3, без зависимости. Таймери за systemd в
`systemd/`: `pazach.timer` (на 15 мин) и `pazach-digest.timer` (всяка сутрин).

## Пример
```bash
bin/shinkansen run pazach --config ~/.config/shinkansen/pazach.json --once --dry-run
# → {"level": "rip", "check": "example-nas", "message": "не отговаря (timed out)", "since": "2026-09-26T05:15:02+00:00"}
# crit · ok 4, warn 1, crit 0, rip 1, off 1 · известия 1
```
