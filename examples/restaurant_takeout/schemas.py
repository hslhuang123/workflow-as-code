from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TakeoutInput:
    customer_name: str
    items: list[str]


@dataclass(frozen=True)
class Order:
    id: str
    customer_name: str
    items: list[str]


@dataclass(frozen=True)
class MenuCheck:
    status: Literal["valid", "invalid"]
    unavailable_items: list[str]


@dataclass(frozen=True)
class OrderTotal:
    subtotal: float
    tax: float
    total: float


@dataclass(frozen=True)
class TakeoutResult:
    status: str
    message: str
    total: float
