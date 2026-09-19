"""Orchestration between the Django ORM, the engine, and the external challenge API.

Used by both `api/views.py` (customer-triggered mandate actions) and the
`run_worker` management command (the decision loop). `server/engine/` never
imports this module and never touches Django or the network; this module is
exactly the glue that assembles plain data for it and persists its answers.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from api.models import ApprovedSpend, AuthorizationRecord, Decision, Mandate, Run
from engine.types import ApprovedPurchase, EngineState
from engine.types import Decision as EngineDecision
from viseca.client import VisecaClient

# -- external client -------------------------------------------------------

_client: VisecaClient | None = None


def get_client() -> VisecaClient:
    """A single `VisecaClient` shared for the life of the process.

    Views and the worker call this instead of constructing their own client
    so connections are pooled and the bearer key is read from settings in
    exactly one place. Tests monkeypatch this function directly to avoid any
    network access.
    """
    global _client
    if _client is None:
        _client = VisecaClient(base_url=settings.VISECA_BASE_URL, api_key=settings.VISECA_API_KEY)
    return _client


class MandateStateError(Exception):
    """A mandate action was attempted from a state that does not allow it
    (e.g. confirming a mandate that is not a draft, or revoking one that is
    not active). Views map this to a clean 400.
    """


# -- event payload helpers --------------------------------------------------


def event_payload(raw_event: dict) -> dict:
    """Return the `authorization.request` event dict from a stored `raw_event`.

    The worker stores the full envelope as delivered (`{"run_id": ..., "data":
    {...event...}, ...}`); some test fixtures store the bare event dict
    directly (top-level `"authorization"`). Handle both shapes so callers
    never have to know which one they got.
    """
    data = raw_event.get("data")
    return data if isinstance(data, dict) else raw_event


#: How long the customer has to answer a step-up: the challenge API's default
#: human window (`/v1/bootstrap` -> `timeouts.human_timeout_seconds`), distinct
#: from `deadline_at`, the ~8s automated deadline.
HUMAN_WINDOW_SECONDS = 120

#: Run IDs created locally by `replay --seed-queue` to try the approval queue.
#: They never existed at the challenge API, so nothing about them is forwarded.
DEMO_RUN_PREFIX = "demo-"


def with_intent_spec(event: dict, run: Run) -> dict:
    """The event with the run's confirmed `intent_spec` attached to its mandate.

    The challenge API stores only `hard_rules` and `uncertainty_policy`; the
    semantic half of the customer's policy (purpose, required attributes, item
    type) lives in our own `Mandate` row. Without it the semantic checks have
    nothing to compare against and every purchase becomes a question.

    Returns a copy: the stored `raw_event` stays exactly what the API sent.
    """
    intent_spec = run.mandate.intent_spec
    if not intent_spec:
        return event
    return {**event, "mandate": {**event.get("mandate", {}), "intent_spec": intent_spec}}


def _authorization_payload(raw_event: dict) -> dict:
    return event_payload(raw_event).get("authorization", {}) or {}


# -- mandate lifecycle -------------------------------------------------------


def create_mandate_draft(
    *,
    instruction: str,
    hard_rules: list[dict],
    uncertainty_policy: str,
    guidance: list[str] | None = None,
    open_questions: list[str] | None = None,
    intent_spec: dict | None = None,
    client: VisecaClient | None = None,
) -> Mandate:
    """Create a draft against the external API from a structured policy and
    persist it locally as `draft`. Nothing is active yet -- the customer must
    still agree; see `confirm_mandate`.
    """
    client = client or get_client()
    payload = {
        "instruction": instruction,
        "hard_rules": hard_rules,
        "uncertainty_policy": uncertainty_policy,
        "guidance": guidance or [],
        "open_questions": open_questions or [],
    }
    response = client.create_mandate(payload)
    draft_id = (response or {}).get("draft_id", "")
    return Mandate.objects.create(
        instruction=instruction,
        hard_rules=hard_rules,
        uncertainty_policy=uncertainty_policy,
        guidance=guidance or [],
        open_questions=open_questions or [],
        intent_spec=intent_spec or {},
        draft_id=draft_id,
        status=Mandate.Status.DRAFT,
    )


def confirm_mandate(
    mandate: Mandate, *, confirmed_by: str = "", client: VisecaClient | None = None
) -> Mandate:
    """The customer agrees: confirm the draft with the external API and flip
    the local record to `active`, storing the returned `mandate_id`.
    """
    if mandate.status != Mandate.Status.DRAFT:
        raise MandateStateError(
            f"Only a draft mandate can be confirmed (status is {mandate.status!r})."
        )
    client = client or get_client()
    response = client.confirm_mandate(mandate.draft_id)
    mandate_id = (response or {}).get("mandate_id", "")
    mandate.status = Mandate.Status.ACTIVE
    mandate.mandate_id = mandate_id
    mandate.confirmed_by = confirmed_by
    mandate.confirmed_at = timezone.now()
    mandate.save(
        update_fields=["status", "mandate_id", "confirmed_by", "confirmed_at", "updated_at"]
    )
    return mandate


def tighten_mandate(
    mandate: Mandate,
    *,
    hard_rules: list[dict] | None = None,
    uncertainty_policy: str | None = None,
    guidance: list[str] | None = None,
    open_questions: list[str] | None = None,
    client: VisecaClient | None = None,
) -> Mandate:
    """Forward a `tighten` (additive-only) change to the external API's PATCH
    endpoint, then keep the local record in sync. Callers (the tighten
    serializer) are responsible for validating that the change only adds
    rules and only strengthens `uncertainty_policy`; this function still
    checks the mandate is active as a defensive backstop.
    """
    if mandate.status != Mandate.Status.ACTIVE:
        raise MandateStateError(
            f"Only an active mandate can be tightened (status is {mandate.status!r})."
        )
    patch_payload: dict = {}
    if hard_rules is not None:
        patch_payload["hard_rules"] = hard_rules
    if uncertainty_policy is not None:
        patch_payload["uncertainty_policy"] = uncertainty_policy
    if guidance is not None:
        patch_payload["guidance"] = guidance
    if open_questions is not None:
        patch_payload["open_questions"] = open_questions

    if patch_payload:
        client = client or get_client()
        client.patch_mandate(mandate.mandate_id, patch_payload)
        for field, value in patch_payload.items():
            setattr(mandate, field, value)
        mandate.save()
    return mandate


def revoke_mandate(mandate: Mandate, *, client: VisecaClient | None = None) -> Mandate:
    """Forward a `revoke` to the external API's DELETE endpoint, then mark the
    local record revoked."""
    if mandate.status != Mandate.Status.ACTIVE:
        raise MandateStateError(
            f"Only an active mandate can be revoked (status is {mandate.status!r})."
        )
    client = client or get_client()
    client.delete_mandate(mandate.mandate_id)
    mandate.status = Mandate.Status.REVOKED
    mandate.save(update_fields=["status", "updated_at"])
    return mandate


# -- historical familiarity (loaded once, cached in memory) -----------------

_history_rows_cache: list[dict[str, str]] | None = None


def _history_rows() -> list[dict[str, str]]:
    """Historical authorization rows from the challenge API's history CSV,
    fetched once per process and cached in memory (never per request).
    """
    global _history_rows_cache
    if _history_rows_cache is None:
        csv_text = get_client().authorization_history_csv()
        _history_rows_cache = list(csv.DictReader(io.StringIO(csv_text)))
    return _history_rows_cache


def familiarity_from_rows(
    rows: Iterable[Mapping[str, str]], card_id: str
) -> tuple[dict[str, int], dict[str, int]]:
    """(merchant_id -> count, customer_device_id -> count) of approved rows for
    `card_id`, counted from already-loaded authorization-history rows.

    Split out from `_historical_familiarity` so the offline replay command can
    reuse the exact same counting rule against the history CSV on disk. The two
    must agree: "a shop I use regularly" has to mean the same thing offline and
    in production, or the replay loop stops predicting what the worker will do.
    """
    merchant_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    if not card_id:
        return merchant_counts, device_counts
    for row in rows:
        if row.get("card_id") != card_id or row.get("status") != "approved":
            continue
        merchant_id = row.get("merchant_id") or ""
        if merchant_id:
            merchant_counts[merchant_id] = merchant_counts.get(merchant_id, 0) + 1
        device_id = row.get("customer_device_id") or ""
        if device_id:
            device_counts[device_id] = device_counts.get(device_id, 0) + 1
    return merchant_counts, device_counts


def _historical_familiarity(card_id: str) -> tuple[dict[str, int], dict[str, int]]:
    """Familiarity counts for `card_id` from the challenge API's history CSV."""
    return familiarity_from_rows(_history_rows(), card_id)


