"""Опис конструкції генератора та сценарію симуляції (лише дані, без фізики)."""
from __future__ import annotations

import copy
import dataclasses
import math
import typing
from dataclasses import dataclass, field

from . import materials as M
from .units import cm2_from_mm, cm3_from_mm, wh_from_mah

CATHODE_THICKNESS_MM = 1.0  # для оцінки габаритів і поверхні тепловіддачі


@dataclass
class Geometry:
    plate_length_mm: float = 100.0
    plate_width_mm: float = 60.0
    plate_thickness_mm: float = 1.2
    mass_mode: str = "thickness"          # "thickness" — задано товщину; "mass" — задано загальну масу Mg
    target_total_mass_g: float = 40.0
    faces: int = 2                        # 1 — катод з одного боку, 2 — з обох боків анода
    active_fraction: float = 0.85         # частка площі пластини, відкрита електроліту
    area_override_cm2: float = 0.0        # > 0 — активна площа анода задана вручну (на комірку)
    cathode_area_ratio: float = 1.0       # площа катода / площа анода
    gap_mm: float = 3.0                   # відстань анод — катод
    electrolyte_volume_ml: float = 70.0   # на комірку
    max_utilization: float = 0.85         # частка маси пластини, яку можна розчинити до перфорації
    contact_resistance_mohm: float = 8.0  # на комірку (контакти, струмовідводи)


@dataclass
class StackConfig:
    connection: str = "series"            # "series" | "parallel" | "mixed"
    n_cells: int = 3
    n_series: int = 3                     # лише для "mixed"
    n_parallel: int = 1                   # лише для "mixed"
    wiring_resistance_mohm: float = 15.0
    shared_electrolyte: bool = False      # спільна ванна: шунтувальні струми при послідовному з'єднанні
    shunt_path_mm: float = 20.0
    shunt_cross_section_cm2: float = 1.0


@dataclass
class ConverterConfig:
    enabled: bool = True
    control: str = "mppt"                 # "mppt" — регулювання вхідної напруги; "simple" — простий boost з UVLO
    efficiency_pct: float = 88.0
    quiescent_mw: float = 25.0
    v_in_min: float = 0.9
    i_in_max_a: float = 6.0
    input_resistance_mohm: float = 30.0
    v_out: float = 5.0
    p_out_max_w: float = 4.0             # обмеження вихідної потужності USB-C


@dataclass
class SupercapConfig:
    enabled: bool = False
    start_delay_s: float = 30.0           # SmartBoost: USB-C вмикається через цей час
    capacitance_f: float = 25.0
    v_max: float = 5.0
    v_min: float = 1.0
    v_initial: float = 0.0
    esr_mohm: float = 40.0
    leakage_ua: float = 50.0              # при номінальній напрузі
    eta_charge_pct: float = 95.0
    eta_discharge_pct: float = 95.0
    i_max_a: float = 5.0
    p_charge_max_w: float = 10.0
    p_discharge_max_w: float = 15.0
    # Керування після стартового імпульсу: USB-C обмежується згладженою потужністю рушія,
    # частина якої йде на підзаряд конденсатора, а конденсатор покриває короткі провали.
    smoothing_tau_s: float = 60.0
    recharge_share_pct: float = 10.0
    soc_target_pct: float = 80.0


@dataclass
class Environment:
    ambient_c: float = 25.0
    relative_humidity_pct: float = 50.0
    air_access: str = "open"              # "open" — катоди відкриті; "vents" — доступ через отвори корпусу
    vent_area_cm2: float = 6.0
    vent_length_mm: float = 3.0
    enclosure_free_volume_ml: float = 200.0
    air_exchange_per_h: float = 900.0     # кратність повітрообміну вільного об'єму, 1/год
    heat_area_override_cm2: float = 0.0
    thermal_model: bool = True


@dataclass
class Disturbances:
    enabled: bool = False
    mean_interval_s: float = 900.0
    duration_s: float = 20.0
    depth_pct: float = 50.0               # частка активної площі, заблокованої бульбашками/повітрям
    seed: int = 7


