"""A purpose the customer stated once, asked about the second time.

The failure this guards against is quiet: an agent proposes six pairs of shoes,
each within budget, each the right size, none of them wrong on its own -- and
the customer ends up with six pairs. No per-purchase rule catches that.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from engine.checks import fulfilment
from engine.types import ApprovedPurchase, EngineState, Verdict

_SHOES_ONCE = {
    "purpose": "replacement road-running shoes",
    "allowed_item_categories": ["sporting_goods"],
    "fulfilment": "single",
}
_GROCERIES_REPEATED = {
    "purpose": "household groceries",
    "allowed_item_categories": ["groceries"],
    "fulfilment": "recurring",
}


def _approved(category: str, description: str = "Earlier purchase") -> ApprovedPurchase:
    return ApprovedPurchase(
        authorization_id="AU_EARLIER",
        timestamp=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        merchant_id="ME_TEST_0001",
        merchant_name="Test Market",
        merchant_country="CH",
        device_id="DVC-TEST",
        billing_amount_chf=Decimal("120.00"),
        purchase_description=description,
        item_categories=(category,),
    )


def _state(*approved: ApprovedPurchase) -> EngineState:
    return EngineState(recent_approved_purchases=approved)


def _shoes(event_factory, **mandate):
    return event_factory(
        authorization={
            "items": [
                {
                    "line_no": 1,
                    "item_id": "IT_1",
                    "item_name": "Road-running shoes",
                    "item_category": "sporting_goods",
                    "quantity": 1,
                    "unit_price": 150.0,
                    "currency": "CHF",
                    "item_details": "size 43",
                }
            ]
        },
        mandate=mandate,
    )


def test_a_second_purchase_for_a_one_off_purpose_asks(event_factory) -> None:
    event = _shoes(event_factory, intent_spec=_SHOES_ONCE)
    result = fulfilment.check(event, _state(_approved("sporting_goods", "Road-running shoes")))
    assert result.verdict is Verdict.UNCERTAIN
    assert result.evidence, "the customer must be told which purchase already covered this"


def test_it_asks_rather_than_declines(event_factory) -> None:
    """The system knows they have one; it does not know they don't want another."""
    event = _shoes(event_factory, intent_spec=_SHOES_ONCE)
    result = fulfilment.check(event, _state(_approved("sporting_goods")))
    assert result.verdict is not Verdict.FAIL


def test_the_first_purchase_passes(event_factory) -> None:
    event = _shoes(event_factory, intent_spec=_SHOES_ONCE)
    assert fulfilment.check(event, EngineState()).verdict is Verdict.PASS


def test_a_recurring_purpose_never_asks(event_factory) -> None:
    """Weekly groceries must not be interrupted every week."""
    event = event_factory(mandate={"intent_spec": _GROCERIES_REPEATED})
    result = fulfilment.check(event, _state(_approved("groceries"), _approved("groceries")))
    assert result.verdict is Verdict.PASS


def test_an_unstated_fulfilment_stays_silent(event_factory) -> None:
    """With nobody having established one-off or recurring, inventing one is worse."""
    event = _shoes(
        event_factory,
        intent_spec={"purpose": "shoes", "allowed_item_categories": ["sporting_goods"]},
    )
    assert fulfilment.check(event, _state(_approved("sporting_goods"))).verdict is Verdict.PASS


def test_an_unrelated_earlier_purchase_does_not_count(event_factory) -> None:
    event = _shoes(event_factory, intent_spec=_SHOES_ONCE)
    assert fulfilment.check(event, _state(_approved("groceries"))).verdict is Verdict.PASS


def test_a_purchase_outside_the_purpose_is_left_to_purpose_fit(event_factory) -> None:
    """This check is about "already got it", not about what is in the basket."""
    event = event_factory(
        authorization={
            "items": [
                {
                    "line_no": 1,
                    "item_id": "IT_1",
                    "item_name": "Shampoo",
                    "item_category": "cosmetics",
                    "quantity": 1,
                    "unit_price": 9.0,
                    "currency": "CHF",
                    "item_details": "",
                }
            ]
        },
        mandate={"intent_spec": _SHOES_ONCE},
    )
    assert fulfilment.check(event, _state(_approved("sporting_goods"))).verdict is Verdict.PASS