# -- engine state assembly ---------------------------------------------------


def _approved_purchase_from_record(record: AuthorizationRecord) -> ApprovedPurchase | None:
    auth = _authorization_payload(record.raw_event)
    if not auth:
        return None
    merchant = auth.get("merchant", {}) or {}
    items = auth.get("items", []) or []
    return ApprovedPurchase(
        authorization_id=record.authorization_id,
        timestamp=record.simulated_purchased_at,
        merchant_id=merchant.get("merchant_id", "") or "",
        merchant_name=merchant.get("merchant_name", "") or "",
        merchant_country=merchant.get("merchant_country", "") or "",
        device_id=auth.get("customer_device_id", "") or "",
        billing_amount_chf=record.billing_amount_chf,
        purchase_description=auth.get("purchase_description", "") or "",
        item_categories=tuple(
            item.get("item_category", "") for item in items if isinstance(item, dict)
        ),
    )


def build_engine_state(run: Run, authorization: AuthorizationRecord) -> EngineState:
    """Assemble the engine's `EngineState` from the ORM for one authorization.

    Everything here is windowed on the **simulated** clock
    (`AuthorizationRecord.simulated_purchased_at`), never the real clock:
    only purchases *earlier* than `authorization`'s own simulated timestamp
    can affect its decision, regardless of the order this server happened to
    receive them in.
    """
    auth_payload = _authorization_payload(authorization.raw_event)
    card_id = auth_payload.get("card_id", "") or ""

    seen_authorization_ids = frozenset(
        AuthorizationRecord.objects.filter(run=run)
        .exclude(pk=authorization.pk)
        .values_list("authorization_id", flat=True)
    )

    prior_approved = list(
        AuthorizationRecord.objects.filter(run=run, approved_spend__isnull=False)
        .exclude(pk=authorization.pk)
        .filter(simulated_purchased_at__lt=authorization.simulated_purchased_at)
        .order_by("simulated_purchased_at")
    )
    recent_approved_purchases = tuple(
        purchase
        for purchase in (_approved_purchase_from_record(record) for record in prior_approved)
        if purchase is not None
    )

    run_merchant_counts: dict[str, int] = {}
    run_device_counts: dict[str, int] = {}
    for purchase in recent_approved_purchases:
        if purchase.merchant_id:
            run_merchant_counts[purchase.merchant_id] = (
                run_merchant_counts.get(purchase.merchant_id, 0) + 1
            )
        if purchase.device_id:
            run_device_counts[purchase.device_id] = run_device_counts.get(purchase.device_id, 0) + 1

    known_merchant_ids, known_device_ids = _historical_familiarity(card_id)
    for merchant_id, count in run_merchant_counts.items():
        known_merchant_ids[merchant_id] = known_merchant_ids.get(merchant_id, 0) + count
    for device_id, count in run_device_counts.items():
        known_device_ids[device_id] = known_device_ids.get(device_id, 0) + count

    month_start = authorization.simulated_purchased_at.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    approved_spend_in_period_chf = (
        ApprovedSpend.objects.filter(
            mandate=run.mandate,
            simulated_purchased_at__gte=month_start,
            simulated_purchased_at__lt=authorization.simulated_purchased_at,
        )
        .exclude(authorization=authorization)
        .aggregate(total=Sum("amount_chf"))["total"]
    )

    return EngineState(
        approved_spend_in_period_chf=approved_spend_in_period_chf,
        seen_authorization_ids=seen_authorization_ids,
        known_merchant_ids=known_merchant_ids,
        known_device_ids=known_device_ids,
        recent_approved_purchases=recent_approved_purchases,
    )


