"""Порівняння локальних OCR-рушіїв на тестових сканах.

    python3 bench.py                                    # усі доступні рушії на samples/
    python3 bench.py --engines tesseract easyocr
    python3 bench.py --tessdata-best /шлях/до/tessdata_best  # додати Tesseract з моделями best

Для кожної сторінки друкує точність тексту (схожість з еталоном), скільки ключових реквізитів
прочитано без жодної помилки (саме це потрібно для імпорту в 1С) і час.
"""
import argparse
import time
from pathlib import Path

import numpy as np

from ocr import PREP_CONFIG, accuracy, load_pages, preprocess

HERE = Path(__file__).parent
FILES = [HERE / "samples/scan_invoice.pdf", HERE / "samples/scan_invoice_g4.tif"]
# номер рахунку, дата, IBAN, ЄДРПОУ, сума без ПДВ, ПДВ, до сплати
FIELDS = ["1247", "15вересня2026", "UA213223130000026007233566001", "38291040", "4051,00", "810,20", "4861,20"]


def fields_ok(text: str) -> int:
    flat = "".join(text.split())
    return sum(f in flat for f in FIELDS)


def tesseract_engine(tessdata: str | None = None):
    import pytesseract

    extra = f' --tessdata-dir "{tessdata}"' if tessdata else ""

    def run(img):
        cfg = f"--oem 1 --psm 6 {PREP_CONFIG}{extra}"
        return pytesseract.image_to_string(preprocess(img), lang="ukr+eng", config=cfg)

    return run


def easyocr_engine():
    import easyocr

    reader = easyocr.Reader(["uk", "en"], gpu=False, verbose=False)

    def run(img):
        a = np.asarray(img.convert("L"))
        boxes = reader.readtext(a, paragraph=False)
        return join_lines([(min(p[1] for p in b), max(p[1] for p in b), min(p[0] for p in b), t) for b, t, _ in boxes])

    return run


def join_lines(items):
    """Слова з рамками (верх, низ, лівий край, текст) -> рядки у порядку читання.

    Слово приєднується до рядка, якщо його середина по вертикалі потрапляє в найближче по
    горизонталі слово цього рядка: так рядок «тягнеться» вздовж перекосу скану.
    """
    lines = []
    for top, bottom, left, text in sorted(items, key=lambda i: i[2]):
        mid = (top + bottom) / 2
        for line in lines:
            _, t, b, _ = line[-1]
            if t <= mid <= b:
                line.append((left, top, bottom, text))
                break
        else:
            lines.append([(left, top, bottom, text)])
    lines.sort(key=lambda line: line[0][1])
    return "\n".join(" ".join(w[3] for w in line) for line in lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engines", nargs="+", default=["tesseract", "easyocr"])
    p.add_argument("--tessdata-best", help="тека з моделями tessdata_best (ukr, eng)")
    args = p.parse_args()

    truth = (HERE / "samples/invoice_ground_truth.txt").read_text(encoding="utf-8")
    pages = [(f"{f.name} с.{n}", img) for f in FILES for n, img in enumerate(load_pages(str(f)), 1)]

    engines = {}
    if "tesseract" in args.engines:
        engines["Tesseract (системні моделі)"] = tesseract_engine
        if args.tessdata_best:
            engines["Tesseract (tessdata_best)"] = lambda: tesseract_engine(args.tessdata_best)
    if "easyocr" in args.engines:
        engines["EasyOCR (CPU)"] = easyocr_engine

    for name, factory in engines.items():
        try:
            t = time.perf_counter()
            run = factory()
            load = time.perf_counter() - t
        except ImportError as e:
            print(f"{name}: не встановлено ({e.name})")
            continue
        print(f"\n{name}  (завантаження {load:.1f} с)")
        for label, img in pages:
            t = time.perf_counter()
            text = run(img)
            secs = time.perf_counter() - t
            print(f"  {label:24} текст {accuracy(text, truth):5.1f}%   реквізити {fields_ok(text)}/{len(FIELDS)}   {secs:5.1f} с")


if __name__ == "__main__":
    main()
