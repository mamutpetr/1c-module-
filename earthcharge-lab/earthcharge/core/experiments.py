"""База даних експериментів (SQLite) та імпорт/експорт вимірювань у CSV.

Кожен дослід має тип конструкції: Mg-повітря (газодифузійний катод), занурений катод
(наприклад, Mg-графіт) або інше. Калібрування дозволене лише для конструкції того самого типу.
"""
from __future__ import annotations

import csv
import io
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from . import materials as M
from .constants import FARADAY

_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")

CONSTRUCTION_LABELS = {
    "air": "Mg–повітря (газодифузійний катод)",
    "submerged": "Занурений катод (Mg–графіт тощо)",
    "other": "Інше / невідомо",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT,
    construction TEXT NOT NULL DEFAULT 'air',
    anode TEXT,
    cathode TEXT,
    electrolyte TEXT,
    separator TEXT,
    area_cm2 REAL,
    gap_mm REAL,
    electrolyte_ml REAL,
    temperature_c REAL,
    mass_start_g REAL,
    mass_end_g REAL,
    load_desc TEXT,
    notes TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    t_s REAL NOT NULL,
    voltage_v REAL,
    current_a REAL,
    temperature_c REAL
);
CREATE INDEX IF NOT EXISTS idx_meas_exp ON measurements(experiment_id, t_s);
"""


@dataclass
class Measurement:
    t_s: float
    voltage_v: float = math.nan
    current_a: float = math.nan
    temperature_c: float = math.nan


@dataclass
class Experiment:
    id: int | None = None
    name: str = "Новий дослід"
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    construction: str = "air"
    anode: str = M.DEFAULT_ANODE
    cathode: str = M.DEFAULT_CATHODE
    electrolyte: str = M.DEFAULT_ELECTROLYTE
    separator: str = "none"
    area_cm2: float = 50.0
    gap_mm: float = 3.0
    electrolyte_ml: float = 100.0
    temperature_c: float = 25.0
    mass_start_g: float = math.nan
    mass_end_g: float = math.nan
    load_desc: str = ""
    notes: str = ""
    measurements: list = field(default_factory=list)

    # ------------------------------------------------------------ масиви
    def arrays(self) -> dict:
        ms = sorted(self.measurements, key=lambda m: m.t_s)
        return {
            "t_s": np.array([m.t_s for m in ms], dtype=float),
            "v": np.array([m.voltage_v for m in ms], dtype=float),
            "i": np.array([m.current_a for m in ms], dtype=float),
            "temp": np.array([m.temperature_c for m in ms], dtype=float),
        }

    def metrics(self) -> dict:
        a = self.arrays()
        t, v, i = a["t_s"], a["v"], a["i"]
        out = {"n_points": int(t.size), "duration_s": float(t[-1] - t[0]) if t.size > 1 else 0.0}
        ok_i = np.isfinite(i)
        ok_vi = ok_i & np.isfinite(v)
        q = float(_trapz(i[ok_i], t[ok_i])) if ok_i.sum() > 1 else 0.0
        e = float(_trapz((v * i)[ok_vi], t[ok_vi])) if ok_vi.sum() > 1 else 0.0
        out["charge_ah"] = q / 3600.0
        out["energy_wh"] = e / 3600.0
        out["v_mean"] = float(np.nanmean(v)) if np.isfinite(v).any() else math.nan
        out["i_mean"] = float(np.nanmean(i)) if ok_i.any() else math.nan
        out["p_mean"] = e / out["duration_s"] if out["duration_s"] > 0 else math.nan
        out["i_density_ma_cm2"] = out["i_mean"] / self.area_cm2 * 1000.0 if self.area_cm2 > 0 else math.nan
        dm = self.mass_start_g - self.mass_end_g
        out["mass_loss_g"] = dm
        if math.isfinite(dm) and dm > 0 and self.anode in M.ANODES:
            z = M.ANODES[self.anode].electrons_per_gram() * FARADAY
            out["faraday_mass_g"] = q / z
            out["anode_eff_pct"] = 100.0 * q / (dm * z)
            out["wh_per_g"] = out["energy_wh"] / dm
        else:
            out["faraday_mass_g"] = q / (M.ANODES[self.anode].electrons_per_gram() * FARADAY) if self.anode in M.ANODES else math.nan
            out["anode_eff_pct"] = math.nan
            out["wh_per_g"] = math.nan
        return out


class ExperimentDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(experiments)")}
        if "separator" not in cols:   # міграція бази попередньої версії
            self.conn.execute("ALTER TABLE experiments ADD COLUMN separator TEXT")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    _COLS = ("name", "date", "construction", "anode", "cathode", "electrolyte", "separator", "area_cm2", "gap_mm",
             "electrolyte_ml", "temperature_c", "mass_start_g", "mass_end_g", "load_desc", "notes")

    @staticmethod
    def _db_value(x):
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return x

    def save(self, exp: Experiment) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        vals = [self._db_value(getattr(exp, c)) for c in self._COLS]
        cur = self.conn.cursor()
        if exp.id is None:
            cur.execute(f"INSERT INTO experiments ({', '.join(self._COLS)}, created_at, updated_at) "
                        f"VALUES ({', '.join('?' * len(self._COLS))}, ?, ?)", vals + [now, now])
            exp.id = cur.lastrowid
        else:
            cur.execute(f"UPDATE experiments SET {', '.join(c + '=?' for c in self._COLS)}, updated_at=? WHERE id=?",
                        vals + [now, exp.id])
            cur.execute("DELETE FROM measurements WHERE experiment_id=?", (exp.id,))
        cur.executemany("INSERT INTO measurements (experiment_id, t_s, voltage_v, current_a, temperature_c) VALUES (?,?,?,?,?)",
                        [(exp.id, m.t_s, self._db_value(m.voltage_v), self._db_value(m.current_a),
                          self._db_value(m.temperature_c)) for m in exp.measurements])
        self.conn.commit()
        return exp.id

    def list(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT e.id, e.name, e.date, e.construction, e.anode, e.cathode, e.area_cm2, "
            "(SELECT COUNT(*) FROM measurements m WHERE m.experiment_id = e.id) "
            "FROM experiments e ORDER BY e.date DESC, e.id DESC").fetchall()
        keys = ("id", "name", "date", "construction", "anode", "cathode", "area_cm2", "n_points")
        return [dict(zip(keys, r)) for r in rows]

    def load(self, exp_id: int) -> Experiment:
        row = self.conn.execute(f"SELECT id, {', '.join(self._COLS)} FROM experiments WHERE id=?", (exp_id,)).fetchone()
        if row is None:
            raise KeyError(exp_id)
        exp = Experiment(id=row[0])
        for c, v in zip(self._COLS, row[1:]):
            if v is None and c == "separator":
                v = "none"
            elif v is None:
                v = math.nan if c in ("area_cm2", "gap_mm", "electrolyte_ml", "temperature_c", "mass_start_g", "mass_end_g") else ""
            setattr(exp, c, v)
        meas = self.conn.execute("SELECT t_s, voltage_v, current_a, temperature_c FROM measurements "
                                 "WHERE experiment_id=? ORDER BY t_s", (exp_id,)).fetchall()
        exp.measurements = [Measurement(*(math.nan if x is None else x for x in r)) for r in meas]
        return exp

    def delete(self, exp_id: int) -> None:
        self.conn.execute("DELETE FROM measurements WHERE experiment_id=?", (exp_id,))
        self.conn.execute("DELETE FROM experiments WHERE id=?", (exp_id,))
        self.conn.commit()


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

@dataclass
class CsvImport:
    measurements: list
    meta: dict
    warnings: list
    columns: dict


_COLUMN_PATTERNS = {
    "t": [r"^(час|time|t|t_s|t_c?ек|секунд\w*|хв\w*|min\w*|год\w*|hour\w*|h)\b", r"^час", r"^time"],
    "v": [r"^(напруга|voltage|v|u|u_v|v_v)\b", r"^напруг", r"^volt"],
    "i": [r"^(струм|current|i|i_a|i_ma|amp\w*)\b", r"^струм", r"^curr"],
    "temp": [r"^(температура|temperature|temp|t_c|t_°c|°c)\b", r"^темп"],
}
_META_PATTERNS = {
    "area_cm2": [r"площ", r"area"],
    "mass_start_g": [r"маса.*(поч|старт|до)", r"mass.*(start|init|before)", r"m0"],
    "mass_end_g": [r"маса.*(кін|після|фін)", r"mass.*(end|final|after)", r"m1"],
    "notes": [r"приміт", r"notes?", r"коментар", r"comment"],
    "temperature_c": [r"температура.*(середов|навк)", r"ambient"],
    "gap_mm": [r"зазор", r"відстань", r"gap"],
    "name": [r"назва", r"name"],
    "date": [r"^дата", r"^date"],
    "construction": [r"конструкц", r"construction"],
    "anode": [r"^анод", r"^anode"],
    "cathode": [r"^катод", r"^cathode"],
    "electrolyte": [r"^електроліт", r"^electrolyte"],
    "separator": [r"^сепаратор", r"^separator"],
    "load_desc": [r"навантаж", r"^load"],
}
_TEXT_META = ("notes", "name", "date", "construction", "anode", "cathode", "electrolyte", "separator", "load_desc")


def _to_float(s: str) -> float:
    s = (s or "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return math.nan
    if re.fullmatch(r"-?\d+:\d{1,2}(:\d{1,2}(\.\d+)?)?", s):
        parts = [float(p) for p in s.split(":")]
        while len(parts) < 3:
            parts.append(0.0)
        sign = -1 if parts[0] < 0 else 1
        return sign * (abs(parts[0]) * 3600 + parts[1] * 60 + parts[2])
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return math.nan


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _detect_delimiter(lines: list[str]) -> str:
    sample = "\n".join(lines[:20])
    counts = {d: sample.count(d) for d in (";", "\t", ",")}
    if counts[";"] > 0:
        return ";"
    if counts["\t"] > 0:
        return "\t"
    return ","


def _time_scale(header: str) -> float:
    h = header.lower()
    if re.search(r"(хв|min)", h):
        return 60.0
    if re.search(r"(год|hour|\bh\b|, ?h\)?$)", h):
        return 3600.0
    if re.search(r"(мс|ms)\b", h):
        return 0.001
    return 1.0


def _current_scale(header: str) -> float:
    h = header.lower()
    return 0.001 if re.search(r"(ма|ma)\b|mа|_ma|\(ma\)|, ?ма", h) else 1.0


def _voltage_scale(header: str) -> float:
    h = header.lower()
    return 0.001 if re.search(r"(мв|mv)", h) else 1.0


def parse_csv_bytes(raw: bytes) -> CsvImport:
    text = _decode(raw)
    lines = [ln for ln in text.splitlines()]
    meta: dict = {}
    warnings: list = []
    body = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.match(r"#\s*([^:=]+)[:=]\s*(.*)$", s)
            if m:
                _match_meta(m.group(1), m.group(2), meta)
            continue
        body.append(ln)
    if not body:
        raise ValueError("Файл не містить даних.")
    delim = _detect_delimiter(body)
    reader = list(csv.reader(io.StringIO("\n".join(body)), delimiter=delim))
    header = [h.strip() for h in reader[0]]
    cols: dict = {}
    for idx, h in enumerate(header):
        hl = h.lower().strip()
        for key, pats in _COLUMN_PATTERNS.items():
            if key in cols:
                continue
            if any(re.search(p, hl) for p in pats):
                if key == "t" and re.search(r"темп|temp|°c", hl):
                    continue
                cols[key] = idx
                break
        else:
            for mkey, pats in _META_PATTERNS.items():
                if any(re.search(p, hl) for p in pats):
                    cols.setdefault("meta:" + mkey, idx)
                    break
    if "t" not in cols:
        raise ValueError("Не знайдено стовпця часу (очікується «час», «time», «t»).")
    if "v" not in cols and "i" not in cols:
        raise ValueError("Не знайдено стовпців напруги чи струму.")
    ts, vs, is_ = _time_scale(header[cols["t"]]), 1.0, 1.0
    if "v" in cols:
        vs = _voltage_scale(header[cols["v"]])
    if "i" in cols:
        is_ = _current_scale(header[cols["i"]])
    meas = []
    skipped = 0
    for row in reader[1:]:
        if not row or all(not c.strip() for c in row):
            continue
        get = lambda k: _to_float(row[cols[k]]) if k in cols and cols[k] < len(row) else math.nan
        t = get("t")
        if not math.isfinite(t):
            skipped += 1
            continue
        meas.append(Measurement(t * ts, get("v") * vs, get("i") * is_, get("temp")))
        for k, idx in cols.items():
            if k.startswith("meta:") and idx < len(row) and row[idx].strip():
                mk = k[5:]
                if mk not in meta:
                    meta[mk] = row[idx].strip() if mk in _TEXT_META else _to_float(row[idx])
    if skipped:
        warnings.append(f"Пропущено рядків без часу: {skipped}.")
    if not meas:
        raise ValueError("Не вдалося прочитати жодного рядка вимірювань.")
    meas.sort(key=lambda m: m.t_s)
    t0 = meas[0].t_s
    if t0 != 0:
        for m in meas:
            m.t_s -= t0
        warnings.append("Час зміщено так, щоб перший рядок мав t = 0.")
    if ts != 1.0:
        warnings.append(f"Час переведено в секунди (множник {ts:g}).")
    if is_ != 1.0:
        warnings.append("Струм переведено з мА в А.")
    if vs != 1.0:
        warnings.append("Напругу переведено з мВ у В.")
    return CsvImport(meas, meta, warnings, cols)


def _match_meta(key: str, value: str, meta: dict) -> None:
    k = key.lower().strip()
    for mkey, pats in _META_PATTERNS.items():
        if any(re.search(p, k) for p in pats):
            meta[mkey] = value.strip() if mkey in _TEXT_META else _to_float(value)
            return


def parse_csv_file(path: str | Path) -> CsvImport:
    return parse_csv_bytes(Path(path).read_bytes())


def _match_library(value: str, library: dict) -> str | None:
    v = (value or "").strip()
    if v in library:
        return v
    low = v.lower()
    for key, item in library.items():
        if low and (low == item.name.lower() or low in item.name.lower() or item.name.lower() in low):
            return key
    return None


def _match_construction(value: str) -> str | None:
    v = (value or "").strip().lower()
    if v in CONSTRUCTION_LABELS:
        return v
    if "повітр" in v or "air" in v:
        return "air"
    if "граф" in v or "занур" in v or "submerged" in v or "graphite" in v:
        return "submerged"
    if v:
        return "other"
    return None


def apply_import(exp: Experiment, imp: CsvImport) -> None:
    exp.measurements = imp.measurements
    libs = {"anode": M.ANODES, "cathode": M.CATHODES, "electrolyte": M.ELECTROLYTES, "separator": M.SEPARATORS}
    for k, v in imp.meta.items():
        if isinstance(v, float) and not math.isfinite(v):
            continue
        if k in libs:
            key = _match_library(str(v), libs[k])
            if key is None:
                imp.warnings.append(f"Невідомий матеріал «{v}» ({k}) — залишено попередній вибір.")
                continue
            v = key
        elif k == "construction":
            v = _match_construction(str(v))
            if v is None:
                continue
        elif k in ("notes", "name", "date", "load_desc"):
            if not str(v).strip():
                continue
        setattr(exp, k, v)


def fmt_num(x: float, decimal_comma: bool, digits: int = 6) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    s = f"{x:.{digits}g}"
    return s.replace(".", ",") if decimal_comma else s


def experiment_to_csv(exp: Experiment, excel_ua: bool = True) -> str:
    delim = ";" if excel_ua else ","
    out = io.StringIO()
    meta = [("назва", exp.name), ("дата", exp.date), ("конструкція", CONSTRUCTION_LABELS.get(exp.construction, exp.construction)),
            ("анод", exp.anode), ("катод", exp.cathode), ("електроліт", exp.electrolyte), ("сепаратор", exp.separator),
            ("площа електрода, см2", fmt_num(exp.area_cm2, excel_ua)), ("зазор, мм", fmt_num(exp.gap_mm, excel_ua)),
            ("маса початкова, г", fmt_num(exp.mass_start_g, excel_ua)), ("маса кінцева, г", fmt_num(exp.mass_end_g, excel_ua)),
            ("температура середовища, °C", fmt_num(exp.temperature_c, excel_ua)),
            ("навантаження", exp.load_desc.replace("\n", " ")), ("примітки", exp.notes.replace("\n", " "))]
    for k, v in meta:
        out.write(f"# {k}: {v}\n")
    w = csv.writer(out, delimiter=delim, lineterminator="\n")
    w.writerow(["час, с", "напруга, В", "струм, А", "температура, °C"])
    for m in sorted(exp.measurements, key=lambda m: m.t_s):
        w.writerow([fmt_num(m.t_s, excel_ua), fmt_num(m.voltage_v, excel_ua), fmt_num(m.current_a, excel_ua),
                    fmt_num(m.temperature_c, excel_ua)])
    return out.getvalue()


def construction_of_cathode(cathode_key: str) -> str:
    c = M.CATHODES.get(cathode_key)
    return c.category if c else "other"