# -- recording decisions ------------------------------------------------


def record_decision(
    authorization: AuthorizationRecord,
    decision: EngineDecision,
    *,
    client: VisecaClient | None = None,
) -> Decision:
    """Persist the engine's decision locally and push it to the external API.

    Idempotent: if this authorization already has an engine decision on file
    (e.g. a retried call on the same authorization), returns the existing
    row instead of submitting or recording a second one.
    """
    existing = (
        authorization.decisions.filter(source=Decision.Source.ENGINE)
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return existing

    client = client or get_client()
    payload = decision.to_api_payload()
    client.submit_decision(authorization.authorization_id, payload)

    record = Decision.objects.create(
        authorization=authorization,
        decision=decision.decision.value,
        reason_codes=payload["reason_codes"],
        evidence=payload["evidence"],
        customer_message=decision.customer_message,
        engine_version=decision.engine_version,
        is_final=decision.decision.value != Decision.Value.STEP_UP,
        source=Decision.Source.ENGINE,
    )
    if decision.decision.value == Decision.Value.APPROVE:
        ApprovedSpend.objects.get_or_create(
            authorization=authorization,
            defaults={
                "mandate": authorization.run.mandate,
                "amount_chf": authorization.billing_amount_chf,
                "simulated_purchased_at": authorization.simulated_purchased_at,
            },
        )
    return record


def forward_customer_resolution(
    decision: Decision, *, client: VisecaClient | None = None
) -> Decision:
    """Push an already-recorded customer resolution (`Decision.source ==
    customer`) to the external API's `/resolve` endpoint. Idempotent: does
    nothing if `forwarded_at` is already set.
    """
    if decision.forwarded_at is not None:
        return decision
    client = client or get_client()
    payload = {
        "decision": decision.decision,
        "customer_message": decision.customer_message,
        "evidence": decision.evidence,
    }
    client.resolve(decision.authorization.authorization_id, payload)
    decision.forwarded_at = timezone.now()
    decision.save(update_fields=["forwarded_at"])
    return decision


__all__ = [
    "MandateStateError",
    "build_engine_state",
    "confirm_mandate",
    "create_mandate_draft",
    "event_payload",
    "forward_customer_resolution",
    "get_client",
    "record_decision",
    "revoke_mandate",
    "tighten_mandate",
]
