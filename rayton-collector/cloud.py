"""Передача даних збирача у Firestore, базу сайту на Google AI Studio.

Колекції (час і дати за годинником комп'ютера зі збирачем):

  rayton_live/current       останні значення, оновлюються кожні --live-every с
  rayton_live/schedule      графік заряду/розряду АКБ: {items: [...], updated}
  rayton_days/РРРР-ММ-ДД    minutes: {"ГГ:ХХ": середні за хвилину}, totals: енергія за день
  rayton_months/РРРР-ММ     days: {"ДД": енергія за день}

Поля потужності (кВт): solar СЕС, plant споживання, grid мережа (+ купуємо / − віддаємо),
ess АКБ (+ розряд / − заряд); soc заряд АКБ, %; sec скільки секунд хвилини були дані.
Енергія (кВт·год) рахується щосекунди з потужності: solar_kwh, plant_kwh, grid_import_kwh,
grid_export_kwh, ess_charge_kwh, ess_discharge_kwh.

Якщо інтернету немає, хвилинні дані накопичуються в data/cloud-pending.json і довантажуються пізніше.
"""
import json
import threading
import time
from pathlib import Path

from google.cloud import firestore

FIELDS = {
    "solar": "POWER_CONTROL_SOLAR_GENERATION",
    "plant": "POWER_CONTROL_PLANT_CONSUMPTION",
    "grid": "POWER_CONTROL_GRID_CONSUMPTION",
    "ess": "POWER_CONTROL_ESS_POWER",
    "soc": "RT_DATA_ESS_SOC",
}
# енергія: назва -> (поле потужності, яку частину брати: 0 усе, +1 лише додатну, −1 лише від'ємну)
ENERGY = {
    "solar_kwh": ("solar", 0),
    "plant_kwh": ("plant", 0),
    "grid_import_kwh": ("grid", 1),
    "grid_export_kwh": ("grid", -1),
    "ess_discharge_kwh": ("ess", 1),
    "ess_charge_kwh": ("ess", -1),
}
FLUSH_MAX = 5000  # хвилин за один запис (після довгого офлайну довантажуємо частинами)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # атомарно: при вимкненні світла файл не зіпсується


class Cloud:
    def __init__(self, key: Path, database: str, out: Path, live_every: int, log):
        self.db = firestore.Client.from_service_account_json(str(key), database=database)
        self.live_every = live_every
        self.log = log
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.pending_path = out / "cloud-pending.json"
        self.totals_path = out / "cloud-totals.json"
        self.pending = load_json(self.pending_path, [])
        saved = load_json(self.totals_path, {})
        self.day = saved.get("date")
        self.totals = saved.get("totals") or dict.fromkeys(ENERGY, 0.0)
        self.minute = None
        self.reset_minute()
        self.live = None
        self.schedule = None
        threading.Thread(target=self.run, daemon=True).start()

    def reset_minute(self):
        self.n = 0
        self.sums = dict.fromkeys(FIELDS, 0.0)
        self.energy = dict.fromkeys(ENERGY, 0.0)

    def tick(self, now, values):
        """Викликається щосекунди; values = None, якщо свіжих даних немає."""
        key = (now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))
        if key != self.minute:
            self.close_minute()
            self.minute = key
        if values is None:
            return
        v = {f: values.get(t) for f, t in FIELDS.items()}
        if not all(isinstance(x, (int, float)) for x in v.values()):
            return
        self.n += 1
        for f, x in v.items():
            self.sums[f] += x
        for name, (f, part) in ENERGY.items():
            self.energy[name] += (v[f] if part == 0 else max(part * v[f], 0)) / 3600
        if int(now.timestamp()) % self.live_every == 0:
            with self.lock:
                self.live = {**{f: round(float(x), 3) for f, x in v.items()}, "time": now}
            self.wake.set()

    def close_minute(self):
        if self.n:
            date, hhmm = self.minute
            if date != self.day:
                self.day, self.totals = date, dict.fromkeys(ENERGY, 0.0)
            for name, e in self.energy.items():
                self.totals[name] += e
            avg = {f: round(s / self.n, 3) for f, s in self.sums.items()}
            rec = {"date": date, "hhmm": hhmm, "avg": {**avg, "sec": self.n},
                   "totals": {k: round(x, 3) for k, x in self.totals.items()}}
            save_json(self.totals_path, {"date": self.day, "totals": self.totals})
            with self.lock:
                self.pending.append(rec)
                save_json(self.pending_path, self.pending)
            self.wake.set()
        self.reset_minute()

    def set_schedule(self, items):
        with self.lock:
            self.schedule = items
        self.wake.set()

    def run(self):
        failing = False
        while True:
            self.wake.wait(30)
            self.wake.clear()
            with self.lock:
                live, sched, pending = self.live, self.schedule, self.pending[:FLUSH_MAX]
                self.live = self.schedule = None
            try:
                if live:
                    self.db.document("rayton_live/current").set(live, timeout=15)
                if sched is not None:
                    self.db.document("rayton_live/schedule").set(
                        {"items": sched, "updated": firestore.SERVER_TIMESTAMP}, timeout=15)
                if pending:
                    self.flush(pending)
                if failing:
                    self.log("зв'язок з Firestore відновлено")
                failing = False
            except Exception as e:  # мережа, квоти, ключ: пробуємо знову, дані не губимо
                with self.lock:
                    if sched is not None and self.schedule is None:
                        self.schedule = sched
                if not failing:
                    self.log(f"не вдалося записати у Firestore ({str(e)[:200]}), повтор кожні 30 с")
                failing = True
                time.sleep(30)

    def flush(self, pending):
        days, months = {}, {}
        for r in pending:
            d = days.setdefault(r["date"], {"date": r["date"], "minutes": {}})
            d["minutes"][r["hhmm"]] = r["avg"]
            d["totals"] = r["totals"]
            m = months.setdefault(r["date"][:7], {"month": r["date"][:7], "days": {}})
            m["days"][r["date"][8:]] = r["totals"]
        batch = self.db.batch()
        for date, doc in days.items():
            batch.set(self.db.document(f"rayton_days/{date}"), {**doc, "updated": firestore.SERVER_TIMESTAMP}, merge=True)
        for month, doc in months.items():
            batch.set(self.db.document(f"rayton_months/{month}"), doc, merge=True)
        batch.commit(timeout=30)
        with self.lock:
            del self.pending[:len(pending)]
            save_json(self.pending_path, self.pending)
