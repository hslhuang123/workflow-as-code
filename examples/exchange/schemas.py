from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeInput:
    amount: float
    from_currency: str
    to_currency: str


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
class ExchangeResult:
    original_amount: float
    converted_amount: float
    from_currency: str
    to_currency: str
    rate: float
    message: str
