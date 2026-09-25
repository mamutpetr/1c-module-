"""Безкоштовний OCR сканів на базі Tesseract.

Приймає PDF (зокрема багатосторінкові), TIFF (зокрема багатосторінкові, CCITT G4), PNG, JPG, BMP.

Приклади:
    python3 ocr.py samples/scan_invoice.pdf
    python3 ocr.py scan.tif --prep                   # з попередньою обробкою
    python3 ocr.py scan.pdf --gt truth.txt           # + точність кожної сторінки відносно еталону
"""
import argparse
import difflib
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytesseract
from PIL import Image, ImageSequence

PDF_DPI = 300


def load_pages(path: str) -> list[Image.Image]:
    """Сторінки документа як зображення: PDF рендериться при 300 dpi, TIFF розбирається на кадри."""
    if Path(path).suffix.lower() == ".pdf":
        pages = []
        with pymupdf.open(path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=PDF_DPI, colorspace=pymupdf.csGRAY)
                pages.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
        return pages
    with Image.open(path) as img:
        return [frame.convert("L") for frame in ImageSequence.Iterator(img)]


def preprocess(img: Image.Image) -> Image.Image:
    """Сірий -> збільшення сканів з низькою роздільністю -> легке розмиття проти шуму.

    Бінаризацію робить сам Tesseract методом Sauvola (див. PREP_CONFIG): на сірих
    зашумлених сканах із нерівним освітленням він стабільніший за глобальний поріг Otsu.
    """
    a = np.asarray(img.convert("L")).astype(np.float32)
    if max(a.shape) < 2000:
        a = cv2.resize(a, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    a = cv2.GaussianBlur(a, (0, 0), 0.6)
    a = (a - 128) * 1.15 + 128
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


PREP_CONFIG = "-c thresholding_method=2"


def accuracy(text: str, truth: str) -> float:
    norm = lambda s: " ".join(s.split())
    return difflib.SequenceMatcher(None, norm(text), norm(truth), autojunk=False).ratio() * 100


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("image", help="PDF, TIFF, PNG, JPG або BMP")
    p.add_argument("--lang", default="ukr+eng")
    p.add_argument("--prep", action="store_true", help="обробка сірих/кольорових сканів: розмиття шуму та бінаризація Sauvola")
    p.add_argument("--psm", default="6", help="режим сегментації Tesseract (6 = один блок тексту)")
    p.add_argument("--gt", help="файл з еталонним текстом для оцінки точності")
    args = p.parse_args()

    pages = load_pages(args.image)
    truth = Path(args.gt).read_text(encoding="utf-8") if args.gt else None
    config = f"--oem 1 --psm {args.psm}" + (f" {PREP_CONFIG}" if args.prep else "")

    for n, img in enumerate(pages, 1):
        if len(pages) > 1:
            print(f"===== Сторінка {n} з {len(pages)} =====")
        if args.prep:
            img = preprocess(img)
        t = time.perf_counter()
        text = pytesseract.image_to_string(img, lang=args.lang, config=config)
        elapsed = time.perf_counter() - t

        print(text.strip())
        print(f"\n--- {elapsed:.2f} c", end="")
        if truth:
            print(f", точність: {accuracy(text, truth):.1f}%", end="")
        print("\n")


if __name__ == "__main__":
    main()