@dataclass
class Design:
    name: str = "Варіант A"
    anode: str = M.DEFAULT_ANODE
    cathode: str = M.DEFAULT_CATHODE
    electrolyte: str = M.DEFAULT_ELECTROLYTE
    separator: str = M.DEFAULT_SEPARATOR
    geometry: Geometry = field(default_factory=Geometry)
    stack: StackConfig = field(default_factory=StackConfig)
    converter: ConverterConfig = field(default_factory=ConverterConfig)
    supercap: SupercapConfig = field(default_factory=SupercapConfig)
    environment: Environment = field(default_factory=Environment)
    disturbances: Disturbances = field(default_factory=Disturbances)
    # Перевизначення параметрів моделі: "anode.k_nde" -> {"value": .., "status": "calibrated"|"user", "source": ..}
    overrides: dict = field(default_factory=dict)


@dataclass
class PhoneConfig:
    spec_mode: str = "mah"                # "mah" | "wh"
    capacity_mah: float = 5000.0
    nominal_v: float = 3.85
    energy_wh: float = 19.25
    soc_start_pct: float = 20.0
    soc_target_pct: float = 100.0
    max_charge_power_w: float = 5.0       # максимальна потужність, яку телефон бере з USB
    charge_efficiency_pct: float = 90.0   # USB -> енергія в акумуляторі
    self_consumption_w: float = 0.15      # власне споживання телефона під час заряджання
    cv_start_pct: float = 85.0            # початок фази постійної напруги (зниження потужності)
    taper_floor_pct: float = 20.0         # мінімальна потужність наприкінці, % від максимальної
    min_input_w: float = 0.5              # нижче цього телефон не заряджається
    cable_resistance_mohm: float = 150.0
    max_time_h: float = 7.0

    def battery_wh(self) -> float:
        return wh_from_mah(self.capacity_mah, self.nominal_v) if self.spec_mode == "mah" else self.energy_wh


LOAD_MODES = {
    "phone": "Смартфон (профіль заряджання)",
    "usb_power": "Постійна потужність USB-C",
    "mppt": "Максимальна потужність (MPPT)",
    "resistor": "Резистор на виводах батареї комірок",
    "current": "Постійний струм батареї комірок",
    "open": "Без навантаження (лише корозія)",
}


@dataclass
class SimSettings:
    load_mode: str = "phone"
    usb_power_w: float = 3.0
    resistor_ohm: float = 1.5
    current_a: float = 1.0
    duration_h: float = 7.0
    dt_s: float = 2.0
    stop_when_phone_done: bool = False


@dataclass
class Scenario:
    design: Design = field(default_factory=Design)
    phone: PhoneConfig = field(default_factory=PhoneConfig)
    sim: SimSettings = field(default_factory=SimSettings)
    notes: str = ""


# ---------------------------------------------------------------------------
# Похідна геометрія
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DerivedGeometry:
    n_series: int
    n_parallel: int
    n_cells: int
    plate_area_cm2: float          # одна сторона пластини
    anode_area_cm2: float          # активна площа анода на комірку
    cathode_area_cm2: float        # активна площа катода на комірку
    thickness_mm: float            # фактична товщина (з урахуванням режиму маси)
    plate_volume_cm3: float
    mass_per_cell_g: float
    total_mass_g: float
    usable_mass_per_cell_g: float
    density_g_cm3: float
    stack_height_mm: float
    heat_area_cm2: float
    electrolyte_total_ml: float


def stack_counts(stack: StackConfig) -> tuple[int, int]:
    if stack.connection == "series":
        return max(1, int(stack.n_cells)), 1
    if stack.connection == "parallel":
        return 1, max(1, int(stack.n_cells))
    return max(1, int(stack.n_series)), max(1, int(stack.n_parallel))


