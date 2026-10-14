"""Фізичне ядро не залежить від інтерфейсу."""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "earthcharge" / "core"
FORBIDDEN = ("PySide6", "PyQt5", "PyQt6", "pyqtgraph")


def test_core_has_no_ui_imports():
    for path in CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith(FORBIDDEN), f"{path.name} імпортує {n}"
