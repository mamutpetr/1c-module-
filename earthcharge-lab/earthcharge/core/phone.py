"""Модель заряджання смартфона.

Профіль CC/CV (оціночна модель): до порогу cv_start телефон приймає максимальну потужність,
далі потужність заряду лінійно зменшується до taper_floor. Реальні профілі залежать від
конкретного телефона, контролера живлення та температури акумулятора.

Під час заряджання частина вхідної потужності йде на власне споживання телефона, решта —
в акумулятор з ККД заряджання. Якщо вхідної потужності менше за власне споживання,
акумулятор розряджається.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .design import PhoneConfig


@dataclass
class PhoneLedger:
    input_j: float = 0.0          # енергія на вході телефона (після кабелю)
    self_from_usb_j: float = 0.0
    self_from_batt_j: float = 0.0
    charge_loss_j: float = 0.0
    stored_j: float = 0.0          # енергія, що надійшла в акумулятор


class PhoneBattery:
    def __init__(self, cfg: PhoneConfig):
        self.cfg = cfg
        self.capacity_j = cfg.battery_wh() * 3600.0
        self.e_j = self.capacity_j * cfg.soc_start_pct / 100.0
        self.target_soc = cfg.soc_target_pct / 100.0
        self.eta = cfg.charge_efficiency_pct / 100.0
        self.p_self = cfg.self_consumption_w
        self.p_cc = max(0.0, (cfg.max_charge_power_w - cfg.self_consumption_w) * self.eta)
        self.done = False
        self.t_done_s: float | None = None
        self.charging = False
        self.ledger = PhoneLedger()
        self.initial_j = self.e_j

    @property
    def soc(self) -> float:
        return self.e_j / self.capacity_j if self.capacity_j > 0 else 0.0

    def battery_accept_w(self, soc: float | None = None) -> float:
        """Потужність, яку приймає акумулятор, Вт (профіль CC/CV)."""
        soc = self.soc if soc is None else soc
        cv = self.cfg.cv_start_pct / 100.0
        if soc < cv:
            return self.p_cc
        frac = (1.0 - soc) / (1.0 - cv) if cv < 1 else 0.0
        return self.p_cc * max(self.cfg.taper_floor_pct / 100.0, frac)

    def request_input_w(self, dt: float) -> float:
        """Потужність, яку телефон хоче взяти з USB (на вході телефона), Вт."""
        if self.done:
            return 0.0
        if self.eta <= 0:
            return 0.0
        headroom_w = max(0.0, self.capacity_j - self.e_j) / dt      # потужність у бік акумулятора
        accept = min(self.battery_accept_w(), headroom_w)
        return min(self.cfg.max_charge_power_w, self.p_self + accept / self.eta)

    def update(self, p_in: float, dt: float, t_end_s: float) -> None:
        lg = self.ledger
        if self.done:
            return
        lg.input_j += p_in * dt
        if p_in >= self.p_self:
            p_charge = p_in - self.p_self
            stored = self.eta * p_charge * dt
            lg.self_from_usb_j += self.p_self * dt
            lg.charge_loss_j += (1.0 - self.eta) * p_charge * dt
            lg.stored_j += stored
            self.e_j += stored
            self.charging = p_charge > 1e-6
        else:
            lg.self_from_usb_j += p_in * dt
            drain = (self.p_self - p_in) * dt
            drain = min(drain, self.e_j)
            lg.self_from_batt_j += drain
            self.e_j -= drain
            self.charging = False
        if self.soc >= self.target_soc - 1e-9:
            self.done = True
            self.t_done_s = t_end_s

    def energy_needed_wh(self) -> float:
        """Мінімальна енергія на вході телефона для досягнення цілі за max_time_h (без втрат генератора)."""
        cfg = self.cfg
        de = max(0.0, cfg.soc_target_pct - cfg.soc_start_pct) / 100.0 * cfg.battery_wh()
        return de / self.eta + cfg.self_consumption_w * self.min_charge_time_h()

    def min_charge_time_h(self) -> float:
        """Час заряджання при необмеженому джерелі (лише обмеження телефона), год."""
        cfg = self.cfg
        cap = cfg.battery_wh() * 3600.0
        s0, s1 = cfg.soc_start_pct / 100.0, cfg.soc_target_pct / 100.0
        cv = cfg.cv_start_pct / 100.0
        if self.p_cc <= 0:
            return math.inf
        t = 0.0
        if s0 < cv:
            t += (min(s1, cv) - s0) * cap / self.p_cc
        lo = max(s0, cv)
        if s1 > lo:
            n = 200
            ds = (s1 - lo) / n
            for k in range(n):
                s = lo + (k + 0.5) * ds
                t += ds * cap / self.battery_accept_w(s)
        return t / 3600.0


def usb_port_power_for_input(p_in: float, v_bus: float, r_cable: float) -> float:
    """Потужність на виході порту USB, потрібна, щоб телефон отримав p_in з урахуванням кабелю."""
    if p_in <= 0:
        return 0.0
    if r_cable <= 0:
        return p_in
    disc = 1.0 - 4.0 * r_cable * p_in / (v_bus * v_bus)
    if disc <= 0:
        return v_bus * v_bus / (2.0 * r_cable)
    return v_bus * v_bus / (2.0 * r_cable) * (1.0 - math.sqrt(disc))


def cable_loss_w(p_port: float, v_bus: float, r_cable: float) -> float:
    i = p_port / v_bus if v_bus > 0 else 0.0
    return i * i * r_cable
