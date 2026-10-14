"""Фізичні константи та довідкові дані.

Тут лише перевірені величини (CODATA, IUPAC, довідкові таблиці термодинаміки).
Усі припущення моделі зберігаються окремо в materials.py зі статусом «Оціночна модель».
"""
from __future__ import annotations

import math

# --- Фундаментальні константи (CODATA 2018, точні або рекомендовані значення) ---
FARADAY = 96485.33212          # Кл/моль
GAS_CONSTANT = 8.314462618     # Дж/(моль·К)
T_ZERO_C = 273.15              # К
T_REF_K = 298.15               # К, стандартна температура 25 °C
P_ATM = 101325.0               # Па

# --- Молярні маси, г/моль (IUPAC) та валентність іонів, що утворюються при розчиненні ---
MOLAR_MASS = {
    "Mg": 24.305,
    "Al": 26.982,
    "Zn": 65.38,
    "Mn": 54.938,
    "Pb": 207.2,
    "Li": 6.94,
    "Ca": 40.078,
}
VALENCE = {"Mg": 2, "Al": 3, "Zn": 2, "Mn": 2, "Pb": 2, "Li": 1, "Ca": 2}

M_MG_OH2 = 58.319   # г/моль, Mg(OH)2
M_H2O = 18.015      # г/моль
M_H2 = 2.016        # г/моль
M_O2 = 31.998       # г/моль
N_ELECTRONS_MG = 2  # Mg -> Mg2+ + 2e-

# --- Термодинаміка при 298,15 К (стандартні таблиці NBS/CRC), Дж/моль ---
DGF_MG_OH2 = -833.5e3
DHF_MG_OH2 = -924.5e3
DGF_H2O_L = -237.14e3
DHF_H2O_L = -285.83e3

# Струмоутворювальна реакція: Mg + 1/2 O2 + H2O -> Mg(OH)2
DG_MG_AIR = DGF_MG_OH2 - DGF_H2O_L          # ≈ -596.4 кДж/моль
DH_MG_AIR = DHF_MG_OH2 - DHF_H2O_L          # ≈ -638.7 кДж/моль
E_REV_MG_AIR = -DG_MG_AIR / (N_ELECTRONS_MG * FARADAY)   # ≈ 3.09 В, оборотна напруга
E_TN_MG_AIR = -DH_MG_AIR / (N_ELECTRONS_MG * FARADAY)    # ≈ 3.31 В, термонейтральна напруга

# Самокорозія: Mg + 2 H2O -> Mg(OH)2 + H2
DH_MG_CORROSION = DHF_MG_OH2 - 2.0 * DHF_H2O_L          # ≈ -352.8 кДж/моль Mg

# --- Повітря та кисень ---
O2_FRACTION_AIR = 0.2095                 # мольна частка O2 у сухому повітрі
D_O2_AIR_25C = 2.09e-5                   # м²/с, дифузія O2 в повітрі (Marrero & Mason), T^1.75
D_O2_WATER_25C = 2.10e-9                 # м²/с, дифузія розчиненого O2 у воді при 25 °C
EA_D_O2_WATER = 17.0e3                   # Дж/моль, температурна залежність дифузії O2 у воді (наближення)

# Розчинність O2 у прісній воді, насиченій повітрям при 1 атм, мг/л (таблиці APHA)
O2_SOLUBILITY_TABLE_C = (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0)
O2_SOLUBILITY_TABLE_MG_L = (14.62, 12.77, 11.29, 10.08, 9.09, 8.26, 7.56, 6.95, 6.41)

# --- Теплофізика ---
CP_WATER = 4.18          # Дж/(г·К)
CP_MG = 1.02             # Дж/(г·К)
CP_NACL = 0.88           # Дж/(г·К)
LATENT_HEAT_WATER = 2442.0  # Дж/г при 25 °C
RHO_WATER = 0.997        # г/мл при 25 °C

# --- Перерахунки ---
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_YEAR = 365.25 * 86400.0


def kelvin(t_c: float) -> float:
    return t_c + T_ZERO_C


def molar_gas_volume_l(t_c: float = 25.0, p_pa: float = P_ATM) -> float:
    """Молярний об'єм ідеального газу, л/моль (24,47 л/моль при 25 °C і 1 атм)."""
    return GAS_CONSTANT * kelvin(t_c) / p_pa * 1000.0


def o2_concentration_air_mol_m3(t_c: float = 25.0) -> float:
    """Концентрація O2 у повітрі, моль/м³ (≈ 8,56 при 25 °C)."""
    return P_ATM * O2_FRACTION_AIR / (GAS_CONSTANT * kelvin(t_c))


def d_o2_air(t_c: float) -> float:
    return D_O2_AIR_25C * (kelvin(t_c) / T_REF_K) ** 1.75


def d_o2_water(t_c: float) -> float:
    return D_O2_WATER_25C * math.exp(-EA_D_O2_WATER / GAS_CONSTANT * (1.0 / kelvin(t_c) - 1.0 / T_REF_K))


def o2_solubility_water_mol_m3(t_c: float, salinity_factor: float = 1.0) -> float:
    """Концентрація розчиненого O2 у воді, насиченій повітрям, моль/м³."""
    tc = min(max(t_c, O2_SOLUBILITY_TABLE_C[0]), O2_SOLUBILITY_TABLE_C[-1])
    xs, ys = O2_SOLUBILITY_TABLE_C, O2_SOLUBILITY_TABLE_MG_L
    for k in range(len(xs) - 1):
        if xs[k] <= tc <= xs[k + 1]:
            frac = (tc - xs[k]) / (xs[k + 1] - xs[k])
            mg_l = ys[k] + frac * (ys[k + 1] - ys[k])
            break
    else:  # pragma: no cover
        mg_l = ys[-1]
    return mg_l / M_O2 * salinity_factor   # мг/л = г/м³ -> моль/м³


def saturation_vapor_pressure_kpa(t_c: float) -> float:
    """Тиск насиченої водяної пари, кПа (формула Магнуса, Alduchov & Eskridge 1996)."""
    return 0.61094 * math.exp(17.625 * t_c / (t_c + 243.04))


def arrhenius_factor(ea_j_mol: float, t_c: float, t_ref_c: float = 25.0) -> float:
    return math.exp(-ea_j_mol / GAS_CONSTANT * (1.0 / kelvin(t_c) - 1.0 / kelvin(t_ref_c)))


def e_her_vs_sce(ph: float, t_c: float = 25.0) -> float:
    """Рівноважний потенціал виділення водню відносно НКЕ (SCE = +0,241 В відносно СВЕ)."""
    nernst = GAS_CONSTANT * kelvin(t_c) * math.log(10.0) / FARADAY
    return -0.2415 - nernst * ph
