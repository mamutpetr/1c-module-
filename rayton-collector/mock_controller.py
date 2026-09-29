"""Імітація кабінету контролера Rayton для перевірки без доступу до локальної мережі.

    pip install aiohttp python-socketio
    python mock_controller.py                              # http://127.0.0.1:8080
    python collector.py --url http://127.0.0.1:8080 --interval 1

Раз на секунду надсилає ті самі події, що й справжній контролер (записано з /dashboard/page4):
5 показників і графік заряду/розряду АКБ. Значення ті самі за формою, але вигадані.
"""
import argparse
import random

import socketio
from aiohttp import web

sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
WIDGETS = {
    "POWER_CONTROL_ESS_POWER": "8c7cfab96281f435",
    "POWER_CONTROL_GRID_CONSUMPTION": "478bd7c1b8a5a578",
    "POWER_CONTROL_PLANT_CONSUMPTION": "047150ebf3db80ea",
    "POWER_CONTROL_SOLAR_GENERATION": "f6f5e976a912e81d",
    "RT_DATA_ESS_SOC": "6b7cc12752405729",
}
SCHEDULE = [
    {"REC_NO": str(i + 1), "CHARGE_FROM_GRID": start == "12:00", "DATE": "2026-09-29", "ALLOW_TO_SELL": False,
     "START_TIME": start, "CHARGE_POWER": 220, "DISCHARGE_POWER": 200, "CHARGE_LIMIT": 97, "SOURCE": 2, "END_TIME": end}
    for i, (start, end) in enumerate(zip(
        ["00:00", "01:00", "03:00", "04:00", "05:00", "09:00", "11:00", "12:00", "14:00", "17:00", "18:00", "23:00"],
        ["01:00", "03:00", "04:00", "05:00", "09:00", "11:00", "12:00", "14:00", "17:00", "18:00", "23:00", "00:00"]))
]


async def broadcast():
    while True:
        solar = 34 + random.uniform(-1.5, 1.5)
        grid = random.uniform(-2.5, 2.9)
        ess = -7
        values = {
            "POWER_CONTROL_ESS_POWER": ess,
            "POWER_CONTROL_GRID_CONSUMPTION": grid,
            "POWER_CONTROL_PLANT_CONSUMPTION": solar + grid + ess,
            "POWER_CONTROL_SOLAR_GENERATION": solar,
            "RT_DATA_ESS_SOC": 96,
        }
        for topic, value in values.items():
            await sio.emit(f"msg-input:{WIDGETS[topic]}", {"payload": value, "topic": topic, "_msgid": "0"})
        await sio.emit("msg-input:670fe9d4a41e6e6c", {"payload": SCHEDULE, "topic": "", "_msgid": "0"})
        await sio.sleep(1)


async def start_background(app):
    sio.start_background_task(broadcast)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    app = web.Application()
    sio.attach(app, socketio_path="dashboard/socket.io")
    app.on_startup.append(start_background)
    web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
