"""Tests for `engine.money`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from engine.money import UnknownCurrencyError, round_chf, to_chf


def test_chf_to_chf_is_identity():
    assert to_chf(Decimal("20.00"), "CHF") == Decimal("20.00")


def test_eur_conversion_uses_fixed_rate():
    # 100 EUR * 0.95 = 95.00 CHF
    assert to_chf(Decimal("100"), "EUR") == Decimal("95.00")


def test_usd_conversion_uses_fixed_rate():
    # 10 USD * 0.87 = 8.70 CHF
    assert to_chf(Decimal("10"), "USD") == Decimal("8.70")


def test_unknown_currency_raises():
    with pytest.raises(UnknownCurrencyError):
        to_chf(Decimal("10"), "JPY")


def test_round_chf_uses_half_even_rounding():
    # 0.005 rounds to 0.00 (nearest even) with ROUND_HALF_EVEN.
    assert round_chf(Decimal("0.005")) == Decimal("0.00")
    assert round_chf(Decimal("0.015")) == Decimal("0.02")
