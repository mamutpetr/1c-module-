"""Збирання ефективного набору параметрів моделі з бібліотеки матеріалів і перевизначень."""
from __future__ import annotations

from dataclasses import dataclass

from . import materials as M
from .design import Design
from .provenance import Prop, Status

GROUP_LABELS = {
    "anode": "Анод",
    "cathode": "Катод",
    "electrolyte": "Електроліт",
    "separator": "Сепаратор",
    "system": "Система / середовище",
}


@dataclass
class ParamSet:
    props: dict          # "group.name" -> Prop

    def v(self, key: str) -> float:
        return self.props[key].value

    def get(self, key: str, default: float) -> float:
        p = self.props.get(key)
        return default if p is None else p.value

    def prop(self, key: str) -> Prop:
        return self.props[key]

    def items(self):
        return self.props.items()


def library_props(design: Design) -> dict:
    props: dict = {}
    for k, p in M.ANODES[design.anode].props.items():
        props[f"anode.{k}"] = p
    for k, p in M.CATHODES[design.cathode].props.items():
        props[f"cathode.{k}"] = p
    for k, p in M.ELECTROLYTES[design.electrolyte].props.items():
        props[f"electrolyte.{k}"] = p
    for k, p in M.SEPARATORS[design.separator].props.items():
        props[f"separator.{k}"] = p
    for k, p in M.SYSTEM_PROPS.items():
        props[f"system.{k}"] = p
    return props


def build_params(design: Design) -> ParamSet:
    props = library_props(design)
    for key, ov in (design.overrides or {}).items():
        if key not in props or not isinstance(ov, dict) or "value" not in ov:
            continue
        status = Status(ov.get("status", Status.USER.value))
        props[key] = props[key].with_value(float(ov["value"]), status, ov.get("source", ""))
    return ParamSet(props)


def set_override(design: Design, key: str, value: float, status: Status = Status.USER, source: str = "") -> None:
    design.overrides[key] = {"value": float(value), "status": status.value, "source": source}


def clear_override(design: Design, key: str) -> None:
    design.overrides.pop(key, None)


def overrides_for_category(design: Design) -> dict:
    """Перевизначення прив'язані до поточних матеріалів; при зміні матеріалу їх варто скинути."""
    return dict(design.overrides)


def uncertain_keys(ps: ParamSet) -> list[str]:
    return [k for k, p in ps.items() if p.status in (Status.ASSUMPTION, Status.LITERATURE)]
