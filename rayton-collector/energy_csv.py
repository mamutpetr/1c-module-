"""Погодинний звіт з контролера Rayton у форматі старого моніторингу: energy-trend-chart-1D-РРРР-ММ-ДД.csv

    pip install "python-socketio[client]"
    python energy_csv.py                                        # http://192.168.0.57, файли в data/
    python energy_csv.py --url http://192.168.0.57/dashboard/page4 --out D:\\rayton

Щосекунди бере потужності з кабінету контролера й додає енергію до поточної години.
Файл дня переписується щохвилини: завершені години плюс поточна, яка ще набирається.
Після перезапуску скрипт продовжує з того, що вже є у файлі.

Генератор, DATA_106 і ціну контролер не передає, ці колонки залишаються порожніми.
Години, коли скрипт не працював, теж порожні.
"""
import argparse
import csv
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from collector import State, connect_forever, log

HEADER = ["Time", "Hour", "Споживання з мережі, кВт*год", "Сонячна генерація, кВт*год",
          "Споживання від генератору, кВт*год", "DATA_106, кВт*год", "Заряд УЗЕ з СЕС, кВт*год",
          "Заряд УЗЕ загалом, кВт*год", "Розряд УЗЕ загалом, кВт*год", "Ціна, грн/кВт*год"]
COLS = [2, 3, 6, 7, 8]  # номери колонок, які рахуємо


def power_by_column(values):
    """Потужності кабінету (кВт) по колонках звіту; None, якщо якогось показника немає."""
    try:
        solar = float(values["POWER_CONTROL_SOLAR_GENERATION"])
        grid = float(values["POWER_CONTROL_GRID_CONSUMPTION"])  # + купуємо, − віддаємо
        ess = float(values["POWER_CONTROL_ESS_POWER"])  # + розряд, − заряд
    except (KeyError, TypeError, ValueError):
        return None
    grid_in, charge = max(grid, 0), max(-ess, 0)
    # з СЕС: та частина заряду, яку не покрила покупка з мережі
    return {2: grid_in, 3: max(solar, 0), 6: max(charge - grid_in, 0), 7: charge, 8: max(ess, 0)}


def fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")  # 13.625, 4.4, 42, 0: як у вихідному файлі
    return "0" if s == "-0" else s


class Report:
    def __init__(self, out: Path):
        self.out = out
        self.lock = threading.Lock()
        self.day = None
        self.hours = {}  # година 1..24 -> {колонка: кВт·год}
        self.warned = False

    def path(self, day: str) -> Path:
        return self.out / f"energy-trend-chart-1D-{day}.csv"

    def load(self, day: str):
        self.day, self.hours = day, {}
        try:
            with self.path(day).open(newline="", encoding="utf-8-sig") as f:
                for row in list(csv.reader(f))[1:]:
                    if any(row[c] for c in COLS):
                        self.hours[int(row[1])] = {c: float(row[c] or 0) for c in COLS}
        except FileNotFoundError:
            pass
        if self.hours:
            log(f"{self.path(day).name}: продовжую, вже є годин: {len(self.hours)}")

    def save(self):
        if not self.day:
            return
        start = datetime.strptime(self.day, "%Y-%m-%d")
        path, tmp = self.path(self.day), self.path(self.day).with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(HEADER)
            for h in range(1, max(self.hours, default=0) + 1):
                acc = self.hours.get(h)
                cells = [fmt(acc[c]) if acc and c in COLS else "" for c in range(2, len(HEADER))]
                w.writerow([f"{start + timedelta(hours=h):%Y-%m-%d %H:%M:%S}", h, *cells])
        try:
            tmp.replace(path)
            self.warned = False
        except PermissionError:  # Windows не дає замінити файл, відкритий в Excel
            if not self.warned:
                log(f"{path.name} відкритий в іншій програмі, оновлю, коли його закриють")
            self.warned = True

    def tick(self, now: datetime, values):
        with self.lock:
            day = now.strftime("%Y-%m-%d")
            if day != self.day:
                self.save()  # закриваємо попередній день з повною 24-ю годиною
                self.load(day)
            power = power_by_column(values) if values else None
            if power:
                acc = self.hours.setdefault(now.hour + 1, dict.fromkeys(COLS, 0.0))
                for c, kw in power.items():
                    acc[c] += kw / 3600  # кВт × 1 с = кВт·год / 3600
            if now.second == 0:
                self.save()


def ticker(state: State, report: Report):
    while True:
        time.sleep(1 - time.time() % 1)
        now = datetime.now()
        # показник за секунду, що щойно минула, належить годині, в якій вона почалась
        report.tick(now - timedelta(seconds=1), state.snapshot())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://192.168.0.57", help="адреса кабінету контролера")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data", help="папка для звітів")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    state, report = State(args.out), Report(args.out)
    threading.Thread(target=ticker, args=(state, report), daemon=True).start()
    log(f"пишу погодинні звіти в {args.out.resolve()}, Ctrl+C для зупинки")
    connect_forever(args.url, state)
    with report.lock:
        report.save()


if __name__ == "__main__":
    main()
