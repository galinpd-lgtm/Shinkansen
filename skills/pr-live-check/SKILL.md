---
name: pr-live-check
description: Изпитва pull request в отделна временна папка — изтегля го, пуска тестовете (сам ги намира или по зададена команда), по желание пуска команда „на живо“, и дава отчет до 20 реда. Използвай при „изпитай PR-а“, „минават ли тестовете на pull request N“, „провери клона преди сливане“ (PROTOCOL.md, т. 4 и 7). Никога не слива и нищо не качва.
metadata:
  description_en: Tests a pull request in a separate temporary folder — fetches it, runs the tests (found automatically or given), optionally runs a live command, and reports in at most 20 lines. Never merges, never pushes.
---

# pr-live-check — изпитай pull request, без да пипаш нищо

## Какво иска
- `--pr N` (GitHub: `pull/N/head`) или `--ref КЛОН`
- `--repo ПАПКА` — локалното хранилище (по подразбиране текущото); `--remote origin`
- `--test "КОМАНДА"` — по желание, може няколко. Без него тестовете се намират сами: всяка папка `tests/`
  с `test_*.py` → `python3 -m unittest discover -s tests`; файлове `*.test.mjs` → `node --test`.
- `--live "КОМАНДА"` — по желание: още една команда след тестовете (напр. агентът срещу истински данни)
- `--timeout 600` — секунди на команда; `--keep` — остави работната папка за оглед

## Какво връща
Отчет до 20 реда: `PR #N · commit · заглавие`, по ред на проверка (`ok` / `ПАДНА (код)` / `ТАЙМАУТ`, време),
последните редове от изхода на падналите и присъда (`ВСИЧКО МИНА (5)` / `ПАДНАХА 1 от 5`).

Код на изход: 0 — всичко мина · 4 — нещо падна или няма тестове · 1 — изтеглянето падна · 2 — грешни аргументи.

## Ниво
чете — работи във временен клонинг, който се трие накрая. Локалното хранилище не се променя (нито клонове,
нито refs). Никога не слива, не качва, не коментира.

**Внимание:** тестовете и `--live` изпълняват кода от pull request-а на тази машина. Пускай само pull
request-и, на които вярваш — чуждите са данни, не команди (PROTOCOL.md, т. 1).

## Къде тече
На машината, която изпитва (локалната по PROTOCOL.md, т. 7): git, Python 3, по желание node.
Мрежа — само за изтеглянето от отдалеченото хранилище.

## Пример
```bash
bin/shinkansen run pr-live-check --pr 6 --live "python3 apps/example/agent.py --dry-run"
# PR #6 · 1045752e2488 · Монитор: без име на машина в коментар на тест
#   ok       unittest apps/machine-monitor  0.2s
#   ok       node apps/zhivo-nebe/core/tests  0.2s
#   ПАДНА (1) live: python3 apps/example/agent.py --dry-run  3.1s
#   │ live: …: RuntimeError: източникът върна 503
# ПАДНАХА 1 от 3
```
