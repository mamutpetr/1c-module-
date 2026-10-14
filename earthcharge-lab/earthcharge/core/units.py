"""Перетворення одиниць вимірювання.

Внутрішні розрахунки ведуться з явними суфіксами в іменах змінних:
_s (секунди), _a (ампери), _v (вольти), _w (вати), _j (джоулі), _g (грами),
_cm2 (см²), _mm (мм), _a_cm2 (А/см²), _ohm (Ом).
"""
from __future__ import annotations

from .constants import FARADAY, MOLAR_MASS, N_ELECTRONS_MG, SECONDS_PER_HOUR, SECONDS_PER_YEAR

MG_DENSITY_PURE = 1.738  # г/см³


def wh_from_j(j: float) -> float:
    return j / SECONDS_PER_HOUR


def j_from_wh(wh: float) -> float:
    return wh * SECONDS_PER_HOUR


def wh_from_mah(mah: float, volts: float) -> float:
    """5000 мА·год при 3,85 В -> 19,25 Вт·год."""
    return mah * volts / 1000.0


def mah_from_wh(wh: float, volts: float) -> float:
    return wh * 1000.0 / volts


def ah_from_c(coulombs: float) -> float:
    return coulombs / SECONDS_PER_HOUR


def c_from_ah(ah: float) -> float:
    return ah * SECONDS_PER_HOUR


def cm2_from_mm(length_mm: float, width_mm: float) -> float:
    return length_mm * width_mm / 100.0


def cm3_from_mm(length_mm: float, width_mm: float, thickness_mm: float) -> float:
    return length_mm * width_mm * thickness_mm / 1000.0


def a_cm2_from_ma_cm2(x: float) -> float:
    return x * 1e-3


def ma_cm2_from_a_cm2(x: float) -> float:
    return x * 1e3


def hours(seconds: float) -> float:
    return seconds / SECONDS_PER_HOUR


def mg_specific_capacity_mah_g() -> float:
    """Теоретична питома ємність чистого магнію: ≈ 2205 мА·год/г."""
    return N_ELECTRONS_MG * FARADAY / MOLAR_MASS["Mg"] / 3.6


def mg_grams_per_ah() -> float:
    """Маса Mg, що розчиняється на 1 А·год за законом Фарадея: ≈ 0,4534 г/(А·год)."""
    return MOLAR_MASS["Mg"] * SECONDS_PER_HOUR / (N_ELECTRONS_MG * FARADAY)


def mg_corrosion_mm_per_year_from_ma_cm2(i_ma_cm2: float, density_g_cm3: float = MG_DENSITY_PURE) -> float:
    """Швидкість корозії, мм/рік, еквівалентна густині струму (для чистого Mg 1 мА/см² ≈ 22,9 мм/рік)."""
    grams_per_cm2_s = i_ma_cm2 * 1e-3 * MOLAR_MASS["Mg"] / (N_ELECTRONS_MG * FARADAY)
    return grams_per_cm2_s * SECONDS_PER_YEAR / density_g_cm3 * 10.0


def format_duration(seconds: float) -> str:
    """Тривалість українською: «6 год 41 хв», «45 с»."""
    if seconds != seconds or seconds == float("inf"):
        return "—"
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f} с"
    total_min = int(round(seconds / 60.0))
    h, m = divmod(total_min, 60)
    if h == 0:
        return f"{m} хв"
    if h >= 100:
        return f"{h} год"
    return f"{h} год {m:02d} хв"


def fmt(value: float, digits: int = 2) -> str:
    """Число з десятковою комою (українська нотація)."""
    if value is None or value != value:
        return "—"
    return f"{value:.{digits}f}".replace(".", ",")
