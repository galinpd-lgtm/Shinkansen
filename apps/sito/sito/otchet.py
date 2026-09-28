"""otchet: преди/след — брой, размер, очакван MD (от картата), реален MD (след preobrazuvay --go) и прегледите:
видени / решени / обработени / спрени като невидени."""
from .karta import _ochakvan, klasove, rabotni, uvedomitelni
from .prisadi import IMENA, chovesko


def _procent(a, b):
    return ("%.2f%%" % (100.0 * a / b)) if b else "—"


def broeve(k):
    fl = rabotni(k)
    za_deystvie = [z for z in fl if z["prisada"] not in ("dublikat", "neyasno")]
    videni = [z for z in za_deystvie if (z.get("vidyan") or {}).get("sha256") == z["sha256"]]
    da = [z for z in za_deystvie if (z.get("reshenie") or {}).get("da")]
    obraboteni = [z for z in fl if z.get("preobrazuvan")]
    spreni = [z for z in da if z not in videni]  # „да“, но без валиден преглед: --go ги спира
    return {"za_deystvie": len(za_deystvie), "videni": len(videni), "resheni": sum(1 for z in za_deystvie
                                                                                  if z.get("reshenie")),
            "da": len(da), "obraboteni": len(obraboteni), "spreni_nevideni": len(spreni),
            "spreni_ocr": sum(1 for z in spreni if z.get("spryan")), "_spreni": spreni}


def md(k):
    fl = k["faylove"]
    rb, uv = rabotni(k), uvedomitelni(k)
    razmer = sum(z.get("razmer") or 0 for z in fl)
    ochakvan = sum(z.get("ochakvan_md_bytes") or 0 for z in rb)
    neizv = sum(1 for z in rb if z.get("ochakvan_md_bytes") is None and z["prisada"] != "dublikat")
    pr = [z for z in rb if z.get("preobrazuvan")]
    pr_razmer = sum(z["razmer"] for z in pr)
    pr_ochakvan = sum(z.get("ochakvan_md_bytes") or 0 for z in pr)
    pr_md = sum(z["preobrazuvan"]["md_bytes"] for z in pr)
    chunks = sum(z["preobrazuvan"].get("chunks", 0) for z in pr)
    b = broeve(k)
    p = k.get("propusnati", {})
    out = ["# Сито — отчет", "",
           "Папка: `%s` · сканирано: %s" % (k["koren"], k["skanirano"]), "",
           "## Преди", "",
           "- Файлове: **%d** — работи Сито: %d, не се работи от Сито: %d" % (len(fl), len(rb), len(uv)),
           "- Пропуснати: системни %d, връзки %d, заради дълбочината (над %s папки) %d" % (
               p.get("sistemni", 0), p.get("vrazki", 0), k.get("maks_dalbochina", "?"), p.get("dalbochina", 0)),
           "- Размер на папката: **%s** (от него в обхвата: %s)" % (chovesko(razmer),
                                                                   chovesko(sum(z["razmer"] for z in rb))),
           "- Очакван MD за всичко с текст: **%s**%s (%s от размера в обхвата)" % (
               chovesko(ochakvan), (" + %d неизвестни (OCR/неясни)" % neizv) if neizv else "",
               _procent(ochakvan, sum(z["razmer"] for z in rb))),
           "", "| Присъда · вид | Брой | Размер | Очакван MD |", "|---|---:|---:|---:|"]
    for c in klasove(k):
        out.append("| %s · %s | %d | %s | %s |" % (IMENA.get(c["prisada"], c["prisada"]), c["klas"].split(":")[1],
                                                   c["broy"], chovesko(c["razmer"]), _ochakvan(c)))
    out += ["", "### Не се работи от Сито", ""]
    if uv:
        out += ["| Присъда · вид | Брой | Размер |", "|---|---:|---:|"]
        for c in klasove(k, uv):
            out.append("| %s · %s | %d | %s |" % (IMENA[c["prisada"]], c["klas"].split(":", 1)[1], c["broy"],
                                                  chovesko(c["razmer"])))
    else:
        out.append("Няма.")
    out += ["", "## Преглед и решения", "",
            "| Видени | Решени | от тях „да“ | Обработени | Спрени като невидени |", "|---:|---:|---:|---:|---:|",
            "| %d от %d | %d | %d | %d | %d%s |" % (b["videni"], b["za_deystvie"], b["resheni"], b["da"],
                                                 b["obraboteni"], b["spreni_nevideni"],
                                                 (" (%d след OCR)" % b["spreni_ocr"]) if b["spreni_ocr"] else "")]
    if b["_spreni"]:
        out += ["", "Чакат преглед (`vidyah`):", ""]
        for z in b["_spreni"]:
            out.append("- `%s` %s%s" % (z["id"], z["put"], (" — " + z["spryan"]["prichina"]) if z.get("spryan")
                                        else ""))
    pp = [z for z in fl if z["vid"] == "pptx"]
    if pp:
        izbrani = [z for z in pp if (z.get("kandidat_pdf") or {}).get("sha256") == z["sha256"]]
        out += ["", "PPTX: %d (%s) · избрани от човек за PDF (Canva): %d (%s)" % (
            len(pp), chovesko(sum(z["razmer"] for z in pp)), len(izbrani),
            chovesko(sum(z["razmer"] for z in izbrani)))]
    out += ["", "## След", ""]
    if not pr:
        out.append("- Нищо не е преобразувано. Следва: `vidyah`, `reshi` и `preobrazuvay --go`.")
    else:
        out += ["- Преобразувани: **%d**" % len(pr),
                "- Оригинали: **%s** → реален MD: **%s** (%s от размера) · очакван беше %s" % (
                    chovesko(pr_razmer), chovesko(pr_md), _procent(pr_md, pr_razmer), chovesko(pr_ochakvan)),
                "- Парчета за базата (chunks.jsonl): **%d**" % chunks,
                "", "| Файл | Присъда | Оригинал | Очакван MD | Реален MD | Дял |", "|---|---|---:|---:|---:|---:|"]
        for z in pr:
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                z["put"].replace("|", "\\|"), IMENA.get(z["prisada"]), chovesko(z["razmer"]),
                chovesko(z.get("ochakvan_md_bytes")), chovesko(z["preobrazuvan"]["md_bytes"]),
                _procent(z["preobrazuvan"]["md_bytes"], z["razmer"])))
    return "\n".join(out) + "\n"
