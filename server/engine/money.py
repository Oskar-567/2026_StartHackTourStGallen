"""CHF conversion helpers using the fixed rates from the challenge data dictionary.

Rates are synthetic and fixed (dated 2026-08-01, `synthetic_fixed` in the
data pack's `fx_rates.csv`) -- not live market rates. All conversions and
monetary totals use decimal half-even rounding to two places, per the data
dictionary's "Units and nulls" section.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from engine.types import Currency

FX_RATES_TO_CHF: dict[str, Decimal] = {
    "CHF": Decimal("1.000000"),
    "EUR": Decimal("0.950000"),
    "GBP": Decimal("1.120000"),
    "USD": Decimal("0.870000"),
}

TWO_PLACES = Decimal("0.01")


class UnknownCurrencyError(ValueError):
    """Raised when asked to convert a currency outside the fixed rate table."""


def round_chf(value: Decimal) -> Decimal:
    """Round a CHF amount to two decimal places using half-even rounding."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_EVEN)


def to_chf(amount: Decimal, currency: Currency | str) -> Decimal:
    """Convert `amount` (in `currency`) to CHF using the fixed rate table.

    Mirrors the data dictionary's rule: convert a purchase line as
    `unit_price * fx_rates[currency]`, and `billing_amount_chf = amount *
    fx_rates[currency]`, rounded to two decimal places with half-even
    rounding.
    """
    rate = FX_RATES_TO_CHF.get(currency)
    if rate is None:
        raise UnknownCurrencyError(f"no fixed rate for currency {currency!r}")
    return round_chf(amount * rate)
