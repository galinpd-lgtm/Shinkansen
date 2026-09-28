"""Отчетът на български: степен, 7-те оси средно, най-честите похвати с примери, тенденция по седмици,
методика, ограничения. Описва измереното — не присъжда."""
from .dov import IMENA_OSI, OSI_KLUCHOVE
from .tekstove import chislo, den, kratko, md, procent

VATRESHNO = "вътрешно · непубликувано"


def tekst(r, cfg, vatreshno=False):
    """r — резултатът от cli.izchisli(): kanal, ch (числата), stepen, izchisleno."""
    k, ch, s = r["kanal"], r["ch"], r["stepen"]
    oc = cfg["otchet"]
    p = ch["period"]
    red = []
    red.append("# Отчет за качеството на информационен канал\n")
    if vatreshno:
        red.append("> **%s.** Каналът не е дал съгласие за публикуване на този отчет. Само за вътрешна употреба.\n"
                   % VATRESHNO.capitalize())
    red.append("- **Канал:** %s (`%s`)%s" % (md(k["ime"]), k["id"], (" · " + k["url"]) if k.get("url") else ""))
    red.append("- **Период:** %s – %s (%d дни)" % (den(p["ot"]), den(p["do"]), p["dni"]))
    red.append("- **Оценени записа:** %d" % ch["zapisi"])
    red.append("- **Изчислено:** %s\n" % den(r["izchisleno"]))

    red.append("## Степен: %s\n" % s["kod"])
    red.append("Цвят: %s. Средна оценка на записите за периода: **%s** от 10.\n" % (s["cvyat_ime"],
                                                                                    chislo(ch["sredna"])))
    if s.get("rachno"):
        red.append("Степента е поставена **ръчно** от човек. Изчислената от числата степен е „%s“.\n"
                   % s["mashinna"]["kod"])
    if s["prichini"]:
        red.append("Защо не е по-висока:\n")
        red += ["- %s" % md(x) for x in s["prichini"]]
        red.append("")

    red.append("## Числата\n")
    red.append("| Мярка | Стойност | Праг за %s |" % cfg["stepeni"][0]["kod"])
    red.append("|---|---|---|")
    naygorna = cfg["stepeni"][0]
    red.append("| Средна оценка | %s | поне %s |" % (chislo(ch["sredna"]), chislo(naygorna["ot"])))
    red.append("| Записи с именувани източници | %s | поне %s |" % (
        procent(ch["dyal_imenuvani"]), procent(naygorna.get("min_imenuvani"))))
    red.append("| Записи с манипулативни похвати | %s | под %s |" % (
        procent(ch["dyal_pohvati"]), procent(naygorna.get("maks_pohvati"))))
    red.append("| История | %d дни (от %s) | поне %s дни |" % (
        ch["istoriya_dni"], den(ch["parvi_zapis"]) if ch["parvi_zapis"] else "—", naygorna.get("min_istoriya_dni", "—")))
    red.append("| Седмици с публикации | %d от %d | — |" % (ch["sedmici_s_publikacii"], len(ch["sedmici"])))
    red.append("| Оценени записа | %d | поне %d за каквато и да е степен |\n" % (ch["zapisi"],
                                                                              cfg["bez_stepen"]["min_zapisi"]))

    red.append("## Седемте оси (средно, 0–10)\n")
    red.append("| Ос | Средно |")
    red.append("|---|---|")
    for kl in OSI_KLUCHOVE:
        red.append("| %s | %s |" % (IMENA_OSI[kl], chislo(ch["osi"].get(kl))))
    red.append("")

    red.append("## Най-честите манипулативни похвати\n")
    if not ch["pohvati"]:
        red.append("В записите за периода не е открит нито един от 14-те похвата.\n")
    for i, e in enumerate(ch["pohvati"][:oc["nay_chesti_pohvati"]], 1):
        red.append("%d. **%s** — в %d от %d записа (%s)" % (i, e["ime"], e["zapisi"], ch["zapisi"],
                                                            procent(e["zapisi"] / ch["zapisi"])))
        for pr in e["primeri"][:oc["primeri_na_pohvat"]]:
            izv = "[%s](%s)" % (md(kratko(pr["zaglavie"], 90)) or "запис", pr["url"]) if pr["url"] \
                else md(kratko(pr["zaglavie"], 90))
            red.append("   - „%s“ — %s, %s" % (md(kratko(pr["otkas"], oc["maks_znaci_primer"])), izv, den(pr["den"])))
    if ch["pohvati"]:
        red.append("\nОткъсите са дословни цитати от текстовете на канала. Похватът описва начина на изказ, "
                   "не верността на твърдението.\n")

    red.append("## Тенденция по седмици\n")
    red.append("| Седмица | Записи | Средна оценка |")
    red.append("|---|---|---|")
    for sd in ch["sedmici"]:
        red.append("| %s – %s | %d | %s |" % (den(sd["ot"]), den(sd["do"]), sd["zapisi"], chislo(sd["sredna"])))
    red.append("")

    red.append("## Методика\n")
    red.append("Всеки текст на канала, събран от информационния филтър, получава профил на доверие по 7 оси и се "
               "проверява за 14 манипулативни похвата. Степента се смята от профилите за последните %d дни: "
               "средна оценка, дял на записите с именувани източници (ос „Прозрачност“ поне %s), дял на записите "
               "с похвати, дължина на историята и редовност на публикациите. Пълното описание и праговете са в "
               "публичната методика (`python -m iq metodika`).\n" % (cfg["prozorec_dni"],
                                                                     chislo(cfg["imenuvani_prag"])))

    red.append("## Ограничения — какво не може да се заключи\n")
    red.append("- Измерени са само %d текста, събрани от филтъра за периода — не всичко, публикувано от канала."
               % ch["zapisi"])
    red.append("- Отчетът не проверява фактите и не казва дали отделно твърдение е вярно или невярно. "
               "Описва как са написани текстовете.")
    red.append("- Отчетът не оценява хората, които работят в канала.")
    if ch["bez_model"]:
        red.append("- %d от %d записа са оценени без езиков модел (само правила): тези оценки са груби."
                   % (ch["bez_model"], ch["zapisi"]))
    uv = ", ".join("%s: %d" % (n, b) for n, b in sorted(ch["uverenost"].items()))
    if uv:
        red.append("- Увереност на оценките по записи — %s." % uv)
    red.append("- Проверени ос по ос от човек: %d от %d записа." % (ch["provereni_ot_chovek"], ch["zapisi"]))
    red.append("- Степента не е сертификат от независим орган.")
    red.append("")
    return "\n".join(red)
