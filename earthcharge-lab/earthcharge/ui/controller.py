"""Стан програми: поточний сценарій, жива симуляція, фонові розрахунки."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..core.design import Scenario, clone
from ..core.economics import PhysicsInputs, Prices
from ..core.experiments import ExperimentDB
from ..core.simulator import Simulation, SimulationError

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SCENARIO_DIR = ROOT / "scenarios"
EXPORT_DIR = ROOT / "exports"
EXAMPLES_DIR = ROOT / "examples" / "scenarios"


class Worker(QThread):
    """Виконує функцію у фоновому потоці. fn(progress, cancel) -> результат."""
    progress = Signal(int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            res = self.fn(self.progress.emit, lambda: self._cancel)
            self.done.emit(res)
        except SimulationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")


class AppController(QObject):
    scenario_changed = Signal(str)       # джерело зміни (шлях поля або назва дії)
    scenario_replaced = Signal()         # завантажено новий сценарій
    sim_started = Signal()
    sim_updated = Signal()
    sim_reset = Signal()
    sim_finished = Signal()
    state_changed = Signal()             # running / paused / speed
    message = Signal(str, str)           # рівень, текст
    forecast_ready = Signal(object)      # Simulation (повний прогін поточного сценарію)
    forecast_failed = Signal(str)
    busy_changed = Signal(bool, str)

    SPEEDS = (1, 10, 100, 1000)

    def __init__(self):
        super().__init__()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.scenario = Scenario()
        self.prices = Prices()
        self.phys_manual = PhysicsInputs()
        self.db = ExperimentDB(DATA_DIR / "experiments.db")
        self.sim: Simulation | None = None
        self.running = False
        self.speed = 100
        self.params_dirty = False
        self.forecast: Simulation | None = None
        self.scenario_path: Path | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._last_tick = 0.0
        self._last_emit = 0.0
        self._time_budget = 0.0
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._start_forecast)
        self._forecast_worker: Worker | None = None
        self._forecast_pending = False
        self._workers: list = []

    # ------------------------------------------------------------ сценарій
    def notify_changed(self, source: str = "") -> None:
        if self.sim is not None:
            self.params_dirty = True
        self.scenario_changed.emit(source)
        self.state_changed.emit()
        self._debounce.start()

    def replace_scenario(self, sc: Scenario, prices: Prices | None = None, phys: PhysicsInputs | None = None) -> None:
        self.reset()
        self.scenario = sc
        if prices is not None:
            self.prices = prices
        if phys is not None:
            self.phys_manual = phys
        self.scenario_replaced.emit()
        self.scenario_changed.emit("replace")
        self._debounce.start()

    # ------------------------------------------------------------ жива симуляція
    def activate(self) -> bool:
        if self.sim is not None and not self.sim.finished and not self.running:
            self.resume()
            return True
        try:
            self.sim = Simulation(self.scenario)
        except SimulationError as exc:
            self.message.emit("critical", f"Неможливо запустити: {exc}")
            return False
        self.params_dirty = False
        self.running = True
        self._time_budget = 0.0
        self._last_tick = time.perf_counter()
        self._timer.start()
        self.sim_started.emit()
        self.sim_updated.emit()
        self.state_changed.emit()
        return True

    def pause(self) -> None:
        if self.running:
            self.running = False
            self._timer.stop()
            self.state_changed.emit()

    def resume(self) -> None:
        if self.sim is None or self.sim.finished:
            return
        self.running = True
        self._last_tick = time.perf_counter()
        self._timer.start()
        self.state_changed.emit()

    def set_speed(self, speed: int) -> None:
        self.speed = speed
        self.state_changed.emit()

    def reset(self) -> None:
        self.running = False
        self._timer.stop()
        self.sim = None
        self.params_dirty = False
        self.sim_reset.emit()
        self.state_changed.emit()

    def restart(self) -> None:
        self.reset()
        self.activate()

    def run_to_end(self) -> None:
        """Миттєвий розрахунок до кінця у фоновому потоці."""
        if self.sim is None or self.sim.finished or self.params_dirty:
            try:
                sim = Simulation(self.scenario)
            except SimulationError as exc:
                self.message.emit("critical", f"Неможливо запустити: {exc}")
                return
        else:
            sim = self.sim
        self.running = False
        self._timer.stop()
        self.sim = None                 # поки рахує фоновий потік, інтерфейс не читає незавершену модель
        self.params_dirty = False
        self.sim_reset.emit()
        self.state_changed.emit()

        def job(progress, cancel):
            sim.run(progress=progress, cancel=cancel)
            return sim

        self.run_job("Розрахунок до кінця…", job, self._on_run_done)

    def _on_run_done(self, sim) -> None:
        self.sim = sim
        self.running = False
        self.sim_started.emit()
        self.sim_updated.emit()
        if sim.finished:
            self.sim_finished.emit()
        self.state_changed.emit()

    def _tick(self) -> None:
        if not self.running or self.sim is None:
            return
        now = time.perf_counter()
        elapsed = min(0.25, now - self._last_tick)
        self._last_tick = now
        # накопичуємо модельний час: крок виконується лише коли набралося dt (точна швидкість ×N)
        dt = self.sim.dt
        self._time_budget = min(self._time_budget + elapsed * self.speed, max(dt, self.speed * 0.5))
        cpu_end = now + 0.022              # не більше ~22 мс обчислень на кадр
        while not self.sim.finished and self._time_budget >= dt - 1e-9:
            self.sim.step()
            self._time_budget -= dt
            if time.perf_counter() > cpu_end:
                break
        if now - self._last_emit > 0.09 or self.sim.finished:
            self._last_emit = now
            self.sim_updated.emit()
        if self.sim.finished:
            self.running = False
            self._timer.stop()
            self.sim_updated.emit()
            self.sim_finished.emit()
            self.state_changed.emit()

    # ------------------------------------------------------------ фонові задачі
    def run_job(self, title: str, fn, on_done, on_progress=None, on_fail=None) -> Worker:
        w = Worker(fn, self)
        self._workers.append(w)
        self.busy_changed.emit(True, title)

        def finish(res):
            self._cleanup(w)
            on_done(res)

        def fail(msg):
            self._cleanup(w)
            if on_fail:
                on_fail(msg)
            else:
                self.message.emit("critical", msg)

        w.done.connect(finish)
        w.failed.connect(fail)
        if on_progress:
            w.progress.connect(on_progress)
        w.start()
        return w

    def _cleanup(self, w) -> None:
        if w in self._workers:
            self._workers.remove(w)
        self.busy_changed.emit(bool(self._workers), "")

    # ------------------------------------------------------------ прогноз
    def _start_forecast(self) -> None:
        if self._forecast_worker is not None:
            self._forecast_pending = True
            self._forecast_worker.cancel()
            return
        sc = clone(self.scenario)
        sc.sim.dt_s = max(sc.sim.dt_s, 10.0)

        def job(progress, cancel):
            sim = Simulation(sc)
            sim.run(cancel=cancel)
            return sim

        w = Worker(job, self)
        self._forecast_worker = w

        def done(sim):
            self._forecast_worker = None
            if self._forecast_pending:
                self._forecast_pending = False
                self._start_forecast()
                return
            if sim.finished:
                self.forecast = sim
                self.forecast_ready.emit(sim)

        def fail(msg):
            self._forecast_worker = None
            self.forecast = None
            self.forecast_failed.emit(msg)
            if self._forecast_pending:
                self._forecast_pending = False
                self._start_forecast()

        w.done.connect(done)
        w.failed.connect(fail)
        w.start()

    def request_forecast(self) -> None:
        self._debounce.start()

    def shutdown(self) -> None:
        self._timer.stop()
        for w in list(self._workers) + ([self._forecast_worker] if self._forecast_worker else []):
            w.cancel()
            w.wait(3000)
        self.db.close()
