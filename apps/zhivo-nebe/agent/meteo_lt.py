#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Метеосигнал за събития на открито (Летен театър, Варна).
Данните: Open-Meteo (безплатно, без ключ). Текстът: локален модел на GX10.
Канон: ЖЕГАТА е проблемът, не дъждът (35,2% негодни следобеди срещу 7,4 дъждовни вечери/год)."""
import json, os, subprocess, urllib.request, datetime

IZHOD = os.environ.get("ZHIVO_NEBE_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
LAT, LON = 43.2141, 27.9147  # Варна
URL = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
       "&hourly=temperature_2m,precipitation_probability,wind_speed_10m"
       "&timezone=Europe/Sofia&forecast_days=4")

# Прагове по канона
ZHEGA = 30.0        # °C във вечерния слот
DAZHD = 50          # % вероятност
VYATAR = 40.0       # km/h


def analiz():
    with urllib.request.urlopen(URL, timeout=25) as r:
        d = json.load(r)
    h = d["hourly"]
    po_dni = {}
    for i, t in enumerate(h["time"]):
        den, chas = t.split("T")
        ch = int(chas[:2])
        if not (18 <= ch <= 22):   # вечерният слот на Летния театър
            continue
        po_dni.setdefault(den, []).append(
            (ch, h["temperature_2m"][i], h["precipitation_probability"][i],
             h["wind_speed_10m"][i]))
    redove, riskove = [], []
    for den in sorted(po_dni):
        s = po_dni[den]
        tmax = max(x[1] for x in s)
        pmax = max(x[2] for x in s)
        vmax = max(x[3] for x in s)
        flag = []
        if tmax >= ZHEGA: flag.append(f"ЖЕГА {tmax:.0f}°C")
        if pmax >= DAZHD: flag.append(f"дъжд {pmax}%")
        if vmax >= VYATAR: flag.append(f"вятър {vmax:.0f} км/ч")
        redove.append(f"{den} 18-22ч: {tmax:.0f}°C · вал. {pmax}% · вятър {vmax:.0f} км/ч"
                      + (f"  ⚠️ {', '.join(flag)}" if flag else "  ✅"))
        if flag:
            riskove.append(f"{den}: {', '.join(flag)}")
    return redove, riskove


def frazirai(redove, riskove):
    """Локалният модел оформя човешкия текст — нула токени към облака."""
    if not riskove:
        return "Няма метеорискове за вечерните слотове през следващите дни."
    p = ("Ти си дежурен по събитията на открито в Летния театър, Варна. "
         "На български, максимум 3 изречения, делово. Данни за вечерния слот 18-22ч:\n"
         + "\n".join(redove) + "\nРискове: " + "; ".join(riskove) +
         "\nКажи кой ден е проблемен и какво да се предвиди (сенки, вода, час на започване). Без увод.")
    try:
        r = subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "ask_local.sh"), "qwen3:8b", p],
                           capture_output=True, text=True, timeout=180)
        return r.stdout.strip() or "; ".join(riskove)
    except Exception:
        return "; ".join(riskove)


def main():
    redove, riskove = analiz()
    dnes = datetime.date.today().isoformat()
    os.makedirs(IZHOD, exist_ok=True)
    f = os.path.join(IZHOD, "METEO_Signal_Leten_Teatar.md")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(f"# Метеосигнал — събития на открито (Летен театър)\n\n")
        fh.write(f"*Обновено: {dnes} · източник: Open-Meteo · вечерен слот 18–22 ч.*\n\n")
        fh.write("## Прогноза\n\n" + "\n".join(f"- {r}" for r in redove) + "\n\n")
        fh.write("## Оценка\n\n" + frazirai(redove, riskove) + "\n\n")
        fh.write(f"---\n*Прагове: жега ≥{ZHEGA:.0f}°C · дъжд ≥{DAZHD}% · вятър ≥{VYATAR:.0f} км/ч. "
                 "Изготвено локално на GX10, без разход на облачен ресурс.*\n")
    print(f"OK -> {f} | риск дни: {len(riskove)}")


if __name__ == "__main__":
    main()
