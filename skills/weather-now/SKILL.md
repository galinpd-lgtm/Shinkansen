---
name: weather-now
description: „Вали ли сега“ за точка по координати — текущото време от няколко безплатни източника (Open-Meteo, MET Norway) плюс METAR от най-близкото летище по ICAO код, с общ отговор дали вали. Използвай при „вали ли“, „какво е времето в момента“, „има ли дъжд сега“, METAR, проверка преди събитие на открито. Не е прогноза за следващите дни.
metadata:
  description_en: “Is it raining right now?” for a point by coordinates — current weather from several free sources plus the METAR of the nearest airport by ICAO code, with one combined answer. Not a multi-day forecast.
---

# weather-now — вали ли сега

## Какво иска
- `--lat`, `--lon` — координати на мястото (градуси)
- `--icao` — по желание: ICAO кодът на най-близкото летище (4 знака, напр. `XXXX`)
- `--json` — по желание: изход като JSON вместо текст

## Какво връща
Кратък текст: общ отговор („вали“, „не вали“, „може би вали: …“) и по един ред на източник
(вали/сухо, °C, mm, вятър; за METAR — и суровият доклад). С `--json`:
`{"verdict": {"raining": true|false|null, "agree", "yes", "of", "text"}, "sources": [...]}`.
`raining` е по мнозинство от успешните източници; при равенство е `null`.
Паднал източник се вижда като `{"source", "error"}` — не се мълчи.

Код на изход: 0 — поне един източник отговори; 1 — всички паднаха; 2 — грешни аргументи.

## Ниво
чете — само GET заявки към публични услуги без ключове.

## Къде тече
Всяка машина с Python 3 и изход към интернет (api.open-meteo.com, api.met.no, aviationweather.gov).
Без зависимости.

## Пример
```bash
bin/shinkansen run weather-now --lat 43.2 --lon 27.9 --icao XXXX
# Вали ли сега: не вали
#   open-meteo сухо · 21.4 °C · 0.0 mm · вятър 12 km/h
#   met-no     сухо · 21.0 °C · 0.0 mm · вятър 10 km/h
#   metar      сухо · 21.0 °C · вятър 9 km/h
#              XXXX 261030Z 09005KT CAVOK 21/12 Q1016
```
