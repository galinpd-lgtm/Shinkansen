# event.json — описанието на събитие

Пълен пример: [`examples/intensive/event.json`](examples/intensive/event.json). Задължителните са с ✱.
В текстовете: `**удебелено**` и `[текст](https://… или страница.html)`. Всичко друго се екранира.

| Ключ | Какво е |
|---|---|
| `slug` ✱ | латиница, цифри, тире; оттук идват имената на таблиците |
| `lang` | `bg` по подразбиране |
| `title` ✱ · `tagline` · `description` | заглавие, подзаглавие, описание за търсачките (датата се добавя сама) |
| `brand.name` ✱ · `brand.logo` · `brand.ribbon` · `brand.legal` | марката горе (или лого от `assets/`), лентата над нея, правното име долу |
| `theme` | `accent`, `ink`, `paper`, `hero_bg`, `hero_ink` (`#rrggbb`); `accent_text` — по-тъмен оттенък за дребен текст, когато акцентът е светъл (контраст ≥ 4,5:1); `on_accent` — текстът върху бутоните; `font_display`, `font_body`, `font_mono`, `font_brand` (само името на марката — за шрифт без кирилица); `stylesheets` — локални CSS (напр. `assets/fonts/fonts.css` за офлайн); `fonts_css` — само `https://fonts.googleapis.com/…` |
| `dates.from` ✱ · `dates.to` ✱ · `dates.label` | ГГГГ-ММ-ДД; `label` е как да се изпише |
| `place` | `name`, `seats`, `note` |
| `publish` | `indexable` (false до „go“), `base_url`, `forbid_text` (низове), `forbid_regex` (изрази, напр. `(?<!Е)ООД`), `pending_marker` (по подразбиране `[ЧАКА`) |
| `server` | `config_file` — пътят на config спрямо папката над `public_html` (по подразбиране `.organizer/<slug>.php`); `rate_limit_per_hour` (10); `rate_table` |
| `cta` | `label` и `form` — id на въпросника, към който води бутонът |
| `home.hero_note` | един ред под заглавието, напр. „Подгряващо събитие за [конференция](https://…)“ |
| `home.stats` | `[{value, label}]` — „три числа“ |
| `home.sections` | раздели `{title, intro, items[{title,text}], table{head[], rows[[]]}, list[], images[]}` |
| `…media` | в `topics[].demo`, `topics[].sections[]`, `home.sections[]`, `gallery.groups[]`: `[{src ✱, alt ✱, caption, poster}]`. Картинка (`.jpg .png .webp .gif .svg`) → lazy, клик отваря пълния файл; видео (`.mp4 .webm`) → `controls muted playsinline preload="metadata"`, без autoplay, `poster` по желание. Решетка: 1 колона до 480 px, 2 до 900 px, 3 над това. `caption` минава през markdown. `check`: липсващ файл е грешка; картинка над 800 KB и видео над 6 MB — предупреждение. `images` е по-старото име (само картинки) и още работи |
| `gallery` | `{title, intro, groups: [{title, intro, media: […]}]}` → `galeria.html` в менюто |
| `program_intro` · `schedule_intro` | увод на „Програмата“ и „Разписание“ |
| `lab_roles` | `{id, label, text}` — колоните на лабораторията и картите „За кого“ |
| `topics` | `{n ✱, title ✱, slug, question, summary, goals[], concepts[{term,text}], sections[], demo{title,intro,steps[]}, lab{роля:[…]}, takeaways[], source{title,text}}` |
| `schedule` | дни `{date, label, intro, slots: [{from, to, title, topics:[n], pause}]}`; без час → липса, застъпване → грешка |
| `people` | `speakers_file` (`data/lektori.json`), `partners_file` (`data/partnyori.json`), `placeholders{speakers,partners}`, `speakers_intro`, `organizers_intro` |
| `organizers` | `[{name, role, text, link, logo}]` на „Организатори“; `role` — „Организатор“, „Съорганизатор“ и т.н., над името |
| `privacy` | `{title, intro, blocks[]}` → `privacy.html` (блоковете са като `home.sections`) |
| `forms` | `{id, slug, title, intro, table, nav, nav_label, fields[]}`; `nav: true` слага формуляра в менюто до основния (`cta.form`); slug не може да е име на страница или `tema-…` |
| `forms[].fields` | `{id, type, label, required, personal, help, group, options[] / options_from:"topics", other, other_label, max, max_length, required_if[]}`; `personal: true` (имейлът и съгласието — винаги) пази полето в отделната таблица `_kontakt` |

`"lab": false` и `"demo": false` скриват лабораторията и демото на тема, която няма такава по замисъл (напр. защитата) — без празни блокове и без липса в `check`. Изходник с празен текст (или само тире) не се показва; блок без ключ също не се показва.

Страницата на тема е `tema-01-<slug>.html`. Блоковете вървят в този ред: въпросът, какво ще можеш,
понятията, своите раздели, демото на живо, лабораторията, какво отнасяш вкъщи, изходникът.

# data/lektori.json и data/partnyori.json

Списък, по един запис на човек. С `name` е потвърден човек; само със `slot` е празно място:

```json
[
 {"slot": "Памет и бази данни"},
 {"name": "Име Фамилия", "role": "Тема 3", "bio": "Едно изречение.", "photo": "assets/hora/ime.jpg", "link": "https://…"}
]
```

`{"slot": "Памет и бази данни"}` се показва като „Лектор · Памет и бази данни — очаква потвърждение“.

# sources — съдържание от Markdown файлове (`organizer.py fill`)

Решенията и текстовете идват от бележки в Markdown: раздел `## N. …` и в него JSON блок в ограда с `json`.
`fill` ги влива в event.json **дословно** и показва разликата по ключове; `--dry-run` само я показва.

```json
"sources": [
 {"file": "izvori/demota.md", "block": "1", "pick": "demo_steps", "map": true,
  "target": "topics[n={key}].demo.steps", "mode": "extend"},
 {"file": "izvori/demota.md", "block": "2", "target": "home.sections", "mode": "upsert", "key": "title"}
]
```

| Ключ | Какво е |
|---|---|
| `file` ✱ | път спрямо папката на събитието (или абсолютен, `~/…`) |
| `block` ✱ | номерът на раздела („2“) или част от заглавието му |
| `index` | кой JSON блок в раздела (от 0) |
| `pick` | само този ключ от блока |
| `map` | блокът е `{ключ: стойност}`; `{key}` в `target` се заменя с всеки ключ |
| `target` ✱ | път: `home.sections`, `topics[n=3].demo`, `forms[id=zapis].fields`, `topics[0]` |
| `mode` | `set` (по подразбиране) · `merge` (обект в обект) · `append` · `extend` · `insert` (с `at`) · `upsert` (с `key`) |

Повторимо: `append`/`extend`/`insert` не добавят второ копие, `upsert` сменя елемента със същия `key`.
При запис старото става `event.json.orig_ДАТА` (второ копие в същия ден — `…-2`, нищо не се презаписва),
а в `decisions.md` се дописва кой източник → кой ключ и колко ключа са се сменили. `check` и `build`
спират, ако файл или раздел от `sources` липсва.
