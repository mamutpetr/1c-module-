"""Збереження й завантаження сценаріїв (JSON)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .. import APP_NAME, APP_VERSION
from .design import Scenario, from_dict, to_dict
from .economics import Prices, PhysicsInputs

FORMAT = "earthcharge-scenario"
FORMAT_VERSION = 1


def scenario_to_json(sc: Scenario, prices: Prices | None = None, physics: PhysicsInputs | None = None) -> str:
    doc = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app": f"{APP_NAME} {APP_VERSION}",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "scenario": to_dict(sc),
    }
    if prices is not None:
        doc["economics"] = {"prices": to_dict(prices)}
        if physics is not None:
            doc["economics"]["physics_manual"] = to_dict(physics)
    return json.dumps(doc, ensure_ascii=False, indent=2)


def scenario_from_json(text: str) -> tuple[Scenario, Prices | None, PhysicsInputs | None]:
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("Файл сценарію пошкоджено.")
    if doc.get("format") not in (None, FORMAT):
        raise ValueError("Це не файл сценарію EarthCharge.")
    if int(doc.get("version", 1)) > FORMAT_VERSION:
        raise ValueError("Сценарій створено новішою версією програми.")
    sc = from_dict(Scenario, doc.get("scenario", doc))
    econ = doc.get("economics") or {}
    prices = from_dict(Prices, econ["prices"]) if "prices" in econ else None
    phys = from_dict(PhysicsInputs, econ["physics_manual"]) if "physics_manual" in econ else None
    return sc, prices, phys


def save_scenario(path: str | Path, sc: Scenario, prices: Prices | None = None,
                  physics: PhysicsInputs | None = None) -> None:
    Path(path).write_text(scenario_to_json(sc, prices, physics), encoding="utf-8")


def load_scenario(path: str | Path) -> tuple[Scenario, Prices | None, PhysicsInputs | None]:
    return scenario_from_json(Path(path).read_text(encoding="utf-8-sig"))
