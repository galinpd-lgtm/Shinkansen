# three.js 0.186.1 (вграден)

- Източник: npm пакет `three@0.186.1` (https://registry.npmjs.org/three/-/three-0.186.1.tgz)
- sha256 на пакета: `8cd068708ea44f2c73c944b1cead2ba2f0d5c15c8fc194e5700f4e4f4a033fe7`
- Лиценз: MIT — виж `LICENSE` до този файл.
- Взети файлове: `build/three.module.js`, `build/three.core.js`, `examples/jsm/controls/OrbitControls.js`,
  `examples/jsm/loaders/GLTFLoader.js`, `examples/jsm/loaders/DRACOLoader.js`, `examples/jsm/utils/BufferGeometryUtils.js`,
  `examples/jsm/utils/SkeletonUtils.js`.
- Draco декодер (Google Draco, **Apache-2.0** — не MIT; текстът е в `examples/jsm/libs/draco/LICENSE`, взет от
  `vendor/draco.LICENSE`, защото пакетът на three.js не го носи): `examples/jsm/libs/draco/gltf/draco_wasm_wrapper.js`,
  `examples/jsm/libs/draco/gltf/draco_decoder.wasm` (вариантът за glTF, само WebAssembly), `examples/jsm/libs/draco/README.md`.
  Зарежда се само когато моделът е компресиран с Draco.
- Единствена промяна: в `examples/jsm/` импортът `from 'three'` е сменен с относителен път до `build/three.module.js`.
- Обновяване: `./vendor/update-three.sh <версия>`.
