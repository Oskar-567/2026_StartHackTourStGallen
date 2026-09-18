"""Small model-creation helpers shared across api tests (not pytest fixtures
themselves, so tests stay explicit about what data they set up).
"""

from django.utils import timezone

from api.models import AuthorizationRecord, Decision, Mandate, Run

PRICE_RULE = {
    "field": "authorization.billing_amount_chf",
    "operator": "<=",
    "value": 20,
    "currency": "CHF",
    "scope": "purchase",
}


def make_mandate(**overrides) -> Mandate:
    defaults = {
        "instruction": "Buy one ordinary grocery item for CHF 20 or less. Ask me when uncertain.",
        "hard_rules": [PRICE_RULE],
        "uncertainty_policy": Mandate.UncertaintyPolicy.ASK,
        "guidance": ["Familiar shop means one used in the last 90 days."],
        "open_questions": [],
        "status": Mandate.Status.ACTIVE,
        "draft_id": "draft-1",
        "mandate_id": "mandate-1",
    }
    defaults.update(overrides)
    return Mandate.objects.create(**defaults)


def make_run(mandate: Mandate | None = None, **overrides) -> Run:
    defaults = {
        "run_id": "run-1",
        "scenario_id": "SCEN0000",
        "mandate": mandate or make_mandate(),
        "status": Run.Status.RUNNING,
    }
    defaults.update(overrides)
    return Run.objects.create(**defaults)


def make_authorization(run: Run | None = None, **overrides) -> AuthorizationRecord:
    now = timezone.now()
    raw_event = {
        "type": "authorization.request",
        "authorization": {
            "authorization_id": "AU_LIVE_0001",
            "merchant": {"merchant_id": "ME1", "merchant_name": "Example Market"},
            "purchase_description": "Example grocery order",
            "items": [{"item_name": "Bread", "quantity": 1, "unit_price": 4.5}],
        },
    }
    defaults = {
        "run": run or make_run(),
        "authorization_id": "AU_LIVE_0001",
        "source_authorization_id": "AU0001",
        "raw_event": raw_event,
        "simulated_purchased_at": now,
        "deadline_at": now + timezone.timedelta(seconds=8),
        "received_at": now,
        "billing_amount_chf": "18.00",
    }
    defaults.update(overrides)
    return AuthorizationRecord.objects.create(**defaults)


def make_step_up_decision(authorization: AuthorizationRecord, **overrides) -> Decision:
    defaults = {
        "authorization": authorization,
        "decision": Decision.Value.STEP_UP,
        "reason_codes": ["customer_confirmation"],
        "customer_message": "Please review this purchase.",
        "is_final": False,
        "source": Decision.Source.ENGINE,
    }
    defaults.update(overrides)
    return Decision.objects.create(**defaults)
