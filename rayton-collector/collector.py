"""Збирач даних з контролера Rayton: безперервно записує показники в CSV і, за бажанням, у Firestore.

    pip install -r requirements.txt
    python collector.py                                   # http://192.168.0.57, рядок кожні 5 с у data/
    python collector.py --url http://192.168.0.57 --interval 1 --out data
    python collector.py --firestore-key ключ.json --firestore-db ID-бази   # ще й у базу сайту (див. cloud.py)

Кабінет контролера (Node-RED, FlowFuse Dashboard 2.0) не зберігає історію, а лише передає поточні
значення через Socket.IO: /dashboard/socket.io, подія "msg-input:<id віджета>", у полі topic назва
показника. Скрипт підключається як ще одна вкладка браузера і тільки слухає: він нічого не надсилає
контролеру, тому змінити режим роботи станції чи графік АКБ не може.

Кожні --interval секунд у data/РРРР-ММ-ДД.csv дописується рядок з останніми значеннями.
Графік заряду/розряду АКБ зберігається в data/schedule.json, коли змінюється.
"""
import argparse
import csv
import itertools
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import socketio

# Показники з кабінету (оновлюються раз на секунду). Контролер рахує споживання як
# СЕС + мережа + АКБ, звідси знаки: мережа + купуємо / − віддаємо, АКБ + розряд / − заряд.
KNOWN = {
    "POWER_CONTROL_SOLAR_GENERATION": "СЕС кВт",           # генерація СЕС
    "POWER_CONTROL_PLANT_CONSUMPTION": "споживання кВт",   # споживання підприємства
    "POWER_CONTROL_GRID_CONSUMPTION": "мережа кВт",
    "POWER_CONTROL_ESS_POWER": "АКБ кВт",
    "RT_DATA_ESS_SOC": "заряд АКБ %",
}
# віджети без topic, які передають таблиці: id віджета -> ім'я файлу
WIDGET_FILES = {"670fe9d4a41e6e6c": "schedule"}
STALE_AFTER = 10  # с без нових повідомлень (зазвичай йдуть щосекунди): старі значення не пишемо як нові


def log(text: str):
    print(f"{datetime.now():%H:%M:%S} {text}", flush=True)


class State:
    def __init__(self, out: Path):
        self.out = out
        self.lock = threading.Lock()
        self.values = {}
        self.last_msg = 0.0
        self.saved = {}  # ім'я файлу -> останній записаний JSON
        self.seen_events = set()
        self.cloud = None

    def save_json(self, name: str, data):
        text = json.dumps(data, ensure_ascii=False, indent=1)
        if self.saved.get(name) != text:
            (self.out / f"{name}.json").write_text(text, encoding="utf-8")
            self.saved[name] = text
            if name == "schedule" and self.cloud:
                self.cloud.set_schedule(data)

    def on_event(self, event: str, *args):
        if not event.startswith("msg-input:") or not args or not isinstance(args[0], dict):
            if event == "ui-config" and args:  # опис сторінок і віджетів, якщо кабінет його надсилає
                self.save_json("ui-config", args[-1])
            if event not in self.seen_events:
                self.seen_events.add(event)
                log(f"подія {event}")
            return
        widget = event.split(":", 1)[1]
        msg = args[0]
        payload = msg.get("payload")
        name = msg.get("topic") or widget
        if isinstance(payload, (list, dict)):
            self.save_json(WIDGET_FILES.get(widget, name), payload)
        elif isinstance(payload, (int, float, str)):
            with self.lock:
                if name not in self.values and name not in KNOWN:
                    log(f"новий показник: {name} = {payload}")
                self.values[name] = payload
                self.last_msg = time.monotonic()

    def on_disconnect(self, *_):
        log("зв'язок з контролером втрачено, перепідключаюсь...")
        with self.lock:
            self.last_msg = 0.0

    def snapshot(self):
        """Останні значення або None, якщо свіжих даних немає."""
        with self.lock:
            if self.last_msg and time.monotonic() - self.last_msg <= STALE_AFTER:
                return dict(self.values)


