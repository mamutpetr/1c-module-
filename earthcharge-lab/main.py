"""EARTHCHARGE LAB — Electrochemical Power Simulator.

Запуск: python main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _check_dependencies() -> None:
    missing = []
    for mod in ("PySide6", "pyqtgraph", "numpy", "scipy"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print("Не встановлено пакети: " + ", ".join(missing))
        print("Встановіть їх командою:  python -m pip install -r requirements.txt")
        sys.exit(1)


if __name__ == "__main__":
    _check_dependencies()
    from earthcharge.ui.app import run
    sys.exit(run())
