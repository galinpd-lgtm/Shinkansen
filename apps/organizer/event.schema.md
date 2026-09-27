# event.json — описанието на събитие

Пълен пример: [`examples/intensive/event.json`](examples/intensive/event.json). Задължителните са с ✱.

| Ключ | Какво е |
|---|---|
| `slug` ✱ | латиница, цифри, тире; име на таблицата-запис и на config файла |
| `lang` | `bg` по подразбиране |
| `title` ✱ · `tagline` · `description` | заглавие, подзаглавие, описание за търсачките |
| `brand.name` ✱ · `brand.ribbon` · `brand.legal` | марката горе, лентата над нея („Организатор: …“), правното име долу |
| `theme` | `accent`, `ink`, `paper` (`#rrggbb`); `font_display`, `font_body` (имена на шрифтове); `fonts_css` — само `https://fonts.googleapis.com/…` или `null` |
| `dates.from` ✱ · `dates.to` ✱ · `dates.label` | ГГГГ-ММ-ДД; `label` е как да се изпише („9–11 октомври 2026“) |
| `place` | `name`, `seats`, `note` |
| `publish` | `indexable` (false докато не е „go“), `base_url` (за canonical и sitemap) |
| `cta` | `label` и `form` — id на въпросника, към който води бутонът |
| `home.why` | карти `{title, text}` за „Защо така“ |
| `lab_roles` | `{id, label, text}` — колоните на лабораторията и картите „За кого“ |
| `topics` | `{n ✱, title ✱, summary, goals[], sections[], lab{роля: [задачи]}, demo{title, steps[]}}` |
| `topics[].sections` | свои раздели: `{title, intro, items: [{title, text}]}` |
| `schedule` | дни `{date, label, slots: [{from, to, title, topics: [n]}]}`; часовете ЧЧ:ММ, без застъпване |
| `forms` | `{id, slug, title, intro, fields[]}`; slug не може да е `index`, `programa`, `razpisanie`, `tema-NN` |
| `forms[].fields` | `{id, type, label, required, help, options[] / options_from, other, max, max_length, required_if[]}` |

В текстовете: `**удебелено**` и `[текст](https://…)`. Всичко друго се екранира.

# people.json

```json
{"placeholders": {"speakers": 4, "partners": 4},
 "speakers": [{"name": "…", "role": "…", "bio": "…", "photo": "img/x.jpg", "link": "https://…"}],
 "partners": []}
```

`photo` и `link` са `https://…` или относителен път. Само `name` е задължително.
