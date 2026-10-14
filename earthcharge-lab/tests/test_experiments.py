"""База експериментів та імпорт CSV."""
import math

import pytest

from earthcharge.core.experiments import (Experiment, ExperimentDB, Measurement, apply_import, experiment_to_csv,
                                          parse_csv_bytes)

UA_CSV = """# площа електрода, см2: 25,5
# маса початкова, г: 3,210
# маса кінцева, г: 2,950
# примітки: тест AZ31 у 3,5% NaCl
час, хв;напруга, В;струм, мА;температура, °C
0;1,52;0;24,1
1;1,21;100;24,3
2;1,18;100;24,5
""".encode("cp1251")

EN_CSV = b"time,voltage,current\n0,1.6,0\n10,1.2,0.5\n20,1.15,0.5\n"


def test_parse_ukrainian_excel_csv():
    imp = parse_csv_bytes(UA_CSV)
    assert len(imp.measurements) == 3
    m = imp.measurements[1]
    assert m.t_s == pytest.approx(60.0)
    assert m.voltage_v == pytest.approx(1.21)
    assert m.current_a == pytest.approx(0.1)
    assert m.temperature_c == pytest.approx(24.3)
    assert imp.meta["area_cm2"] == pytest.approx(25.5)
    assert imp.meta["mass_start_g"] == pytest.approx(3.21)
    assert imp.meta["mass_end_g"] == pytest.approx(2.95)
    assert "AZ31" in imp.meta["notes"]


def test_parse_english_csv():
    imp = parse_csv_bytes(EN_CSV)
    assert [m.t_s for m in imp.measurements] == [0, 10, 20]
    assert imp.measurements[2].current_a == pytest.approx(0.5)


def test_parse_hms_time():
    imp = parse_csv_bytes("час;напруга;струм\n00:00:00;1,5;0,1\n00:01:30;1,4;0,1\n".encode("utf-8"))
    assert imp.measurements[1].t_s == pytest.approx(90.0)


def test_bad_csv_reports_error():
    with pytest.raises(ValueError):
        parse_csv_bytes(b"a;b\n1;2\n")


def test_metrics_faraday_efficiency():
    exp = Experiment(anode="mg_pure", area_cm2=10.0, mass_start_g=10.0, mass_end_g=10.0 - 0.4534 / 0.5)
    exp.measurements = [Measurement(0, 1.2, 1.0), Measurement(3600, 1.2, 1.0)]
    m = exp.metrics()
    assert m["charge_ah"] == pytest.approx(1.0)
    assert m["energy_wh"] == pytest.approx(1.2)
    assert m["anode_eff_pct"] == pytest.approx(50.0, rel=2e-3)


def test_db_roundtrip(tmp_path):
    db = ExperimentDB(tmp_path / "exp.db")
    exp = Experiment(name="Перший", construction="submerged", cathode="graphite", mass_start_g=5.0)
    apply_import(exp, parse_csv_bytes(UA_CSV))
    eid = db.save(exp)
    back = db.load(eid)
    assert back.name == "Перший"
    assert back.construction == "submerged"
    assert len(back.measurements) == 3
    assert back.area_cm2 == pytest.approx(25.5)
    back.notes = "змінено"
    db.save(back)
    assert db.load(eid).notes == "змінено"
    assert len(db.list()) == 1 and db.list()[0]["n_points"] == 3
    db.delete(eid)
    assert db.list() == []
    db.close()


def test_export_reimport_roundtrip():
    exp = Experiment(name="X", area_cm2=12.0, mass_start_g=2.0, mass_end_g=1.5)
    exp.measurements = [Measurement(0, 1.5, 0.0, 25.0), Measurement(60, 1.3, 0.05, math.nan)]
    text = experiment_to_csv(exp, excel_ua=True)
    imp = parse_csv_bytes(text.encode("utf-8"))
    assert imp.measurements[1].voltage_v == pytest.approx(1.3)
    assert imp.meta["area_cm2"] == pytest.approx(12.0)
    assert imp.meta["mass_end_g"] == pytest.approx(1.5)


def test_csv_restores_materials_and_construction():
    exp = Experiment(name="Графіт", construction="submerged", anode="mg_pure", cathode="graphite",
                     electrolyte="nacl_10", load_desc="резистор 100 Ом")
    exp.measurements = [Measurement(0, 1.5, 0.0), Measurement(60, 0.4, 0.002)]
    back = Experiment()
    apply_import(back, parse_csv_bytes(experiment_to_csv(exp).encode("utf-8")))
    assert (back.construction, back.anode, back.cathode, back.electrolyte) == ("submerged", "mg_pure", "graphite", "nacl_10")
    assert back.name == "Графіт" and back.load_desc == "резистор 100 Ом"
