from __future__ import annotations

from examples.test_workflow.schemas import ConvertedAmount, ExchangeRate, Ticket


def make_ticket(message: str) -> Ticket:
    return Ticket(
        id="test_ticket_001",
        customer_id="test_customer_001",
        subject="Test workflow ticket",
        body=message,
        priority="normal",
    )


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
    return ConvertedAmount(
        original_amount=amount,
        converted_amount=round(amount * exchange_rate.rate, 2),
        from_currency=exchange_rate.from_currency,
        to_currency=exchange_rate.to_currency,
        rate=exchange_rate.rate,
    )
