---
name: share-single-file
description: Сглобява HTML страница с локалните ѝ JS/CSS/картинки/данни в ЕДИН .html файл, който се отваря с двоен клик, без сървър — за споделяне по поща, чат или флашка. Използвай при „направи го на един файл“, „прати страницата без сървър“, „single file HTML“, „вгради всичко в страницата“, демо за клиент. Иска esbuild.
---

# share-single-file — цялата страница в един файл

## Какво иска
- `index.html` — страницата; вграждат се само файлове от нейната папка (и подпапките)
- `изход.html` — новият файл; без `--force` съществуващ не се презаписва
- `--data ФАЙЛ` — по желание, може няколко: файл с данни, който не се намира сам по име
- esbuild — от `SHINKANSEN_ESBUILD`, `PATH` или `node_modules/.bin` нагоре от страницата. Без мрежа, без `npx`.

## Какво връща
Един `.html` файл и ред на екрана: размер и колко скрипта, стила, картинки и данни са вградени.

- `<script src>` → esbuild `--bundle` (модулите с импортите им) → вграден `<script>`
- `<link rel="stylesheet">` → esbuild за CSS (`@import`, `url()` като `data:`) → `<style>`
- `<img src>`, `<link rel="icon">` → `data:` URI
- данни (`.json .csv .glb .gltf .wasm …`), чиито имена се срещат в HTML, в JS или в самите данни
  (напр. `venue.json` → `model.glb`), се вграждат и се връщат от `fetch()` от паметта. `XMLHttpRequest` не се
  прихваща.

Над 15 MB — предупреждение. Код на изход: 0 — готово · 1 — esbuild падна · 2 — грешни аргументи · 3 — липсва esbuild.

## Ниво
чернови — входът само се чете; пише се един нов файл.

## Къде тече
Локално, без мрежа. Python 3 + esbuild (`npm i -g esbuild` или `npm i esbuild` в проекта).

## Пример
```bash
bin/shinkansen run share-single-file _site/index.html /tmp/demo.html
# index.html → /tmp/demo.html · 1092.8 KB · скриптове 1, стилове 0, картинки 0, данни 3
#   данни: model.glb
#   данни: skeleton.json
#   данни: venue.json
```
