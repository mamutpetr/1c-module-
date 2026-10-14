"""Походження кожного параметра моделі: довідкове значення, літературний діапазон,
оціночне припущення, значення користувача або результат калібрування."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Status(str, Enum):
    REFERENCE = "reference"
    LITERATURE = "literature"
    ASSUMPTION = "assumption"
    USER = "user"
    CALIBRATED = "calibrated"


STATUS_LABELS = {
    Status.REFERENCE: "Довідкове",
    Status.LITERATURE: "Літературний діапазон",
    Status.ASSUMPTION: "Оціночна модель",
    Status.USER: "Задано користувачем",
    Status.CALIBRATED: "Калібровано",
}

STATUS_HINTS = {
    Status.REFERENCE: "Фізична константа або довідкові дані.",
    Status.LITERATURE: "Типовий діапазон з літератури. Для конкретного матеріалу потрібна перевірка.",
    Status.ASSUMPTION: "Припущення для оціночної моделі, а не перевірений факт. Потрібне калібрування.",
    Status.USER: "Значення, введене користувачем.",
    Status.CALIBRATED: "Підібрано за експериментальними вимірюваннями.",
}


@dataclass(frozen=True)
class Prop:
    value: float
    unit: str
    status: Status
    label: str
    source: str = ""
    lo: float | None = None
    hi: float | None = None

    def with_value(self, value: float, status: Status, source: str) -> "Prop":
        return replace(self, value=float(value), status=status, source=source)

    @property
    def is_uncertain(self) -> bool:
        return self.status in (Status.ASSUMPTION, Status.LITERATURE)