def derive_geometry(design: Design, density_g_cm3: float) -> DerivedGeometry:
    g = design.geometry
    s, p = stack_counts(design.stack)
    n = s * p
    plate_area = cm2_from_mm(g.plate_length_mm, g.plate_width_mm)
    if g.area_override_cm2 and g.area_override_cm2 > 0:
        anode_area = g.area_override_cm2
    else:
        anode_area = plate_area * g.faces * g.active_fraction
    cathode_area = anode_area * g.cathode_area_ratio
    if g.mass_mode == "mass":
        per_cell = g.target_total_mass_g / n
        thickness = per_cell / (density_g_cm3 * plate_area) * 10.0 if plate_area > 0 else 0.0
    else:
        thickness = g.plate_thickness_mm
    volume = cm3_from_mm(g.plate_length_mm, g.plate_width_mm, thickness)
    mass_cell = volume * density_g_cm3
    pitch = thickness + g.faces * (g.gap_mm + CATHODE_THICKNESS_MM) + 2.0  # +2 мм рамка/повітряний канал
    stack_h = n * pitch
    if design.environment.heat_area_override_cm2 > 0:
        heat_area = design.environment.heat_area_override_cm2
    else:
        lw = plate_area
        box = 2 * lw + 2 * (g.plate_length_mm + g.plate_width_mm) / 10.0 * stack_h / 10.0
        # повітряні канали біля катодів теж віддають тепло (з меншою ефективністю)
        heat_area = box + 0.5 * cathode_area * n
    return DerivedGeometry(
        n_series=s, n_parallel=p, n_cells=n,
        plate_area_cm2=plate_area, anode_area_cm2=anode_area, cathode_area_cm2=cathode_area,
        thickness_mm=thickness, plate_volume_cm3=volume, mass_per_cell_g=mass_cell,
        total_mass_g=mass_cell * n, usable_mass_per_cell_g=mass_cell * g.max_utilization,
        density_g_cm3=density_g_cm3, stack_height_mm=stack_h, heat_area_cm2=heat_area,
        electrolyte_total_ml=g.electrolyte_volume_ml * n,
    )


# ---------------------------------------------------------------------------
# Перевірка введених даних
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    level: str      # "error" | "warning" | "info"
    message: str


def validate_design(design: Design) -> list[Issue]:
    out: list[Issue] = []
    g, st, env = design.geometry, design.stack, design.environment
    if design.anode not in M.ANODES:
        out.append(Issue("error", f"Невідомий матеріал анода: {design.anode}"))
    if design.cathode not in M.CATHODES:
        out.append(Issue("error", f"Невідомий тип катода: {design.cathode}"))
    if design.electrolyte not in M.ELECTROLYTES:
        out.append(Issue("error", f"Невідомий електроліт: {design.electrolyte}"))
    if design.separator not in M.SEPARATORS:
        out.append(Issue("error", f"Невідомий сепаратор: {design.separator}"))
    for name, value in (("Довжина пластини", g.plate_length_mm), ("Ширина пластини", g.plate_width_mm),
                        ("Відстань між електродами", g.gap_mm), ("Об'єм електроліту", g.electrolyte_volume_ml)):
        if not (value > 0):
            out.append(Issue("error", f"{name} має бути більшою за нуль."))
    if g.mass_mode == "thickness" and not (g.plate_thickness_mm > 0):
        out.append(Issue("error", "Товщина пластини має бути більшою за нуль."))
    if g.mass_mode == "mass" and not (g.target_total_mass_g > 0):
        out.append(Issue("error", "Загальна маса магнію має бути більшою за нуль."))
    if g.faces not in (1, 2):
        out.append(Issue("error", "Кількість робочих сторін анода: 1 або 2."))
    if not (0 < g.active_fraction <= 1):
        out.append(Issue("error", "Активна частка площі має бути в межах 0–100%."))
    if not (0 < g.max_utilization <= 1):
        out.append(Issue("error", "Допустиме використання пластини має бути в межах 0–100%."))
    if g.cathode_area_ratio <= 0:
        out.append(Issue("error", "Співвідношення площ катода й анода має бути більшим за нуль."))
    if g.contact_resistance_mohm < 0 or st.wiring_resistance_mohm < 0:
        out.append(Issue("error", "Опір контактів не може бути від'ємним."))
    s, p = stack_counts(st)
    if s * p > 64:
        out.append(Issue("error", "Забагато комірок (максимум 64)."))
    if 0 < g.gap_mm < 1.0:
        out.append(Issue("warning", "Зазор менше 1 мм: ризик короткого замикання шламом Mg(OH)₂ і бульбашками."))
    if g.gap_mm > 15:
        out.append(Issue("warning", "Зазор більше 15 мм: великий опір електроліту."))
    if g.mass_mode == "thickness" and 0 < g.plate_thickness_mm < 0.3:
        out.append(Issue("warning", "Пластина тонша за 0,3 мм швидко перфорується."))
    if design.anode in M.ANODES and M.ANODES[design.anode].warning:
        out.append(Issue("warning", M.ANODES[design.anode].warning))
    if design.cathode in M.CATHODES and M.CATHODES[design.cathode].warning:
        out.append(Issue("info", M.CATHODES[design.cathode].warning))
    if design.electrolyte in M.ELECTROLYTES:
        el = M.ELECTROLYTES[design.electrolyte]
        if el.warning:
            out.append(Issue("warning", el.warning))
        if env.ambient_c <= el.props["freezing"].value:
            out.append(Issue("error", f"Температура {env.ambient_c:.1f} °C нижча за точку замерзання електроліту "
                                      f"({el.props['freezing'].value:.1f} °C)."))
    if env.ambient_c > 60:
        out.append(Issue("warning", "Температура вище 60 °C: інтенсивне випаровування й корозія."))
    if s > 1 and st.shared_electrolyte:
        out.append(Issue("warning", "Послідовне з'єднання зі спільним електролітом: шунтувальні струми "
                                    "розряджають комірки без корисної роботи."))
    conv = design.converter
    if conv.enabled:
        if not (0 < conv.efficiency_pct <= 100):
            out.append(Issue("error", "ККД перетворювача має бути в межах 0–100%."))
        if conv.v_in_min <= 0:
            out.append(Issue("error", "Мінімальна вхідна напруга перетворювача має бути більшою за нуль."))
    sc = design.supercap
    if sc.enabled:
        if sc.capacitance_f <= 0 or sc.v_max <= 0:
            out.append(Issue("error", "Ємність і допустима напруга суперконденсатора мають бути більшими за нуль."))
        if sc.v_min >= sc.v_max:
            out.append(Issue("error", "Мінімальна напруга розряду суперконденсатора має бути меншою за допустиму."))
        if not (0 <= sc.start_delay_s <= 300):
            out.append(Issue("error", "Час запуску SmartBoost: від 0 до 300 с."))
        if not conv.enabled:
            out.append(Issue("warning", "SmartBoost працює лише з увімкненим перетворювачем (шина USB-C)."))
    return out


