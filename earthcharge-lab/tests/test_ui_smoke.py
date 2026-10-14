"""Димовий тест інтерфейсу: вікно створюється, симуляція запускається, усі сторінки відкриваються.

Пропускається, якщо PySide6 не встановлено. Працює без дисплея (QT_QPA_PLATFORM=offscreen).
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_main_window_runs(app, tmp_path, monkeypatch):
    import earthcharge.ui.controller as C
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    monkeypatch.setattr(C, "SCENARIO_DIR", tmp_path / "sc")
    monkeypatch.setattr(C, "EXPORT_DIR", tmp_path / "ex")
    from earthcharge.ui.theme import apply_theme
    from earthcharge.ui.main_window import MainWindow
    apply_theme(app)
    w = MainWindow()
    w.show()
    c = w.ctrl
    c.set_speed(1000)
    assert c.activate()
    pump(app, 1.0)
    assert c.sim is not None and c.sim.state.t > 0
    c.pause()
    for i in range(len(w.pages)):
        w.nav.setCurrentRow(i)
        pump(app, 0.05)
    c.reset()
    assert c.sim is None
    c.shutdown()
    w.close()
