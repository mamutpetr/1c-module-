"""Запуск інтерфейсу."""
from __future__ import annotations

import os
import sys


def run() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import QLocale, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QLocale.setDefault(QLocale(QLocale.Ukrainian, QLocale.Ukraine))
    app = QApplication(sys.argv)
    app.setApplicationName("EARTHCHARGE LAB")
    app.setOrganizationName("EarthCharge")
    from .theme import apply_theme
    apply_theme(app)
    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()
