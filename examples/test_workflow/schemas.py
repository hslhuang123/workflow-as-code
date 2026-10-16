from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TestInput:
    message: str
    amount: float
    from_currency: str
    to_currency: str


@dataclass(frozen=True)
class Ticket:
    id: str
    customer_id: str
    subject: str
    body: str
    priority: Literal["low", "normal", "high"]


@dataclass(frozen=True)
class Classification:
    category: Literal["refund", "bug", "billing", "how_to", "other"]
    confidence: float
    rationale: str

@dataclass(frozen=True)
class ExchangeRate:
    from_currency: str
    to_currency: str
    rate: float


@dataclass(frozen=True)
class ConvertedAmount:
    original_amount: float
    converted_amount: float
    from_currency: str
    to_currency: str
    rate: float


@dataclass(frozen=True)
class TestResult:
    category: str
    handled_by: str
    message: str
