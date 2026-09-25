"""Безкоштовний OCR на базі Tesseract.

Приклади:
    python3 ocr.py samples/invoice_clean.png
    python3 ocr.py scan.jpg --prep                  # з попередньою обробкою
    python3 ocr.py scan.jpg --prep --gt truth.txt   # + точність відносно еталону
"""
import argparse
import difflib
import time

import cv2
import numpy as np
import pytesseract
from PIL import Image


def preprocess(img: Image.Image) -> Image.Image:
    """Сірий -> збільшення -> вирівнювання нахилу -> бінаризація."""
    a = np.asarray(img.convert("L"))
    if a.shape[1] < 1500:
        a = cv2.resize(a, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    a = cv2.fastNlMeansDenoising(a, h=15)

    # кут нахилу: той, при якому рядки тексту дають найрізкіший горизонтальний профіль
    inv = cv2.threshold(a, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    small = cv2.resize(inv, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    h, w = small.shape

    def score(angle: float) -> float:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        return float(np.var(cv2.warpAffine(small, m, (w, h)).sum(axis=1)))

    angle = max(np.arange(-5, 5.01, 0.25), key=score)
    if abs(angle) > 0.2:
        h, w = a.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        a = cv2.warpAffine(a, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)

    a = cv2.adaptiveThreshold(a, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
    return Image.fromarray(a)


def accuracy(text: str, truth: str) -> float:
    norm = lambda s: " ".join(s.split())
    return difflib.SequenceMatcher(None, norm(text), norm(truth)).ratio() * 100


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--lang", default="ukr+eng")
    p.add_argument("--prep", action="store_true", help="попередня обробка зображення")
    p.add_argument("--psm", default="6", help="режим сегментації Tesseract (6 = один блок тексту)")
    p.add_argument("--gt", help="файл з еталонним текстом для оцінки точності")
    args = p.parse_args()

    img = Image.open(args.image)
    if args.prep:
        img = preprocess(img)

    t = time.perf_counter()
    text = pytesseract.image_to_string(img, lang=args.lang, config=f"--oem 1 --psm {args.psm}")
    elapsed = time.perf_counter() - t

    print(text.strip())
    print(f"\n--- {elapsed:.2f} c", end="")
    if args.gt:
        with open(args.gt, encoding="utf-8") as f:
            print(f", точність: {accuracy(text, f.read()):.1f}%", end="")
    print()


if __name__ == "__main__":
    main()
