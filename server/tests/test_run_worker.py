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
from engine.types import ExtractedFacts, ItemFacts
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


class _RecordingExtractor:
    """Returns fixed facts and remembers whether it was asked."""

    name = "test-extractor"

    def __init__(self, attributes: dict[str, str]) -> None:
        self.calls = 0
        self._attributes = attributes

    def extract(self, items):
        self.calls += 1
        return ExtractedFacts(
            items=tuple(
                ItemFacts(
                    line_no=item.line_no,
                    category="groceries",
                    category_verified=True,
                    attributes=self._attributes,
                )
                for item in items
            ),
            source=self.name,
        )


def _deadline_in(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


@pytest.mark.django_db
def test_worker_decides_with_the_local_intent_spec_and_extracted_facts(monkeypatch):
    """The API's mandate carries no intent_spec; the worker must add ours and read facts."""
    monkeypatch.setattr(services, "_history_rows_cache", [])
    mandate = make_mandate(
        mandate_id="TM1",
        status="active",
        intent_spec={
            "allowed_item_categories": ["groceries"],
            "required_attributes": {"size": "L"},
        },
    )
    run = make_run(mandate=mandate, run_id="run-facts")
    client = MagicMock()
    client.submit_decision.return_value = {"status": "accepted"}

    command = Command()
    command._extractor = _RecordingExtractor({"size": "S"})
    command._handle_envelope(client, _envelope(run.run_id, "AU_LIVE_FACTS", _deadline_in(120)))

    decision = Decision.objects.get(source=Decision.Source.ENGINE)
    assert command._extractor.calls == 1
    assert decision.decision == Decision.Value.DECLINE
    assert "item_match_attribute_mismatch" in decision.reason_codes


@pytest.mark.django_db
def test_worker_skips_extraction_when_it_could_not_finish_in_time(monkeypatch, settings):
    monkeypatch.setattr(services, "_history_rows_cache", [])
    settings.FACTS_TIMEOUT_SECONDS = 4
    run = make_run(mandate=make_mandate(mandate_id="TM1", status="active"), run_id="run-skip")
    client = MagicMock()
    client.submit_decision.return_value = {"status": "accepted"}

    command = Command()
    command._extractor = _RecordingExtractor({})
    # Past the watchdog margin, but short of watchdog margin + extraction timeout.
    command._handle_envelope(client, _envelope(run.run_id, "AU_LIVE_SKIP", _deadline_in(4)))

    assert command._extractor.calls == 0
    assert client.submit_decision.call_count == 1


@pytest.mark.django_db
def test_run_counts_as_finished_when_the_api_says_completed():
    """Shape as returned by the live API on 2026-09-19 for a completed SCEN0000 run."""
    run = make_run(mandate=make_mandate(mandate_id="TM1", status="active"), run_id="run-done")
    client = MagicMock()
    client.get_scenario_run.return_value = {
        "run_id": "run-done",
        "status": "completed",
        "counters": {
            "total_events": 1,
            "generated": 1,
            "remaining": 0,
            "pending": 0,
            "awaiting_customer": 0,
            "approved": 1,
        },
    }

    assert Command()._run_finished(client, run) is True
    run.refresh_from_db()
    assert run.status == "completed"
    assert run.event_counters["approved"] == 1


@pytest.mark.django_db
def test_run_is_not_finished_while_a_customer_answer_is_outstanding():
    run = make_run(mandate=make_mandate(mandate_id="TM1", status="active"), run_id="run-open")
    client = MagicMock()
    client.get_scenario_run.return_value = {
        "status": "running",
        "counters": {"total_events": 1, "remaining": 0, "pending": 0, "awaiting_customer": 1},
    }

    assert Command()._run_finished(client, run) is False


@pytest.mark.django_db
def test_worker_forwards_a_fresh_customer_answer_and_skips_an_expired_one():
    from django.utils import timezone

    from tests.factories import make_authorization

    fresh = make_authorization(authorization_id="AU_FRESH")
    stale = make_authorization(authorization_id="AU_STALE")
    Decision.objects.create(
        authorization=fresh, decision="approve", source=Decision.Source.CUSTOMER
    )
    old = Decision.objects.create(
        authorization=stale, decision="approve", source=Decision.Source.CUSTOMER
    )
    Decision.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(seconds=services.HUMAN_WINDOW_SECONDS + 10)
    )
    client = MagicMock()

    Command()._forward_pending_resolutions(client)

    forwarded = [call.args[0] for call in client.resolve.call_args_list]
    assert forwarded == ["AU_FRESH"]


@pytest.mark.django_db
def test_a_run_is_refused_when_the_mandate_belongs_to_another_scenario():
    from django.core.management import CommandError, call_command

    from api.reference_policies import REFERENCE_POLICIES

    monitor = make_mandate(
        instruction=REFERENCE_POLICIES["SCEN0004"]["instruction"], status="active"
    )
    with pytest.raises(CommandError, match="different instruction"):
        call_command("run_worker", "--scenario", "SCEN0003", "--mandate-id", str(monitor.pk))


@pytest.mark.django_db
def test_the_watchdog_never_approves_what_it_had_no_time_to_read(monkeypatch):
    """Tight deadline, policy requires a size: the answer is a question, not approval."""
    monkeypatch.setattr(services, "_history_rows_cache", [])
    mandate = make_mandate(
        mandate_id="TM1",
        status="active",
        intent_spec={
            "allowed_item_categories": ["groceries"],
            "required_attributes": {"size": "43"},
        },
    )
    run = make_run(mandate=mandate, run_id="run-watchdog-safe")
    client = MagicMock()
    client.submit_decision.return_value = {"status": "accepted"}

    command = Command()
    command._extractor = _RecordingExtractor({"size": "43"})
    command._handle_envelope(client, _envelope(run.run_id, "AU_TIGHT_SAFE", _deadline_in(0.5)))

    decision = Decision.objects.get(source=Decision.Source.ENGINE)
    assert command._extractor.calls == 0
    assert decision.decision != Decision.Value.APPROVE
