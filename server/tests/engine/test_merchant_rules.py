"""Rules about which kind of shop may be used, and what they do to familiarity.

"Buy only from a specialist sports retailer" is a rule on the merchant's
category. A shop outside it is declined with a code that says so; a shop inside
it needs no extra question just for being new.
"""

from __future__ import annotations

from engine import reasons
from engine.checks import amount, merchant
from engine.types import EngineState, Verdict

_SPORTS_ONLY = {
    "field": "authorization.merchant.merchant_category",
    "operator": "in",
    "value": ["sporting_goods"],
    "scope": "purchase",
}


def _shop(category: str) -> dict:
    return {"merchant": {"merchant_id": "ME_NEW", "merchant_category": category}}


def test_a_shop_outside_the_allowed_category_is_declined_as_such(event_factory) -> None:
    event = event_factory(
        authorization=_shop("sustainable_goods"), mandate={"hard_rules": [_SPORTS_ONLY]}
    )
    result = amount.check(event, EngineState())
    assert result.verdict is Verdict.FAIL
    assert result.reason_code == reasons.MERCHANT_NOT_PERMITTED


def test_a_spending_limit_breach_keeps_its_own_code(event_factory) -> None:
    event = event_factory(
        authorization={"billing_amount_chf": 50.0},
        mandate={
            "hard_rules": [
                {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20}
            ]
        },
    )
    assert amount.check(event, EngineState()).reason_code == reasons.AMOUNT_LIMIT_EXCEEDED


def test_a_new_shop_the_policy_vouches_for_passes(event_factory) -> None:
    event = event_factory(
        authorization=_shop("sporting_goods"), mandate={"hard_rules": [_SPORTS_ONLY]}
    )
    assert merchant.check(event, EngineState()).verdict is Verdict.PASS


def test_a_new_shop_without_any_merchant_rule_is_still_a_question(event_factory) -> None:
    event = event_factory(authorization=_shop("sporting_goods"))
    result = merchant.check(event, EngineState())
    assert result.verdict is Verdict.UNCERTAIN
    assert result.reason_code == reasons.MERCHANT_UNFAMILIAR


def test_a_new_shop_failing_the_merchant_rule_is_not_vouched_for(event_factory) -> None:
    event = event_factory(
        authorization=_shop("sustainable_goods"), mandate={"hard_rules": [_SPORTS_ONLY]}
    )
    assert merchant.check(event, EngineState()).verdict is Verdict.UNCERTAIN
