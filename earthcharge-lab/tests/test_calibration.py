"""Калібрування: відновлення відомих параметрів із синтетичних «вимірювань»."""
import numpy as np
import pytest

from earthcharge.core.calibration import (apply_calibration, calibrate_efficiency, calibrate_passivation,
                                          calibrate_polarization, experiment_design, predict_points, replay)
from earthcharge.core.design import Design
from earthcharge.core.experiments import Experiment, Measurement
from earthcharge.core.params import build_params


def synthetic_step_test(true_values: dict) -> Experiment:
    exp = Experiment(name="Синтетичний", area_cm2=20.0, gap_mm=3.0, temperature_c=25.0)
    currents = [0.0, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
    exp.measurements = [Measurement(k * 30.0, 0.0, i) for k, i in enumerate(currents)]
    d = experiment_design(exp)
    v = predict_points(d, exp, true_values)
    for m, vv in zip(exp.measurements, v):
        m.voltage_v = float(vv)
    return exp


def test_polarization_fit_recovers_parameters():
    true = {"anode.ocp": -1.60, "cathode.i0": 0.08, "cathode.asr": 3.0}
    exp = synthetic_step_test(true)
    res = calibrate_polarization(exp)
    assert res.ok
    assert res.rmse_after < 2e-3
    assert res.params["anode.ocp"] == pytest.approx(-1.60, abs=0.01)
    assert res.params["cathode.asr"] == pytest.approx(3.0, rel=0.15)


def test_efficiency_fit_recovers_nde():
    d = Design()
    ps = build_params(d)
    exp = Experiment(name="Маса", area_cm2=20.0, mass_start_g=5.0, anode="az31")
    exp.measurements = [Measurement(0, 1.2, 0.2), Measurement(36000, 1.1, 0.2)]
    design = experiment_design(exp)
    from earthcharge.core.electrochem import CellModel
    from earthcharge.core.design import derive_geometry
    psd = build_params(design)
    cell = CellModel(design, psd, derive_geometry(design, psd.v("anode.density")))
    q = 0.2 * 36000
    total = q + cell.corrosion_current(0.2) * 36000 + cell.chunk_current(0.2) * 36000
    from earthcharge.core.constants import FARADAY
    exp.mass_end_g = 5.0 - total / (FARADAY * cell.anode.electrons_per_gram())
    res = calibrate_efficiency(exp)
    assert res.ok
    assert res.params["anode.k_nde"] == pytest.approx(ps.v("anode.k_nde"), rel=1e-6)


def test_passivation_fit():
    exp = Experiment(name="Пасивація", area_cm2=20.0, temperature_c=25.0)
    exp.measurements = [Measurement(t, 0.0, 0.2) for t in np.arange(0, 6 * 3600, 300.0)]
    true = {"anode.pass_asr_max": 6.0, "anode.pass_q_char": 150.0}
    v = predict_points(experiment_design(exp), exp, true)
    for m, vv in zip(exp.measurements, v):
        m.voltage_v = float(vv)
    res = calibrate_passivation(exp)
    assert res.ok
    assert res.rmse_after < 2e-3
    assert res.params["anode.pass_asr_max"] == pytest.approx(6.0, rel=0.1)


def test_graphite_experiment_cannot_calibrate_air_design():
    exp = Experiment(name="Графіт", construction="submerged", cathode="graphite", area_cm2=10.0)
    exp.id = 1
    from earthcharge.core.calibration import CalibrationResult
    res = CalibrationResult("polarization", True, params={"cathode.i0": 1e-3})
    d = Design()
    applied, refused = apply_calibration(d, exp, res)
    assert applied == []
    assert refused and "не збігається" in refused[0][1]
    assert d.overrides == {}


def test_calibration_applied_with_status():
    exp = Experiment(name="Повітря", construction="air", cathode="air_mno2", anode="az31")
    exp.id = 7
    from earthcharge.core.calibration import CalibrationResult
    d = Design()
    applied, refused = apply_calibration(d, exp, CalibrationResult("efficiency", True, params={"anode.k_nde": 0.4}))
    assert applied == ["anode.k_nde"]
    p = build_params(d).prop("anode.k_nde")
    assert p.value == pytest.approx(0.4)
    assert p.status.value == "calibrated"


def test_replay_matches_model_generated_data():
    exp = Experiment(name="Профіль", area_cm2=20.0, temperature_c=25.0)
    exp.measurements = [Measurement(t, 0.0, 0.1 if t < 1800 else 0.2) for t in np.arange(0, 3600, 60.0)]
    v = predict_points(experiment_design(exp), exp)
    for m, vv in zip(exp.measurements, v):
        m.voltage_v = float(vv)
    sim, comp = replay(exp)
    assert comp["rmse"] < 0.02
