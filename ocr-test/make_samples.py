"""Генерує тестові скани рахунку у форматах, які віддають сканери та МФУ.

samples/scan_invoice.pdf     2 сторінки A4: офісний скан 300 dpi і поганий скан 150 dpi (сірий, JPEG)
samples/scan_invoice_g4.tif  ті самі 2 сторінки, ч/б TIFF зі стисненням CCITT G4 (як «скан у мережеву папку»)
"""
import io
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "samples"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

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

A4_300 = (2480, 3508)


def render_a4() -> Image.Image:
    """Сторінка A4 при 300 dpi, шрифт ~10 pt."""
    img = Image.new("L", A4_300, 255)
    d = ImageDraw.Draw(img)
    mono, mono_b = ImageFont.truetype(MONO, 40), ImageFont.truetype(MONO_B, 40)
    y = 260
    for style, text in LINES:
        d.text((220, y), text, font=mono_b if style == "b" else mono, fill=0)
        y += 68
    return img


def scan(img: Image.Image, *, dpi: int, skew: float, noise: float, blur: float, light: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = img.rotate(skew, resample=Image.BICUBIC, fillcolor=255)
    if dpi != 300:
        img = img.resize((img.width * dpi // 300, img.height * dpi // 300), Image.BILINEAR)
    img = img.filter(ImageFilter.GaussianBlur(blur))
    a = np.asarray(img).astype(np.int16)
    a += rng.normal(0, noise, a.shape).astype(np.int16)
    a -= np.linspace(0, light, a.shape[1]).astype(np.int16)  # нерівне освітлення (кришка сканера не притиснута)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def to_bw(img: Image.Image) -> Image.Image:
    """Режим «ч/б» сканера: фіксований поріг без дизерингу."""
    return img.point(lambda v: 255 if v > 140 else 0).convert("1", dither=Image.Dither.NONE)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    page = render_a4()
    office = scan(page, dpi=300, skew=0.7, noise=8, blur=0.7, light=15, seed=1)
    poor = scan(page, dpi=150, skew=-2.5, noise=18, blur=0.8, light=60, seed=2)

    # кожна сторінка — JPEG-зображення з розміром сторінки за її dpi, як у PDF від МФУ
    doc = pymupdf.open()
    for im, dpi in ((office, 300), (poor, 150)):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        p = doc.new_page(width=im.width * 72 / dpi, height=im.height * 72 / dpi)
        p.insert_image(p.rect, stream=buf.getvalue())
    doc.save(OUT / "scan_invoice.pdf", deflate=True)

    bw = [to_bw(office), to_bw(poor)]
    bw[0].save(OUT / "scan_invoice_g4.tif", save_all=True, append_images=bw[1:], compression="group4", dpi=(300, 300))

    (OUT / "invoice_ground_truth.txt").write_text("\n".join(t for _, t in LINES) + "\n", encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:28} {f.stat().st_size // 1024:>5} КБ")
