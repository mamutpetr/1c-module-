"""SmartBoost: суперконденсатор на шині USB-C з окремим зарядним/розрядним DC/DC.

Суперконденсатор не створює енергії: він лише переносить її в часі.
Кожен крок точно зберігає баланс:

    енергія з шини = ΔE_конденсатора + втрати DC/DC + втрати на ESR + витік

Напругу оновлено за середньою точкою кроку, тому ½C(V+ΔV)² − ½CV² = I·dt·(V + ΔV/2)
виконується точно, і заряд починається навіть з нульової напруги.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .design import SupercapConfig


@dataclass
class CapLedger:
    bus_in_j: float = 0.0          # енергія, взята з шини на заряд
    bus_out_j: float = 0.0         # енергія, віддана в шину при розряді
    conv_loss_j: float = 0.0       # втрати зарядного/розрядного DC/DC
    esr_loss_j: float = 0.0
    leak_loss_j: float = 0.0
    initial_j: float = 0.0
    events: list = field(default_factory=list)


class Supercap:
    def __init__(self, cfg: SupercapConfig):
        self.cfg = cfg
        self.c = cfg.capacitance_f
        self.v_max = cfg.v_max
        self.v_min = max(0.0, min(cfg.v_min, cfg.v_max * 0.999))
        self.esr = cfg.esr_mohm / 1000.0
        self.r_leak = cfg.v_max / (cfg.leakage_ua * 1e-6) if cfg.leakage_ua > 0 else math.inf
        self.eta_c = cfg.eta_charge_pct / 100.0
        self.eta_d = cfg.eta_discharge_pct / 100.0
        self.i_max = cfg.i_max_a
        v0 = min(max(cfg.v_initial, 0.0), cfg.v_max)
        self.e = 0.5 * self.c * v0 * v0
        self.ledger = CapLedger(initial_j=self.e)

    # ------------------------------------------------------------- стан
    @property
    def v(self) -> float:
        return math.sqrt(max(2.0 * self.e / self.c, 0.0))

    @property
    def e_max(self) -> float:
        return 0.5 * self.c * self.v_max ** 2

    @property
    def e_min(self) -> float:
        return 0.5 * self.c * self.v_min ** 2

    @property
    def usable_j(self) -> float:
        """Енергія, яку ще можна забрати до мінімальної напруги розряду."""
        return max(0.0, self.e - self.e_min)

    @property
    def soc(self) -> float:
        span = self.e_max - self.e_min
        return min(1.0, max(0.0, (self.e - self.e_min) / span)) if span > 0 else 0.0

    # ------------------------------------------------------------- заряд
    def charge_request_bus_w(self, dt: float) -> float:
        room = self.e_max - self.e
        if room <= 1e-9 or self.eta_c <= 0:
            return 0.0
        v = self.v
        a = dt * dt / (2.0 * self.c)
        i_room = (-v * dt + math.sqrt((v * dt) ** 2 + 4.0 * a * room)) / (2.0 * a)
        i = min(self.i_max, i_room)
        p_t = i * (v + i * dt / (2.0 * self.c)) + i * i * self.esr
        return min(p_t / self.eta_c, self.cfg.p_charge_max_w)

    def charge(self, p_bus: float, dt: float) -> None:
        if p_bus <= 0:
            self._leak(dt)
            return
        p_t = p_bus * self.eta_c
        v = self.v
        a = self.esr + dt / (2.0 * self.c)
        i = (-v + math.sqrt(v * v + 4.0 * a * p_t)) / (2.0 * a)
        stored = i * dt * (v + i * dt / (2.0 * self.c))
        esr = i * i * self.esr * dt
        lg = self.ledger
        lg.bus_in_j += p_bus * dt
        lg.conv_loss_j += (p_bus - p_t) * dt
        lg.esr_loss_j += esr
        self.e += stored
        self._leak(dt)

    # ------------------------------------------------------------- розряд
    def _a_dis(self, dt: float) -> float:
        return self.esr + dt / (2.0 * self.c)

    def discharge_avail_bus_w(self, dt: float) -> float:
        v = self.v
        if v <= self.v_min or self.eta_d <= 0:
            return 0.0
        room = self.e - self.e_min
        b = dt * dt / (2.0 * self.c)
        disc = (v * dt) ** 2 - 4.0 * b * room
        i_room = (v * dt - math.sqrt(max(disc, 0.0))) / (2.0 * b)
        a = self._a_dis(dt)
        i_opt = v / (2.0 * a)
        i = min(self.i_max, i_room, i_opt)
        p_t = i * v - a * i * i
        return max(0.0, min(p_t * self.eta_d, self.cfg.p_discharge_max_w))

    def discharge(self, p_bus_needed: float, dt: float) -> float:
        """Повертає потужність, фактично віддану в шину, Вт."""
        p_bus = min(p_bus_needed, self.discharge_avail_bus_w(dt))
        if p_bus <= 0:
            self._leak(dt)
            return 0.0
        p_t = p_bus / self.eta_d
        v = self.v
        a = self._a_dis(dt)
        disc = v * v - 4.0 * a * p_t
        i = (v - math.sqrt(max(disc, 0.0))) / (2.0 * a)
        removed = i * dt * (v - i * dt / (2.0 * self.c))
        esr = i * i * self.esr * dt
        lg = self.ledger
        # removed − esr = p_t·dt (точно за побудовою)
        lg.bus_out_j += p_bus * dt
        lg.conv_loss_j += (p_t - p_bus) * dt
        lg.esr_loss_j += esr
        self.e -= removed
        self._leak(dt)
        return p_bus

    def idle(self, dt: float) -> None:
        self._leak(dt)

    def _leak(self, dt: float) -> None:
        if math.isinf(self.r_leak):
            return
        v = self.v
        loss = min(v * v / self.r_leak * dt, max(self.e, 0.0))
        self.e -= loss
        self.ledger.leak_loss_j += loss

    def balance_residual_j(self) -> float:
        """Залишок енергетичного балансу (має бути ≈ 0)."""
        lg = self.ledger
        return (lg.initial_j + lg.bus_in_j - lg.bus_out_j - lg.conv_loss_j - lg.esr_loss_j
                - lg.leak_loss_j - self.e)
