# Сграда в 3D — входовете на една сграда, в браузъра

Двигател за страница, на която човек върти сградата и вижда откъде се влиза: входове, достъпен вход, каса,
паркинг, спирка, информация. Общ е за всяка сграда. Примерът е **измислена** кръгла арена — без данни и бранд
на конкретна сграда.

**Части:**
- `blender/` — от числа (`skeleton.json`) до модел (`model.glb`) в Blender; проверка на числата без Blender
- `core/` — уеб компонентът `<venue-3d>` (ES модул) и чистите му функции
- `vendor/three/` — three.js 0.186.1, вграден (MIT, `LICENSE` и `VERSION.md` до него) — без CDN
- `models/arena.example.glb` — моделът на примерната арена, изнесен с Blender скрипта
- `site/` — демонстрацията; публикува се под `/3d/` (`.github/workflows/pages.yml`)

## Как се пуска локално

```bash
cd apps/venue-3d
rm -rf _site && mkdir -p _site/core _site/vendor
cp -r site/. _site/ && cp core/*.js _site/core/ && cp -r vendor/three _site/vendor/
cp models/arena.example.glb _site/model.glb && cp blender/skeleton.example.json _site/skeleton.json
python3 -m http.server -d _site 8000                    # → http://localhost:8000
```

Без `_site/model.glb` страницата строи временен модел от `skeleton.json` и го казва с жълта лента.

Тестове — без Blender, без браузър, без зависимости:

```bash
python3 -m unittest discover -s blender/tests -v        # skeleton.json: проверка и геометрия
node --test core/tests/*.test.mjs                       # venue.json, временният модел, размерът под 5 MB
```

## Моделът: `blender/build_venue.py`

На машина с Blender 5.x:

```bash
cd apps/venue-3d
python3 blender/venue_geometry.py my-skeleton.json          # първо проверка, без Blender
blender -b --python blender/build_venue.py -- my-skeleton.json site/model.glb
```

Скриптът строи всичко само от числата в `skeleton.json` (описание: `blender/skeleton.schema.md`):
барабан (цилиндър или пресечен конус с наклон), нива, външен пръстен, пилони, покрив (купол, плосък, конус
или седло), правоъгълни крила и отвори-входове. Всеки елемент е отделен именуван възел — `level_0`,
`level_1`, `ring`, `roof`, `pylon_01`…, `wing_<id>`, `entrance_<id>` — и носи в `extras` вида си и нивото си.
Отворите се изрязват с boolean. Изнася glTF binary.

Където API-то на Blender има стойности, които се менят между версиите (формат на износа, boolean solver,
настройката на материалите), скриптът пробва списък от кандидати. Пример: в Blender 5.0 списъкът със
стойности на `export_format` се връща празен (стойностите се определят динамично), затова форматът се
пробва — `GLB`, после `GLTF_BINARY`.

Скриптът работи и с модула `bpy` от PyPI (същото API, без интерфейс на Blender):
`pip install bpy==5.0.1 && python3 blender/build_venue.py -- skeleton.json out.glb`. Така е изнесен
`models/arena.example.glb`.

Временният модел в браузъра (`core/skeleton-geometry.js`) е същата геометрия, пренесена на JS; двете се
сверяват в тестовете срещу `core/tests/fixtures/parts.summary.json`. След промяна на геометрията:
`python3 blender/tests/test_skeleton.py --write-summary`. Единствената разлика: в браузъра отворите не се
изрязват — на тяхно място има тъмен панел.

## Компонентът: `core/venue-3d.js`

```html
<script type="module" src="core/venue-3d.js"></script>
<venue-3d src="venue.json" lang="bg"></venue-3d>
```

До страницата трябват `core/` и `vendor/` една до друга (модулът внася `../vendor/three/…`).

- **Движение:** мишка (влачене — въртене, колелце — увеличение, десен бутон — преместване), пръст (един —
  въртене, два — увеличение и преместване), стрелките, когато сцената е на фокус. Камерата не слиза под земята
  и не се отдалечава извън границите от `camera`. Бутон „Начален изглед“. Стрелка на север по `north_deg`.
