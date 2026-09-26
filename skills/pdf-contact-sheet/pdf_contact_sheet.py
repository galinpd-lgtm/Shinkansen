#!/usr/bin/env python3
"""pdf-contact-sheet — всички страници на PDF в една картинка-мрежа с номера.

    pdf_contact_sheet.py ВХОД.pdf ИЗХОД.png [--cols N] [--thumb 240] [--max-pages 400] [--force]

За бърз триаж на сканове: празни, обърнати, дублирани страници се виждат с един поглед.
Незадължителни зависимости: pymupdf (рендер) и Pillow (мрежата). Без тях — ясна грешка, код 3.
Входът само се чете; изходът е нов файл (без --force не презаписва съществуващ).
"""
import argparse
import math
import os
import sys

EXIT_MISSING = 3
BG = (8, 13, 22)          # тъмен фон
LABEL_BG = (16, 24, 37)
LABEL_FG = (230, 236, 243)
PAD = 10
LABEL_H = 22


def write_summary(text):
    path = os.environ.get("SHINKANSEN_SUMMARY_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def load_deps():
    """→ (pymupdf, PIL.Image, PIL.ImageDraw, PIL.ImageFont) или SystemExit с ясно съобщение."""
    missing = []
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf       # по-стари версии
        except ImportError:
            pymupdf = None
            missing.append("pymupdf")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        Image = ImageDraw = ImageFont = None
        missing.append("pillow")
    if missing:
        print("липсва: %s — инсталирай с: python3 -m pip install %s"
              % (", ".join(missing), " ".join(missing)), file=sys.stderr)
        write_summary("липсва зависимост")
        raise SystemExit(EXIT_MISSING)
    return pymupdf, Image, ImageDraw, ImageFont


def grid_layout(n, cols=None, aspect=16 / 9):
    """Колко колони и редове за n страници. Без cols — мрежа, близка до зададеното съотношение."""
    if n <= 0:
        return 0, 0
    if not cols:
        # страница A4 е ~0.71 широка/висока: мрежата е cols широка и n/cols·1.41 висока,
        # отношението е aspect, когато cols² = n·aspect/0.71
        cols = max(1, round(math.sqrt(n * aspect / 0.71)))
    cols = min(cols, n)
    return cols, math.ceil(n / cols)


def cell_origin(i, cols, cell_w, cell_h):
    r, c = divmod(i, cols)
    return PAD + c * (cell_w + PAD), PAD + r * (cell_h + PAD)


def build(pdf_path, out_path, cols=None, thumb=240, max_pages=400):
    pymupdf, Image, ImageDraw, ImageFont = load_deps()
    doc = pymupdf.open(pdf_path)
    total = doc.page_count
    n = min(total, max_pages)
    if n == 0:
        raise ValueError("PDF файлът няма страници")
    cols, rows = grid_layout(n, cols)
    # височината на клетката — по най-високата страница при ширина thumb
    heights = []
    for i in range(n):
        r = doc[i].rect
        heights.append(int(thumb * r.height / r.width) if r.width else thumb)
    cell_w, cell_h = thumb, max(heights) + LABEL_H
    sheet = Image.new("RGB", (PAD + cols * (cell_w + PAD), PAD + rows * (cell_h + PAD)), BG)
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=14)     # Pillow ≥ 10.1
    except TypeError:
        font = ImageFont.load_default()
    for i in range(n):
        page = doc[i]
        zoom = thumb / page.rect.width if page.rect.width else 1
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        x, y = cell_origin(i, cols, cell_w, cell_h)
        sheet.paste(img, (x, y + LABEL_H))
        draw.rectangle([x, y, x + cell_w - 1, y + LABEL_H - 1], fill=LABEL_BG)
        draw.text((x + 6, y + 3), "%d / %d" % (i + 1, total), fill=LABEL_FG, font=font)
    doc.close()
    sheet.save(out_path)
    return {"pages": total, "shown": n, "cols": cols, "rows": rows, "size": sheet.size}


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDF → една картинка с всички страници.")
    ap.add_argument("pdf")
    ap.add_argument("out", help="изходна картинка (.png или .jpg)")
    ap.add_argument("--cols", type=int, help="колони (по подразбиране — автоматично)")
    ap.add_argument("--thumb", type=int, default=240, help="ширина на страница в пиксели")
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--force", action="store_true", help="презапиши съществуващ изход")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.pdf):
        ap.error("няма такъв PDF файл")
    if os.path.exists(a.out) and not a.force:
        ap.error("изходът съществува — добави --force, за да го презапишеш")
    if os.path.realpath(a.out) == os.path.realpath(a.pdf):
        ap.error("изходът не може да е самият PDF")
    if not (40 <= a.thumb <= 2000) or (a.cols is not None and a.cols < 1) or a.max_pages < 1:
        ap.error("неразумни размери")
    info = build(a.pdf, a.out, a.cols, a.thumb, a.max_pages)
    more = "" if info["shown"] == info["pages"] else " (показани първите %d)" % info["shown"]
    print("%s: %d страници%s → %s (%dx%d, %d×%d)" % (
        os.path.basename(a.pdf), info["pages"], more, a.out, info["size"][0], info["size"][1],
        info["cols"], info["rows"]))
    write_summary("%d страници → мрежа %d×%d" % (info["pages"], info["cols"], info["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
