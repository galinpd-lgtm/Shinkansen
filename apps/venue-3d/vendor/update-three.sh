#!/usr/bin/env bash
# Вгражда фиксирана версия на three.js в vendor/three/ — без CDN и без npm зависимости по време на работа.
# Пускане (иска npm и достъп до registry.npmjs.org):  ./vendor/update-three.sh 0.186.1
# Взима само нужните файлове и сменя голия импорт 'three' с относителен път,
# за да работят модулите в браузъра без import map. Друго в тях не се пипа.
set -euo pipefail
VERSION="${1:?версия, напр. 0.186.1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HERE/three"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

( cd "$TMP" && npm pack "three@$VERSION" --silent >/dev/null && tar xzf "three-$VERSION.tgz" )
PKG="$TMP/package"
rm -rf "$DEST" && mkdir -p "$DEST/build" "$DEST/examples/jsm/controls" "$DEST/examples/jsm/loaders" "$DEST/examples/jsm/utils" \
  "$DEST/examples/jsm/libs/draco/gltf"
cp "$PKG/LICENSE" "$DEST/LICENSE"
cp "$PKG/build/three.module.js" "$PKG/build/three.core.js" "$DEST/build/"
for f in controls/OrbitControls.js loaders/GLTFLoader.js loaders/DRACOLoader.js utils/BufferGeometryUtils.js utils/SkeletonUtils.js; do
  # examples/jsm/<папка>/<файл> → три нива нагоре до vendor/three/
  sed "s#from 'three';#from '../../../build/three.module.js';#" "$PKG/examples/jsm/$f" > "$DEST/examples/jsm/$f"
done
# Draco декодер (Google, Apache-2.0): само WebAssembly вариантът за glTF — обвивка и .wasm, без JS резервата (0,5 MB)
cp "$PKG/examples/jsm/libs/draco/README.md" "$DEST/examples/jsm/libs/draco/README.md"
cp "$PKG/examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js" "$PKG/examples/jsm/libs/draco/gltf/draco_decoder.wasm" \
  "$DEST/examples/jsm/libs/draco/gltf/"
cp "$HERE/draco.LICENSE" "$DEST/examples/jsm/libs/draco/LICENSE"   # пакетът на three.js не носи текста на лиценза
if grep -rn "from 'three'" "$DEST/examples"; then echo "остана гол импорт 'three'" >&2; exit 1; fi

SHA="$(sha256sum "$TMP/three-$VERSION.tgz" | cut -d' ' -f1)"
cat > "$DEST/VERSION.md" <<MD
# three.js $VERSION (вграден)

- Източник: npm пакет \`three@$VERSION\` (https://registry.npmjs.org/three/-/three-$VERSION.tgz)
- sha256 на пакета: \`$SHA\`
- Лиценз: MIT — виж \`LICENSE\` до този файл.
- Взети файлове: \`build/three.module.js\`, \`build/three.core.js\`, \`examples/jsm/controls/OrbitControls.js\`,
  \`examples/jsm/loaders/GLTFLoader.js\`, \`examples/jsm/loaders/DRACOLoader.js\`, \`examples/jsm/utils/BufferGeometryUtils.js\`,
  \`examples/jsm/utils/SkeletonUtils.js\`.
- Draco декодер (Google Draco, **Apache-2.0** — не MIT; текстът е в \`examples/jsm/libs/draco/LICENSE\`, взет от
  \`vendor/draco.LICENSE\`, защото пакетът на three.js не го носи): \`examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js\`,
  \`examples/jsm/libs/draco/gltf/draco_decoder.wasm\` (вариантът за glTF, само WebAssembly), \`examples/jsm/libs/draco/README.md\`.
  Зарежда се само когато моделът е компресиран с Draco.
- Единствена промяна: в \`examples/jsm/\` импортът \`from 'three'\` е сменен с относителен път до \`build/three.module.js\`.
- Обновяване: \`./vendor/update-three.sh <версия>\`.
MD
echo "three.js $VERSION → $DEST"
du -sh "$DEST"
