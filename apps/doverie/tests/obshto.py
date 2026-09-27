"""Общо за тестовете: пътища, конфигурация и фалшив модел. Нула мрежа."""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from doverie.config import zaredi  # noqa: E402

CFG = zaredi(os.path.join(APP, "config.example.json"))


def cfg():
    c = copy.deepcopy(CFG)
    c["pamet"] = None
    return c


def primer(n):
    with open(os.path.join(HERE, "primer_%d.txt" % n), encoding="utf-8") as f:
        return f.read()


class FalshivModel:
    """Същият интерфейс като doverie.model.Model: chat(rolya, sistema, potrebitel) → dict.

    pohvati — списък, който се връща на промпта за похватите; osi — {ключ: (оценка, защо)};
    sintez — dict за синтеза. Всяко викане се записва в self.vikaniya.
    """

    def __init__(self, pohvati=None, osi=None, sintez=None, surovo=None, vaprosi=None, tvardenia=None):
        self.pohvati = pohvati or []
        self.osi = osi or {}
        self.sintez = sintez
        self.surovo = surovo or {}
        self.vaprosi = vaprosi or {}        # {ключ: "да"|"частично"|"не"}; липсващите са „да“
        self.tvardenia = tvardenia          # (всички, с източник) за проверимостта или None
        self.vikaniya = []

    def chat(self, rolya, sistema, potrebitel):
        self.vikaniya.append((rolya, sistema, potrebitel))
        from doverie.model import izvadi_json
        from doverie.ocenka import PROMPT_OS
        if potrebitel.startswith("Отговори за всеки от тези въпроси"):
            if "palnota" in self.surovo:
                return izvadi_json(self.surovo["palnota"])
            from obshto import CFG as _c
            return {"otgovori": {v["kluch"]: self.vaprosi.get(v["kluch"], "да") for v in _c["palnota_vaprosi"]},
                    "zashto": "Фалшивият модел: отговорите на въпросите."}
        for k, p in PROMPT_OS.items():
            if potrebitel.startswith(p):
                if k in self.surovo:
                    return izvadi_json(self.surovo[k])
                oc, za = self.osi.get(k, (6.0, "Фалшивият модел дава средна оценка."))
                d = {"ocenka": oc, "zashto": za}
                if k == "proverimost" and self.tvardenia:
                    d["tvardenia"], d["s_iztochnik"] = self.tvardenia
                return d
        if potrebitel.startswith("Кои от тези манипулативни похвати"):
            return {"pohvati": self.pohvati}
        if rolya == "pisach":
            return self.sintez or {"za_chitatelya": "Текстът е прегледан.", "silni": ["Има дати."],
                                   "slabi": ["Един източник е анонимен."], "preporaka": "Прочетете внимателно."}
        raise AssertionError("неочакван промпт")
