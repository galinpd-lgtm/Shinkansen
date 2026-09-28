"""otchet: преди/след — брой, размер, очакван MD (от картата) и реален MD (след preobrazuvay --go)."""
from .karta import _ochakvan, klasove
from .prisadi import IMENA, chovesko


def _procent(a, b):
    return ("%.2f%%" % (100.0 * a / b)) if b else "—"


def md(k):
    fl = k["faylove"]
    ist = [z for z in fl if z["prisada"] != "kontejner"]
    razmer = sum(z.get("razmer") or 0 for z in fl if not z.get("roditel"))
    ochakvan = sum(z.get("ochakvan_md_bytes") or 0 for z in ist)
    neizv = sum(1 for z in ist if z.get("ochakvan_md_bytes") is None and z["prisada"] not in ("dublikat",))
    pr = [z for z in fl if z.get("preobrazuvan")]
    pr_razmer = sum(z["razmer"] for z in pr)
    pr_ochakvan = sum(z.get("ochakvan_md_bytes") or 0 for z in pr)
    pr_md = sum(z["preobrazuvan"]["md_bytes"] for z in pr)
    chunks = sum(z["preobrazuvan"].get("chunks", 0) for z in pr)
    resheni_da = sum(1 for z in fl if (z.get("reshenie") or {}).get("da"))
    out = ["# Сито — отчет", "",
           "Папка: `%s` · сканирано: %s" % (k["koren"], k["skanirano"]), "",
           "## Преди", "",
           "- Файлове: **%d** (от тях %d вътре в архиви и писма; пропуснати системни: %d, връзки: %d)" % (
               len(fl), sum(1 for z in fl if z.get("roditel")), k["propusnati"].get("sistemni", 0),
               k["propusnati"].get("vrazki", 0)),
           "- Размер на папката: **%s**" % chovesko(razmer),
           "- Очакван MD за всичко с текст: **%s**%s (%s от размера)" % (
               chovesko(ochakvan), (" + %d неизвестни (OCR/препис/неясни)" % neizv) if neizv else "",
               _procent(ochakvan, razmer)),
           "", "| Присъда · вид | Брой | Размер | Очакван MD |", "|---|---:|---:|---:|"]
    for c in klasove(k):
        out.append("| %s · %s | %d | %s | %s |" % (IMENA.get(c["prisada"], c["prisada"]), c["klas"].split(":")[1],
                                                   c["broy"], chovesko(c["razmer"]), _ochakvan(c)))
    out += ["", "## След", ""]
    if not pr:
        out.append("- Нищо не е преобразувано (решени „да“: %d). Следва: `reshi` и `preobrazuvay --go`." % resheni_da)
    else:
        out += ["- Решени „да“: %d · преобразувани: **%d**" % (resheni_da, len(pr)),
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
