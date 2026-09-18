"""Tests for `engine.parsing.parse_event`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from engine.parsing import EventParsingError, parse_event


def test_parses_example_event_without_loss(base_raw_event):
    event = parse_event(base_raw_event)

    assert event.request_id == "req_test_0001"
    assert event.authorization_id == "AU_TEST_0001"
    assert event.merchant.merchant_id == "ME_TEST_0001"
    assert event.merchant.recurring_capable is False
    assert event.amount == Decimal("20.0")
    assert event.billing_amount_chf == Decimal("20.0")
    assert len(event.items) == 1
    assert event.items[0].item_id == "IT_TEST_0001"
    assert event.items[0].unit_price == Decimal("18.0")
    assert event.mandate.mandate_id == "TM_TEST_0001"
    assert event.mandate.uncertainty_policy == "ask"
    assert event.context.recent_authorizations == ()
    assert event.runtime.history_window_minutes == 10


def test_drops_scenario_id_and_replay_order(base_raw_event):
    """The engine must never be able to read scenario_id or replay_order.

    They are present on the raw event (as the live API sends them) but
    `AuthorizationEvent` has no field for either -- parsing them out is the
    boundary that makes it structurally impossible for a check to see them.
    """
    event = parse_event(base_raw_event)

    assert not hasattr(event, "scenario_id")
    assert not hasattr(event, "replay_order")
    # Confirm the underlying dataclass truly carries no such field, not just
    # that no attribute was set at runtime.
    field_names = set(event.__dataclass_fields__)
    assert "scenario_id" not in field_names
    assert "replay_order" not in field_names


def test_null_spend_in_period_stays_none_not_zero(base_raw_event):
    event = parse_event(base_raw_event)
    assert event.spend_in_period_before_chf is None


def test_unknown_order_terms_are_not_coerced(raw_event_factory):
    raw = raw_event_factory(
        authorization={"order_returnable": "unknown", "order_cancellable": "not_applicable"}
    )
    event = parse_event(raw)
    assert event.order_returnable == "unknown"
    assert event.order_cancellable == "not_applicable"
    # "unknown" and "not_applicable" must never collapse into each other or
    # into a boolean.
    assert event.order_returnable != event.order_cancellable


def test_null_related_authorization_fields_stay_none(raw_event_factory):
    raw = raw_event_factory(
        authorization={"related_authorization_id": None, "related_authorization_status": None}
    )
    event = parse_event(raw)
    assert event.related_authorization_id is None
    assert event.related_authorization_status is None


def test_missing_required_field_raises(raw_event_factory):
    raw = raw_event_factory()
    del raw["authorization"]["billing_amount_chf"]
    with pytest.raises(EventParsingError):
        parse_event(raw)


def test_wrong_type_raises(raw_event_factory):
    raw = raw_event_factory(authorization={"billing_amount_chf": "20.00"})
    with pytest.raises(EventParsingError):
        parse_event(raw)


def test_invalid_enum_value_raises(raw_event_factory):
    raw = raw_event_factory(authorization={"channel": "carrier_pigeon"})
    with pytest.raises(EventParsingError):
        parse_event(raw)


def test_hard_rule_value_cannot_be_boolean(raw_event_factory):
    raw = raw_event_factory(
        mandate={
            "hard_rules": [
                {"field": "authorization.billing_amount_chf", "operator": "<=", "value": True}
            ]
        }
    )
    with pytest.raises(EventParsingError):
        parse_event(raw)


def test_hard_rule_list_value_of_strings_parses(raw_event_factory):
    raw = raw_event_factory(
        mandate={
            "hard_rules": [
                {
                    "field": "authorization.items.item_category",
                    "operator": "not_in",
                    "value": ["cosmetics", "gift_card"],
                }
            ]
        }
    )
    event = parse_event(raw)
    assert event.mandate.hard_rules[0].value == ("cosmetics", "gift_card")
