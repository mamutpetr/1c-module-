"""Підбір конструкції під заряджання телефона."""
from earthcharge.core.design import Scenario
from earthcharge.core.sizing import SizingConstraints, candidate_scenario, size_for_phone
from earthcharge.core.simulator import Simulation


def test_sizing_finds_feasible_design_and_verifies():
    cons = SizingConstraints(max_series=4, max_parallel=1, max_cells=4,
                             plate_areas_cm2=(40.0, 60.0, 100.0), dt_s=60.0)
    base = Scenario()
    res = size_for_phone(base, cons)
    assert res.candidates, res.rejected
    best = res.candidates[0]
    assert best.t_done_h <= base.phone.max_time_h
    # перевірка: обраний варіант з округленою товщиною справді заряджає телефон
    sc = candidate_scenario(base, best)
    sc.sim.load_mode = "phone"
    sc.sim.dt_s = 30.0
    sim = Simulation(sc).run()
    assert sim.summary()["phone_done"]
    assert res.sensitivity and res.sensitivity_mass_range is not None
    lo, hi = res.sensitivity_mass_range
    assert lo <= hi


def test_sizing_rejects_one_cell_below_converter_voltage():
    base = Scenario()
    base.design.converter.v_in_min = 1.8
    cons = SizingConstraints(max_series=1, max_parallel=1, max_cells=1, plate_areas_cm2=(50.0,), dt_s=60.0)
    res = size_for_phone(base, cons)
    assert not res.candidates
    assert "напруга" in res.rejected[0][1]