def validate_phone(phone: PhoneConfig) -> list[Issue]:
    out: list[Issue] = []
    if phone.battery_wh() <= 0:
        out.append(Issue("error", "Енергія акумулятора телефона має бути більшою за нуль."))
    if not (0 <= phone.soc_start_pct < phone.soc_target_pct <= 100):
        out.append(Issue("error", "Потрібно: 0 ≤ поточний заряд < бажаний заряд ≤ 100%."))
    if not (0 < phone.charge_efficiency_pct <= 100):
        out.append(Issue("error", "ККД заряджання телефона має бути в межах 0–100%."))
    if phone.max_charge_power_w <= phone.self_consumption_w:
        out.append(Issue("error", "Потужність заряджання має перевищувати власне споживання телефона."))
    if not (0 < phone.max_time_h <= 48):
        out.append(Issue("error", "Час заряджання: від 0 до 48 год."))
    if not (0 <= phone.cv_start_pct < 100):
        out.append(Issue("error", "Початок фази CV має бути в межах 0–99%."))
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)


# ---------------------------------------------------------------------------
# Серіалізація dataclass <-> dict (для JSON-сценаріїв)
# ---------------------------------------------------------------------------

def to_dict(obj) -> dict:
    return dataclasses.asdict(obj)


def from_dict(cls, data):
    """Створює dataclass зі словника: невідомі ключі ігноруються, відсутні беруться за замовчуванням."""
    if data is None:
        return cls()
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = hints.get(f.name)
        if dataclasses.is_dataclass(ftype):
            kwargs[f.name] = from_dict(ftype, value)
        elif ftype is float and value is not None:
            kwargs[f.name] = float(value)
        elif ftype is int and value is not None:
            kwargs[f.name] = int(value)
        elif ftype is bool:
            kwargs[f.name] = bool(value)
        elif ftype is dict:
            kwargs[f.name] = copy.deepcopy(value) if isinstance(value, dict) else {}
        else:
            kwargs[f.name] = value
    return cls(**kwargs)


def clone(obj):
    return copy.deepcopy(obj)


def finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
