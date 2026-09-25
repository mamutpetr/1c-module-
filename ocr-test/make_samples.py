"""Генерує тестові зображення документа (чисте + «погане сканування»)."""
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "samples"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

LINES = [
    ("b", "РАХУНОК НА ОПЛАТУ № 1247 від 15 вересня 2026 р."),
    ("", ""),
    ("", "Постачальник: ТОВ «Альфа-Трейд», ЄДРПОУ 38291040"),
    ("", "IBAN: UA213223130000026007233566001"),
    ("", "Покупець: ФОП Петренко Іван Миколайович"),
    ("", ""),
    ("b", "№  Товар                          К-сть   Ціна     Сума"),
    ("", "1  Папір офісний А4, 500 арк.       10   185,00   1850,00"),
    ("", "2  Картридж HP 85A                   2   920,50   1841,00"),
    ("", "3  Ручка кулькова синя              50     7,20    360,00"),
    ("", ""),
    ("b", "Разом без ПДВ:                              4051,00 грн"),
    ("", "ПДВ 20%:                                    810,20 грн"),
    ("b", "Всього до сплати:                          4861,20 грн"),
    ("", ""),
    ("", "Сума прописом: чотири тисячі вісімсот шістдесят одна грн 20 коп."),
]


def render() -> Image.Image:
    img = Image.new("L", (1700, 1000), 255)
    d = ImageDraw.Draw(img)
    mono = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 30)
    mono_b = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 30)
    y = 60
    for style, text in LINES:
        d.text((80, y), text, font=mono_b if style == "b" else mono, fill=0)
        y += 52
    return img


def degrade(img: Image.Image) -> Image.Image:
    random.seed(1)
    np.random.seed(1)
    img = img.rotate(2.5, resample=Image.BICUBIC, expand=True, fillcolor=255)
    img = img.resize((img.width // 2, img.height // 2), Image.BILINEAR)  # ~ низька роздільність
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    a = np.asarray(img).astype(np.int16)
    a = a + np.random.normal(0, 18, a.shape).astype(np.int16)  # шум
    grad = np.linspace(0, 60, a.shape[1]).astype(np.int16)  # нерівне освітлення
    a = np.clip(a - grad, 0, 255).astype(np.uint8)
    return Image.fromarray(a)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    clean = render()
    clean.save(OUT / "invoice_clean.png")
    degrade(clean).save(OUT / "invoice_bad_scan.png")
    Path(OUT / "invoice_ground_truth.txt").write_text(
        "\n".join(t for _, t in LINES) + "\n", encoding="utf-8"
    )
    print("готово:", *sorted(p.name for p in OUT.iterdir()))
