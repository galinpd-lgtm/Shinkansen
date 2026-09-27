"""Статистика от firewall_log: решения по слой и по източник, плюс репутацията на източниците.

Източник, който не отговаря от ne_otgovarya_sled_dni дни насам, се показва като „не отговаря“.
Не се изключва сам — решението е на човека.
"""
from datetime import datetime, timedelta


def statistika(b, sega, ne_otgovarya_dni=3):
    po_sloy = b.execute("SELECT sloy, reshenie, COUNT(*) n FROM firewall_log GROUP BY sloy, reshenie "
                        "ORDER BY sloy, reshenie").fetchall()
    po_izvor = b.execute("SELECT izvor, reshenie, COUNT(*) n FROM zapisi WHERE sastoyanie='obraboten' "
                         "GROUP BY izvor, reshenie ORDER BY izvor, reshenie").fetchall()
    izvori = []
    for r in b.execute("SELECT id, ime, vid, rep_score, preizchislena, posledno_sastoyanie, ne_otgovarya_ot "
                       "FROM izvori ORDER BY id"):
        d = dict(r)
        d["ne_otgovarya"] = bool(r["ne_otgovarya_ot"]) and \
            sega - datetime.fromisoformat(r["ne_otgovarya_ot"]) >= timedelta(days=ne_otgovarya_dni)
        izvori.append(d)
    novi = b.execute("SELECT COUNT(*) FROM zapisi WHERE sastoyanie='nov'").fetchone()[0]
    return {
        "po_sloy": [dict(r) for r in po_sloy],
        "po_izvor": [dict(r) for r in po_izvor],
        "izvori": izvori,
        "nesortirani": novi,
    }


def otchet(s):
    r = ["Статистика на филтъра", "", "По слой (редове в дневника):"]
    if not s["po_sloy"]:
        r.append("  няма")
    for x in s["po_sloy"]:
        r.append("  слой %d  %-14s %5d" % (x["sloy"], x["reshenie"], x["n"]))
    r += ["", "По източник (крайно решение за записите):"]
    if not s["po_izvor"]:
        r.append("  няма")
    for x in s["po_izvor"]:
        r.append("  %-28s %-12s %5d" % (x["izvor"], x["reshenie"], x["n"]))
    r += ["", "Източници (вид · репутация · последно събиране):"]
    for x in s["izvori"]:
        r.append("  %-28s %-14s %4.1f  %s%s" % (x["id"], x["vid"] or "", x["rep_score"], x["posledno_sastoyanie"] or "—",
                                               "  ⚠ НЕ ОТГОВАРЯ от %s" % x["ne_otgovarya_ot"][:10] if x["ne_otgovarya"] else ""))
    ne = [x["id"] for x in s["izvori"] if x["ne_otgovarya"]]
    if ne:
        r += ["", "Не отговарят (не са изключени — решението е твое): %s" % ", ".join(ne)]
    r += ["", "Несортирани записи: %d" % s["nesortirani"]]
    return "\n".join(r)
