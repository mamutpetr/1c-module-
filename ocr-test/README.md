# Тест безкоштовного OCR сканів (Tesseract)

Перевірка, чи вистачає безкоштовного Tesseract 5 для розпізнавання сканів рахунків і накладних перед імпортом у 1С.
Приймає те, що віддають сканери та МФУ: PDF і TIFF на кілька сторінок (зокрема ч/б CCITT G4), а також PNG, JPG, BMP.

## Python (сервер / пакетна обробка)

```bash
sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus
pip install pillow pytesseract opencv-python-headless numpy pymupdf

python3 make_samples.py                    # тестові скани: samples/scan_invoice.pdf і samples/scan_invoice_g4.tif
python3 ocr.py samples/scan_invoice.pdf --prep --gt samples/invoice_ground_truth.txt
python3 ocr.py мій_скан.tif --prep
```

`--prep` прибирає шум і бінаризує методом Sauvola. Для сірих і кольорових сканів він потрібен обов'язково.

Точність (схожість з еталонним текстом), сторінка 1 / сторінка 2:

| Файл | Без обробки | `--prep` |
|---|---|---|
| `scan_invoice.pdf`: офісний скан 300 dpi / поганий скан 150 dpi, сірий JPEG | 98% / 2% | 99% / 96% |
| `scan_invoice_g4.tif`: те саме, ч/б TIFF G4 | 97% / 94% | 97% / 91% |

## Браузер (`web/`)

Той самий Tesseract у WebAssembly, файл не залишає комп'ютер. PDF розгортається через pdf.js при 300 dpi, TIFF через UTIF.js.
Сторінка показує сумнівні слова і знаходить IBAN, ЄДРПОУ та РНОКПП (з перевіркою контрольної суми), дату, суми без ПДВ, ПДВ і до сплати окремо для кожної сторінки.

```bash
web/build.sh                               # завантажує рушій, pdf.js, UTIF.js і мовні моделі в web/dist
python3 -m http.server -d web/dist 8000    # http://localhost:8000/ocr.html
```
