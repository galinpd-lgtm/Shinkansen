"""Решението на филтъра (за Z8): ПРОПУСНИ · ПРЕДУПРЕДИ · КАРАНТИНА. Праговете са в config["reshenie"].

КАРАНТИНА: оценка под karantina_pod, или ai_generated с вероятност ≥ ai_karantina_ot,
           или критичен флаг: anonymous_authority и прозрачност ≤ bez_iztochnici_do (липса на източници).
ПРОПУСНИ:  оценка ≥ propusni_ot и нито един флаг.
ПРЕДУПРЕДИ: всичко останало.
"""
IMENA = {"PROPUSNI": "ПРОПУСНИ", "PREDUPREDI": "ПРЕДУПРЕДИ", "KARANTINA": "КАРАНТИНА"}


def reshi(krayna, pohvati, osi, cfg):
    r = cfg["reshenie"]
    prozr = next((o["ocenka"] for o in osi if o["kluch"] == "prozrachnost"), 10.0)
    kluchove = {p["kluch"] for p in pohvati}
    ai = max((p.get("veroyatnost", 0.0) for p in pohvati if p["kluch"] == "ai_generated"), default=0.0)

    prichini = []
    if krayna < r["karantina_pod"]:
        prichini.append("оценката %.1f е под %.1f" % (krayna, r["karantina_pod"]))
    if ai >= r["ai_karantina_ot"]:
        prichini.append("вероятно машинно генериран текст (%.2f)" % ai)
    if "anonymous_authority" in kluchove and prozr <= r["bez_iztochnici_do"]:
        prichini.append("критичен флаг: анонимен авторитет и липсват посочени източници")
    if prichini:
        kod = "KARANTINA"
    elif krayna >= r["propusni_ot"] and not pohvati:
        kod = "PROPUSNI"
        prichini.append("оценка %.1f и няма открити похвати" % krayna)
    else:
        kod = "PREDUPREDI"
        if krayna < r["propusni_ot"]:
            prichini.append("оценката %.1f е между %.1f и %.1f" % (krayna, r["karantina_pod"], r["propusni_ot"]))
        if pohvati:
            prichini.append("открити похвати: %d" % len(pohvati))
    return {"kod": kod, "ime": IMENA[kod], "prichini": prichini}
