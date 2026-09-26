# Помощници — skills/

Малки общи инструменти, които хора и агенти викат по един и същи начин. Всеки е папка с описание
`SKILL.md`, изпълним файл до него и тестове. Без наши адреси и данни — те идват като аргументи или
конфигурация извън репото.

| Помощник | Какво прави | Ниво |
|---|---|---|
| [`weather-now`](weather-now/SKILL.md) | „Вали ли сега“: няколко безплатни източника + METAR по ICAO | чете |
| [`pdf-contact-sheet`](pdf-contact-sheet/SKILL.md) | всички страници на PDF в една картинка-мрежа с номера | чернови |
| [`leak-filter`](leak-filter/SKILL.md) | изтичания в папка и в цялата git история; само докладва | чете |
| [`pr-live-check`](pr-live-check/SKILL.md) | pull request в отделна папка → тестове → отчет до 20 реда; не слива | чете |
| [`share-single-file`](share-single-file/SKILL.md) | HTML + локалните му JS/CSS/данни → един файл без сървър | чернови |
| [`preview-serve`](preview-serve/SKILL.md) | временен статичен сървър, спира сам след N минути | действа |

## Командата

```bash
bin/shinkansen list                       # скиловете с описание и ниво
bin/shinkansen show leak-filter           # отпечатва SKILL.md
bin/shinkansen run leak-filter . --words ~/.config/shinkansen/leak-words.txt
```

`run` пуска помощника със същия Python и му подава аргументите както са. Кодът на изход е неговият.

### Дневник на ходовете: `SHINKANSEN_RUNS`

Ако е зададена, всеки `run` добавя един ред в `$SHINKANSEN_RUNS/<скил>.jsonl`:

```json
{"t": "2026-09-26T12:51:44+00:00", "helper": "leak-filter", "ok": true, "summary": "чисто · exit 0 · 0.8s"}
```

По него частното табло разбира кой помощник мълчи или пада. Редът **никога не носи данни от входа**:
`summary` е кратко обобщение, което помощникът сам пише във файла от `SHINKANSEN_SUMMARY_FILE`
(напр. `чисто`, `3 проверки, 1 паднаха`), плюс кода на изход и времето. Аргументите и изходът не влизат.

### Кодове на изход (общи)

| Код | Значи | `ok` |
|---|---|---|
| 0 | готово / чисто | да |
| 4 | помощникът работи, но има находки (изтичане, паднал тест) | да |
| 1 | помощникът падна (или всичките му източници) | не |
| 2 | грешна употреба | не |
| 3 | липсва зависимост (pymupdf, esbuild…) | не |

## Формат на скил

```
skills/<име>/
  SKILL.md          frontmatter (name, description) + разделите по-долу
  <име_с_долни_черти>.py
  tests/test_*.py   python unittest, без мрежа където е възможно
```

`SKILL.md`:

```markdown
---
name: <име>                 # като папката: малки латински букви, цифри, тире
description: Какво прави и КОГА се ползва — думите, при които агентът трябва да се сети за него.
metadata:
  description_en: What it does, in English — for the public showcase catalogue.
---

# <име> — едно изречение

## Какво иска
## Какво връща
## Ниво
чете | чернови | действа — и защо
## Къде тече
## Пример
```

Стойностите във frontmatter са YAML: без кавичка или специален знак в началото и без „: “ в текста
(тестът в `bin/tests` го проверява). `metadata.description_en` отива в каталога на витрината; без него там
стои българското описание.

Нивата са по PROTOCOL.md, т. 6: **чете** — нищо не променя; **чернови** — пише само нов файл-изход, без да
презаписва; **действа** — прави нещо навън (тук: отваря порт) и трябва да е поискано изрично.

Форматът е същият като на скиловете на Claude Code. `.claude/skills` в репото е символна връзка към
`skills/`, така че Claude Code, пуснат в Shinkansen, ги зарежда директно. За всички проекти на машината:
`ln -s "$PWD/skills/leak-filter" ~/.claude/skills/leak-filter` (по един на скил).

Помощникът пише обобщението си така:

```python
def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
```

## Тестове

```bash
python3 -m unittest discover -s bin/tests -v                  # диспечерът + формата на всички скилове
for d in skills/*/tests; do python3 -m unittest discover -s "$d" || exit 1; done
```

Мрежа не е нужна. Тестовете за рендер на PDF и за истински esbuild се пропускат, ако ги няма.
