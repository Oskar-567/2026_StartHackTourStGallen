"""Tests for the generic hard-rule interpreter (`engine.checks._hard_rule_engine`)
and the two check modules built on it (`engine.checks.amount`, `engine.checks.period`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from engine.checks import amount, period
from engine.checks._hard_rule_engine import evaluate_rule, resolve_field
from engine.types import ApprovedPurchase, EngineState, HardRule, Verdict


def _rule(**kwargs) -> HardRule:
    defaults = {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20}
    defaults.update(kwargs)
    return HardRule(**defaults)


# -- A rule that parses/resolves cleanly -------------------------------------


def test_resolve_known_purchase_field(event_factory):
    event = event_factory()
    assert resolve_field(event, "authorization.billing_amount_chf") == event.billing_amount_chf


def test_evaluate_rule_that_is_satisfied(event_factory):
    event = event_factory(authorization={"billing_amount_chf": 15.0, "amount": 15.0})
    satisfied, resolved, cause = evaluate_rule(event, _rule(value=20))
    assert satisfied is True
    assert cause is None
    assert resolved == Decimal("15.0")


def test_evaluate_rule_that_fails(event_factory):
    event = event_factory(authorization={"billing_amount_chf": 25.0})
    satisfied, _, cause = evaluate_rule(event, _rule(value=20))
    assert satisfied is False
    assert cause is None


def test_amount_check_passes_within_limit(event_factory, empty_state):
    event = event_factory(
        authorization={"billing_amount_chf": 15.0},
        mandate={
            "hard_rules": [
                {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20}
            ]
        },
    )
    result = amount.check(event, empty_state)
    assert result.verdict is Verdict.PASS


def test_amount_check_fails_over_limit(event_factory, empty_state):
    event = event_factory(
        authorization={"billing_amount_chf": 25.0},
        mandate={
            "hard_rules": [
                {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20}
            ]
        },
    )
    result = amount.check(event, empty_state)
    assert result.verdict is Verdict.FAIL
    assert result.evidence  # non-PASS must carry evidence


# -- A rule that does NOT parse/resolve --------------------------------------


def test_resolve_unknown_field_returns_uncertain(event_factory):
    event = event_factory()
    satisfied, resolved, cause = evaluate_rule(event, _rule(field="authorization.not_a_real_field"))
    assert satisfied is None
    assert cause == "unknown_field"


def test_amount_check_is_uncertain_for_unknown_field(event_factory, empty_state):
    event = event_factory(
        mandate={
            "hard_rules": [{"field": "authorization.made_up_field", "operator": "=", "value": "x"}]
        }
    )
    result = amount.check(event, empty_state)
    assert result.verdict is Verdict.UNCERTAIN
    assert result.evidence


# -- Missing information is never permission ----------------------------------


def test_null_actual_value_is_uncertain_not_pass(event_factory):
    """A null field must never be silently treated as satisfying a rule."""
    event = event_factory(authorization={"spend_in_period_before_chf": None})
    rule = _rule(field="authorization.spend_in_period_before_chf", operator="<=", value=100)
    satisfied, resolved, cause = evaluate_rule(event, rule)
    assert satisfied is None
    assert resolved is None
    assert cause == "missing_actual"


def test_unknown_value_is_uncertain_not_fail_for_equals(event_factory):
    """ "unknown" must never be coerced into a confirmed match for `=`."""
    event = event_factory(authorization={"order_returnable": "unknown"})
    rule = _rule(field="authorization.order_returnable", operator="=", value="true")
    satisfied, resolved, cause = evaluate_rule(event, rule)
    assert satisfied is None
    assert resolved == "unknown"
    assert cause == "unknown_value"


def test_unknown_value_is_uncertain_not_fail_for_not_equals(event_factory):
    """ "unknown" must never be coerced into a confirmed non-match for `!=` either."""
    event = event_factory(authorization={"order_returnable": "unknown"})
    rule = _rule(field="authorization.order_returnable", operator="!=", value="true")
    satisfied, resolved, cause = evaluate_rule(event, rule)
    assert satisfied is None
    assert resolved == "unknown"
    assert cause == "unknown_value"


def test_amount_check_uses_the_dedicated_unknown_value_reason_code(event_factory, empty_state):
    event = event_factory(
        authorization={"order_returnable": "unknown"},
        mandate={
            "hard_rules": [
                {"field": "authorization.order_returnable", "operator": "=", "value": "true"}
            ]
        },
    )
    result = amount.check(event, empty_state)
    assert result.verdict is Verdict.UNCERTAIN
    assert any("hard_rule_value_unknown" in e.note for e in result.evidence)


def test_not_applicable_is_distinct_from_unknown(event_factory):
    """ "not_applicable" is known, legitimate information -- not missing data."""
    event = event_factory(authorization={"order_returnable": "not_applicable"})

    # Ordinary string comparison applies: not_applicable != unknown is a
    # confident True, not UNCERTAIN.
    rule = _rule(field="authorization.order_returnable", operator="!=", value="unknown")
    satisfied, _, cause = evaluate_rule(event, rule)
    assert satisfied is True
    assert cause is None

    # A hard rule that strictly requires "true" is not satisfied by
    # not_applicable -- this is a definite FAIL, not UNCERTAIN, because the
    # merchant did supply an answer; it just isn't the one required.
    strict_rule = _rule(field="authorization.order_returnable", operator="=", value="true")
    satisfied2, _, cause2 = evaluate_rule(event, strict_rule)
    assert satisfied2 is False
    assert cause2 is None


# -- Period-scope aggregation --------------------------------------------------


def test_period_check_sums_recent_approved_purchases(event_factory):
    event = event_factory(
        authorization={
            "billing_amount_chf": 30.0,
            "timestamp": "2026-08-12T08:59:59Z",
        },
        mandate={
            "hard_rules": [
                {
                    "field": "authorization.billing_amount_chf",
                    "operator": "<=",
                    "value": 50,
                    "scope": "period",
                    "period_days": 7,
                }
            ]
        },
    )
    state = EngineState(
        recent_approved_purchases=(
            ApprovedPurchase(
                authorization_id="AU_PRIOR",
                timestamp=datetime(2026, 8, 10, tzinfo=UTC),
                merchant_id="ME_OTHER",
                merchant_name="Other Shop",
                merchant_country="CH",
                device_id="DVC-1",
                billing_amount_chf=Decimal("25.00"),
                purchase_description="prior purchase",
                item_categories=("groceries",),
            ),
        )
    )
    # 25 (prior, within 7 days) + 30 (this purchase) = 55 > 50 -> FAIL
    result = period.check(event, state)
    assert result.verdict is Verdict.FAIL


def test_period_check_ignores_purchases_outside_the_window(event_factory):
    event = event_factory(
        authorization={"billing_amount_chf": 30.0, "timestamp": "2026-08-12T08:59:59Z"},
        mandate={
            "hard_rules": [
                {
                    "field": "authorization.billing_amount_chf",
                    "operator": "<=",
                    "value": 50,
                    "scope": "period",
                    "period_days": 7,
                }
            ]
        },
    )
    state = EngineState(
        recent_approved_purchases=(
            ApprovedPurchase(
                authorization_id="AU_OLD",
                timestamp=datetime(2026, 7, 1, tzinfo=UTC),  # well outside 7 days
                merchant_id="ME_OTHER",
                merchant_name="Other Shop",
                merchant_country="CH",
                device_id="DVC-1",
                billing_amount_chf=Decimal("1000.00"),
                purchase_description="old purchase",
                item_categories=("groceries",),
            ),
        )
    )
    result = period.check(event, state)
    assert result.verdict is Verdict.PASS
