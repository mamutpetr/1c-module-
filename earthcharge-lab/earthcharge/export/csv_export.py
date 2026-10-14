"""Експорт часових рядів симуляції в CSV."""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path

import numpy as np

from ..core.simulator import CHANNELS, LEDGER_LABELS


def _num(x: float, decimal_comma: bool) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    s = f"{x:.6g}"
    return s.replace(".", ",") if decimal_comma else s


def simulation_csv(sim, excel_ua: bool = True, every: int = 1) -> str:
    """CSV з усіма каналами. excel_ua: «;» і десяткова кома (як очікує Excel з українською локаллю)."""
    delim = ";" if excel_ua else ","
    out = io.StringIO()
    w = csv.writer(out, delimiter=delim, lineterminator="\n")
    keys = [k for k, _, _ in CHANNELS]
    w.writerow([f"{label}, {unit}" for _, label, unit in CHANNELS])
    data = [sim.rec.get(k) for k in keys]
    n = sim.rec.n
    step = max(1, int(every))
    for r in range(0, n, step):
        w.writerow([_num(float(col[r]), excel_ua) for col in data])
    return out.getvalue()


def summary_csv(sim, excel_ua: bool = True) -> str:
    delim = ";" if excel_ua else ","
    out = io.StringIO()
    w = csv.writer(out, delimiter=delim, lineterminator="\n")
    w.writerow(["Показник", "Значення"])
    for k, v in sim.summary().items():
        if k == "verdicts":
            continue
        w.writerow([k, _num(v, excel_ua) if isinstance(v, (int, float)) and not isinstance(v, bool) else v])
    w.writerow([])
    w.writerow(["Енергетичний баланс", "Вт·год"])
    w.writerow(["Ідеальна хімічна енергія (3,09 В)", _num(sim.ledger.ideal_j / 3600.0, excel_ua)])
    for k, v in sim.ledger_breakdown().items():
        w.writerow([LEDGER_LABELS.get(k, k), _num(v / 3600.0, excel_ua)])
    w.writerow([])
    w.writerow(["Висновки"])
    for level, text in sim.summary()["verdicts"]:
        w.writerow([level, text])
    return out.getvalue()


def write_text(path: str | Path, text: str) -> None:
    # utf-8 з BOM, щоб Excel у Windows коректно показав кирилицю
    Path(path).write_text(text, encoding="utf-8-sig")


def downsample_every(n: int, max_rows: int = 20000) -> int:
    return max(1, int(np.ceil(n / max_rows)))
