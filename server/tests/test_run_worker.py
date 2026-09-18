"""Worker idempotency: a repeated delivery of the same live `authorization_id`
must never run the engine twice or create a second engine `Decision`.

Exercises `Command._handle_envelope` directly (no long-poll loop, no real
network -- the external API is a `MagicMock`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from api import services
from api.management.commands.run_worker import Command
from api.models import AuthorizationRecord, Decision
from tests.factories import make_mandate, make_run


def _envelope(run_id: str, authorization_id: str, deadline_at: str) -> dict:
    return {
        "run_id": run_id,
        "event_id": "evt-1",
        "type": "authorization.request",
        "authorization_id": authorization_id,
        "status": "pending",
        "occurred_at": "2026-08-10T12:00:00Z",
        "data": {
            "type": "authorization.request",
            "request_id": f"req-{authorization_id}",
            "deadline_at": deadline_at,
            "authorization": {
                "authorization_id": authorization_id,
                "source_authorization_id": "AU0001",
                "scenario_id": "SCEN0000",
                "replay_order": 1,
                "mandate_id": "TM1",
                "profile_id": "PROFILE1",
                "card_id": "CA0001",
                "merchant": {
                    "merchant_id": "ME0001",
                    "merchant_name": "Alpine Basket",
                    "merchant_category": "groceries",
                    "merchant_mcc": "5411",
                    "merchant_country": "CH",
                    "merchant_city": "Zurich",
                    "availability": "store_and_online",
                    "recurring_capable": "false",
                },
                "timestamp": "2026-08-10T11:59:00Z",
                "amount": 15.0,
                "currency": "CHF",
                "billing_amount_chf": 15.0,
                "items_subtotal": 15.0,
                "delivery_fee": 0.0,
                "channel": "ecommerce",
                "customer_device_id": "DVC-1",
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
                "purchase_description": "Grocery order",
                "items": [
                    {
                        "line_no": 1,
                        "item_id": "IT0001",
                        "item_name": "Fresh produce",
                        "item_category": "groceries",
                        "quantity": 1,
                        "unit_price": 15.0,
                        "currency": "CHF",
                        "item_details": "basket",
                    }
                ],
            },
            "mandate": {
                "mandate_id": "TM1",
                "status": "active",
                "customer_id": "CU0001",
                "card_id": "CA0001",
                "instruction": "Buy groceries under CHF 20.",
                "hard_rules": [
                    {
                        "field": "authorization.billing_amount_chf",
                        "operator": "<=",
                        "value": 20,
                        "currency": "CHF",
                        "scope": "purchase",
                    }
                ],
                "uncertainty_policy": "ask",
                "profile_id": "PROFILE1",
            },
            "context": {"approved_spend_in_period_chf": None, "recent_authorizations": []},
            "runtime": {
                "received_at": deadline_at,
                "history_window_minutes": 10,
                "context_basis": "run_decisions_and_scenario_timestamps",
            },
        },
    }


@pytest.mark.django_db
def test_handle_envelope_is_idempotent_on_repeated_delivery(monkeypatch):
    # No network for the historical-familiarity lookup build_engine_state does.
    monkeypatch.setattr(services, "_history_rows_cache", [])

    mandate = make_mandate(mandate_id="TM1", status="active")
    run = make_run(mandate=mandate, run_id="run-idem")

    # Comfortably inside the deadline so the watchdog does not short-circuit.
    deadline_at = (datetime.now(UTC) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    envelope = _envelope(run.run_id, "AU_LIVE_1", deadline_at)

    client = MagicMock()
    client.submit_decision.return_value = {"status": "accepted"}

    command = Command()
    command._handle_envelope(client, envelope)

    assert AuthorizationRecord.objects.filter(run=run).count() == 1
    assert Decision.objects.filter(source=Decision.Source.ENGINE).count() == 1
    assert client.submit_decision.call_count == 1

    # Repeated delivery of the same live authorization_id: the engine must not
    # be asked to decide a second time.
    command._handle_envelope(client, envelope)

    assert AuthorizationRecord.objects.filter(run=run).count() == 1
    assert Decision.objects.filter(source=Decision.Source.ENGINE).count() == 1
    # Reconciliation re-affirms the decision already on file to the external
    # API (a second submit call), but never re-runs the engine.
    assert client.submit_decision.call_count == 2


@pytest.mark.django_db
def test_watchdog_submits_deterministic_only_decision_when_margin_is_tight(monkeypatch):
    monkeypatch.setattr(services, "_history_rows_cache", [])

    mandate = make_mandate(mandate_id="TM1", status="active")
    run = make_run(mandate=mandate, run_id="run-watchdog")

    # Past the watchdog's safety margin (but still technically in the future
    # so parse_event's deadline_at is a valid timestamp).
    deadline_at = (
        (datetime.now(UTC) + timedelta(milliseconds=500)).isoformat().replace("+00:00", "Z")
    )
    envelope = _envelope(run.run_id, "AU_LIVE_TIGHT", deadline_at)

    client = MagicMock()
    client.submit_decision.return_value = {"status": "accepted"}

    command = Command()
    command._handle_envelope(client, envelope)

    decision = Decision.objects.get(source=Decision.Source.ENGINE)
    # The deterministic-only fallback still returns a valid decision value.
    assert decision.decision in {
        Decision.Value.APPROVE,
        Decision.Value.DECLINE,
        Decision.Value.STEP_UP,
    }
    assert client.submit_decision.call_count == 1
