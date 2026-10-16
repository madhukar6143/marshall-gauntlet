"""Trivial payments helpers."""


def to_cents(amount: float) -> int:
    return int(round(amount * 100))


def fee(amount_cents: int, rate: float = 0.029, fixed: int = 30) -> int:
    return int(round(amount_cents * rate)) + fixed