def open_csv(out: Path, day: str, header: list[str]):
    # якщо набір показників змінився (з'явився новий), пишемо в наступну частину дня
    for part in itertools.count(1):
        path = out / (f"{day}.csv" if part == 1 else f"{day}_{part}.csv")
        if not path.exists():
            f = path.open("w", newline="", encoding="utf-8-sig")  # -sig: Excel бачить кирилицю й UTF-8
            csv.writer(f).writerow(header)
            return f
        with path.open(newline="", encoding="utf-8-sig") as f:
            if next(csv.reader(f), None) == header:
                return path.open("a", newline="", encoding="utf-8-sig")


def fmt(v):
    return round(v, 3) if isinstance(v, float) else int(v) if isinstance(v, bool) else v


def ticker(state: State, interval: int):
    f, key, rows, paused = None, None, 0, False
    while True:
        time.sleep(1 - time.time() % 1)  # рівно на початку кожної секунди
        now = datetime.now().astimezone()
        values = state.snapshot()
        if state.cloud:
            state.cloud.tick(now, values)
        if values is None:
            if rows and not paused:
                log("немає свіжих даних від контролера, запис призупинено")
            paused = True
            continue
        if rows and paused:
            log("дані знову надходять, запис продовжено")
        paused = False
        if int(now.timestamp()) % interval:
            continue
        cols = list(KNOWN) + sorted(set(values) - set(KNOWN))
        if key != (now.date(), cols):
            if f:
                f.close()
            key = (now.date(), cols)
            f = open_csv(state.out, now.strftime("%Y-%m-%d"), ["time", *cols])
        csv.writer(f).writerow([now.isoformat(timespec="seconds"), *(fmt(values.get(c, "")) for c in cols)])
        f.flush()
        rows += 1
        if rows == 1 or now.second < interval and now.minute % 10 == 0:
            short = ", ".join(f"{label} {fmt(values[c])}" for c, label in KNOWN.items() if c in values)
            log(f"записано рядків: {rows} ({short})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://192.168.0.57", help="адреса кабінету контролера")
    ap.add_argument("--interval", type=int, default=5, help="як часто писати рядок у CSV, с (дані йдуть раз на 1 с)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data", help="папка для CSV")
    ap.add_argument("--firestore-key", type=Path, help="JSON-ключ сервісного акаунта Firebase: увімкнути запис у Firestore")
    ap.add_argument("--firestore-db", default="(default)", help="ID бази Firestore (firestoreDatabaseId у AI Studio)")
    ap.add_argument("--live-every", type=int, default=10, help="як часто оновлювати rayton_live/current, с")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    state = State(args.out)
    if args.firestore_key:
        from cloud import Cloud

        state.cloud = Cloud(args.firestore_key, args.firestore_db, args.out, args.live_every, log)
        log(f"запис у Firestore увімкнено (база {args.firestore_db})")
    sio = socketio.Client(reconnection_delay=2, reconnection_delay_max=10)
    sio.on("*", state.on_event)
    sio.on("connect", lambda: log(f"підключено до {args.url}"))
    sio.on("disconnect", state.on_disconnect)
    threading.Thread(target=ticker, args=(state, args.interval), daemon=True).start()
    log(f"пишу в {args.out.resolve()}, Ctrl+C для зупинки")

    failing = False
    try:
        while True:
            try:
                # браузер працює з кабінетом тільки через polling (без WebSocket), робимо так само
                sio.connect(args.url, socketio_path="dashboard/socket.io", transports=["polling"], wait_timeout=10)
                failing = False
                sio.wait()
            except socketio.exceptions.ConnectionError as e:
                if not failing:
                    log(f"контролер недоступний ({str(e)[:200]}), пробую кожні 10 с")
                failing = True
            time.sleep(10)
    except KeyboardInterrupt:
        sio.disconnect()


if __name__ == "__main__":
    main()
