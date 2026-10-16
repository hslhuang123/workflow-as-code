from __future__ import annotations

from examples.exchange.schemas import ConvertedAmount, ExchangeRate


_RATES = {
    ("USD", "EUR"): 0.92,
    ("EUR", "USD"): 1.09,
    ("USD", "JPY"): 149.5,
    ("JPY", "USD"): 0.0067,
}


def get_exchange_rate(from_currency: str, to_currency: str) -> ExchangeRate:
    pair = (from_currency.upper(), to_currency.upper())
    if pair not in _RATES:
        raise ValueError(f"unsupported exchange pair {pair[0]}->{pair[1]}")
    return ExchangeRate(
        from_currency=pair[0],
        to_currency=pair[1],
        rate=_RATES[pair],
    )


def convert_amount(amount: float, exchange_rate: ExchangeRate) -> ConvertedAmount:
    converted = round(amount * exchange_rate.rate, 2)
    return ConvertedAmount(
        original_amount=amount,
        converted_amount=converted,
        from_currency=exchange_rate.from_currency,
        to_currency=exchange_rate.to_currency,
        rate=exchange_rate.rate,
    )
