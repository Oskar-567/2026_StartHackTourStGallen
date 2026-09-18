"""Shared inline fixtures for pure-engine tests.

No database, no Django test marks: these tests exercise `server/engine/`
only, as plain functions of plain data. Fixtures are small and inline on
purpose -- the task calls for not reading files from the challenge data pack
in tests, so everything here is a hand-built dict shaped like one raw event.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from engine.parsing import parse_event
from engine.types import AuthorizationEvent, EngineState

# A minimal, schema-valid raw event dict, closely modelled on
# data/scenario_fixtures/example_authorization_request.json from the
# challenge data pack (not copied from the pack itself -- typed by hand).
_BASE_RAW_EVENT: dict[str, Any] = {
    "type": "authorization.request",
    "request_id": "req_test_0001",
    "deadline_at": "2026-08-12T09:00:08Z",
    "authorization": {
        "authorization_id": "AU_TEST_0001",
        "source_authorization_id": "AU_TEST_0001",
        "scenario_id": "SCEN0000",
        "replay_order": 1,
        "mandate_id": "TM_TEST_0001",
        "profile_id": "PROFILE_TEST_0001",
        "card_id": "CA_TEST_0001",
        "initiator_type": "agent",
        "merchant": {
            "merchant_id": "ME_TEST_0001",
            "merchant_name": "Test Market",
            "merchant_category": "groceries",
            "merchant_mcc": "5411",
            "merchant_country": "CH",
            "merchant_city": "Zurich",
            "availability": "store_and_online",
            "recurring_capable": "false",
        },
        "timestamp": "2026-08-12T08:59:59Z",
        "amount": 20.0,
        "currency": "CHF",
        "billing_amount_chf": 20.0,
        "items_subtotal": 18.0,
        "delivery_fee": 2.0,
        "channel": "ecommerce",
        "customer_device_id": "DVC-TEST",
        "authority_status": "active",
        "card_status_at_attempt": "active",
        "spend_in_period_before_chf": None,
        "recent_attempt_count_10m": 0,
        "fulfillment_method": "delivery",
        "delivery_by": None,
        "order_returnable": "unknown",
        "order_cancellable": "unknown",
        "related_authorization_id": None,
        "related_authorization_status": None,
        "purchase_description": "Test grocery order",
        "items": [
            {
                "line_no": 1,
                "item_id": "IT_TEST_0001",
                "item_name": "Test grocery item",
                "item_category": "groceries",
                "quantity": 1,
                "unit_price": 18.0,
                "currency": "CHF",
                "item_details": "Synthetic test item",
            }
        ],
    },
    "mandate": {
        "mandate_id": "TM_TEST_0001",
        "status": "active",
        "customer_id": "CU_TEST_0001",
        "card_id": "CA_TEST_0001",
        "instruction": "Buy one ordinary grocery item for CHF 20 or less. Ask me when uncertain.",
        "hard_rules": [],
        "uncertainty_policy": "ask",
        "profile_id": "PROFILE_TEST_0001",
    },
    "context": {
        "approved_spend_in_period_chf": 0.0,
        "recent_authorizations": [],
    },
    "runtime": {
        "received_at": "2026-08-12T09:00:00Z",
        "history_window_minutes": 10,
        "context_basis": "run_decisions_and_scenario_timestamps",
    },
}


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def build_raw_event(
    *,
    authorization: dict[str, Any] | None = None,
    mandate: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    top_level: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A schema-valid raw event dict with the given sections shallow/deep-merged in."""
    raw = copy.deepcopy(_BASE_RAW_EVENT)
    if authorization:
        raw["authorization"] = _deep_merge(raw["authorization"], authorization)
    if mandate:
        raw["mandate"] = _deep_merge(raw["mandate"], mandate)
    if context:
        raw["context"] = _deep_merge(raw["context"], context)
    if runtime:
        raw["runtime"] = _deep_merge(raw["runtime"], runtime)
    if top_level:
        raw = _deep_merge(raw, top_level)
    return raw


def build_event(**kwargs: Any) -> AuthorizationEvent:
    """Build and parse a schema-valid event in one step."""
    return parse_event(build_raw_event(**kwargs))


@pytest.fixture
def base_raw_event() -> dict[str, Any]:
    return copy.deepcopy(_BASE_RAW_EVENT)


@pytest.fixture
def raw_event_factory():
    """A callable fixture: `raw_event_factory(authorization={...}, mandate={...}, ...)`."""
    return build_raw_event


@pytest.fixture
def event_factory():
    """A callable fixture: `event_factory(authorization={...}, ...) -> AuthorizationEvent`."""
    return build_event


@pytest.fixture
def empty_state() -> EngineState:
    return EngineState()