- **Точки:** HTML етикети, закачени за 3D позицията; скриват се, когато са зад сградата. Клик (или избор в
  списъка) → карта с описание и плавен полет на камерата към точката. Списъкът работи с клавиатура (Tab,
  стрелки, Home/End, Enter; Esc затваря картата).
- **Нива:** „Отвори сградата“ скрива покрива и нивата над избраното. Точка с `"inside": true` отваря сградата
  до своето ниво, когато се избере.
- **Разглобен изглед:** нивата се раздалечават нагоре с плавна анимация (`explode.gap` метра), покривът — най-отгоре.
  До всяко ниво има етикет с името и котата. Клик върху ниво или етикета му → останалото избледнява, камерата се
  насочва към нивото, а видими остават само точките на това ниво. „Цялата сграда“ връща всичко. Работи и с glb,
  и с временния модел — по имената на възлите (`level_*`, `roof`) и по `extras.level`.
- **Двуезично** (`lang="bg"`/`"en"`), с падане към другия език. При `prefers-reduced-motion` няма анимации —
  преходите са мигновени. Без WebGL списъкът и картите пак работят.

### `venue.json`

Координатите са в плана, както в `skeleton.json`: метри, `x` на изток, `y` на север, `z` нагоре.

| Поле | Какво е |
|---|---|
| `schema_version` | `"1"` |
| `name` | `{bg, en}` (или низ) |
| `model` | път до `.glb`, спрямо `venue.json` |
| `skeleton` | път до `skeleton.json` или самият обект — за временния модел |
| `north_deg` | накъде е истинският север спрямо оста `y` на плана (по часовника, градуси) |
| `camera` | `target` `[x,y,z]`, `distance`, `azimuth_deg` (откъде гледа камерата, по компас), `elevation_deg`, `min_distance`, `max_distance`, `max_target_radius`, `min_elevation_deg` |
| `roof_nodes` | възлите на покрива (`["roof"]`) |
| `explode.gap` | разстояние между нивата в разглобения изглед, метри (по подразбиране — по височината на нивата) |
| `levels[]` | `id`, `name` `{bg,en}`, `nodes` (възлите на нивото; по подразбиране `[id]`), `elevation` (кота; по подразбиране — от модела) |
| `hotspots[]` | `id`, `kind` (`entrance`, `accessible_entrance`, `ticket_office`, `parking`, `transit_stop`, `info`), `name` и `description` `{bg,en}`, `position` `[x,y,z]`, `level` (id на ниво), `inside` (по избор), `node` (по избор — възелът на входа) |

Негодните точки се изпускат, а грешките се пишат в конзолата — страницата не пада заради една точка.

### Визия — само през CSS custom properties

`--v3d-font`, `--v3d-fg`, `--v3d-muted`, `--v3d-bg` (фон на сцената), `--v3d-panel`, `--v3d-border`,
`--v3d-accent`, `--v3d-radius`, `--v3d-height`, `--v3d-north`; цветовете на временния модел — `--v3d-ground`,
`--v3d-building`, `--v3d-roof`, `--v3d-pylon`, `--v3d-wing`, `--v3d-entrance`, `--v3d-door`; точките —
`--v3d-pin-bg`, `--v3d-pin-fg`, `--v3d-pin-entrance`, `--v3d-pin-accessible`, `--v3d-pin-service`,
`--v3d-pin-transport`; жълтата лента — `--v3d-warn-bg|fg|border`. Частите са достъпни и през `::part(...)`:
`root`, `stage`, `toolbar`, `compass`, `pins`, `level-tags`, `status`, `card`, `list`.
Моделът от glb пази своите материали; променливите оцветяват временния модел, земята и интерфейса.

## Размер

Страница, скриптове, three.js, модел и скелет — около 2,7 MB (под 5 MB; проверява се в тестовете).
Най-голямото е three.js (2,1 MB некомпресиран; GitHub Pages го праща компресиран).
