"""Збереження/завантаження сценаріїв та експорт CSV."""
import json

import pytest

from earthcharge.core.design import Scenario, from_dict, to_dict
from earthcharge.core.economics import Prices
from earthcharge.core.params import set_override
from earthcharge.core.scenarios import load_scenario, save_scenario, scenario_from_json
from earthcharge.core.simulator import Simulation
from earthcharge.export.csv_export import simulation_csv, summary_csv
from helpers import quick


def test_roundtrip(tmp_path):
    sc = Scenario()
    sc.design.name = "Тест «Ω»"
    sc.design.stack.n_cells = 5
    sc.design.supercap.enabled = True
    set_override(sc.design, "anode.k_nde", 0.33)
    p = tmp_path / "s.json"
    save_scenario(p, sc, Prices(mg_price_per_kg=123.0))
    back, prices, _ = load_scenario(p)
    assert to_dict(back) == to_dict(sc)
    assert prices.mg_price_per_kg == 123.0


def test_missing_and_unknown_keys_tolerated():
    sc, _, _ = scenario_from_json(json.dumps({"format": "earthcharge-scenario", "version": 1,
                                              "scenario": {"design": {"geometry": {"gap_mm": 5, "foo": 1}}}}))
    assert sc.design.geometry.gap_mm == 5.0
    assert sc.design.geometry.plate_length_mm == Scenario().design.geometry.plate_length_mm


def test_rejects_foreign_file():
    with pytest.raises(ValueError):
        scenario_from_json(json.dumps({"format": "other"}))


def test_from_dict_types():
    from earthcharge.core.design import Geometry
    g = from_dict(Geometry, {"faces": "2", "gap_mm": "3,0".replace(",", ".")})
    assert g.faces == 2 and g.gap_mm == 3.0


def test_csv_export():
    sim = Simulation(quick("phone", hours=0.2)).run()
    text = simulation_csv(sim, excel_ua=True)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Час, год;")
    assert len(lines) == sim.rec.n + 1
    assert "," in lines[2]
    text2 = simulation_csv(sim, excel_ua=False)
    assert text2.splitlines()[0].startswith('"Час, год",')
    assert "Енергетичний баланс" in summary_csv(sim)
