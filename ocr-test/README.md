# Тест безкоштовного OCR (Tesseract)

Перевірка, чи вистачає безкоштовного Tesseract 5 для розпізнавання рахунків/накладних перед імпортом у 1С.

## Python (сервер / пакетна обробка)

```bash
sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus
pip install pillow pytesseract opencv-python-headless numpy

python3 make_samples.py                     # тестові рахунки: чистий і «поганий скан»
python3 ocr.py samples/invoice_clean.png --gt samples/invoice_ground_truth.txt
python3 ocr.py мій_скан.jpg --prep          # --prep: збільшення, шумозаглушення, вирівнювання нахилу
```

| Зображення | Без обробки | `--prep` |
|---|---|---|
| Чистий рахунок | 98% | 88% |
| Поганий скан (нахил, шум, низька роздільність) | 10% | 85% |

Точність — схожість із еталонним текстом. `--prep` вмикайте лише для фото й поганих сканів: чистий документ він трохи погіршує.

## Браузер (`web/`)

Та сама модель Tesseract у WebAssembly: файл не залишає комп'ютер. Показує сумнівні слова та знаходить IBAN, ЄДРПОУ, РНОКПП з перевіркою контрольної суми, дату й суму до сплати.

```bash
web/build.sh                                # завантажує рушій і мовні моделі в web/dist
python3 -m http.server -d web/dist 8000     # http://localhost:8000/ocr.html
```
