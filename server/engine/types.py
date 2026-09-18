"""Typed structures for the decision engine.

Every structure here is a frozen dataclass (or a plain enum) and mirrors the
challenge's live-event JSON schema
(``data/schemas/authorization_event.schema.json`` in the challenge data pack)
or is plain data the caller supplies from outside the engine. Nothing in this
module performs I/O, talks to Django, or calls a network or model.

Deliberate omission: ``AuthorizationEvent`` does NOT carry ``scenario_id`` or
``replay_order``, even though both fields exist on the live event's
``authorization`` object. The challenge brief forbids deciding from scenario
identity or sequence position, so ``parsing.py`` drops them at the parsing
boundary and they never enter the engine's typed world at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Literal

Currency = Literal["CHF", "EUR", "GBP", "USD"]

# order_returnable / order_cancellable / related_authorization_status use these
# tri/four-state strings on purpose: "unknown" (not supplied) is never the same
# as "not_applicable" (does not apply to this fulfilment type), and neither may
# be coerced to a boolean. See CLAUDE.md / challenge data_dictionary.md.
TrileanStr = Literal["true", "false", "unknown", "not_applicable"]


class Verdict(Enum):
    """The outcome of a single check."""

    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"


class DecisionType(StrEnum):
    """The three outcomes the engine (and the challenge API) can return."""

    APPROVE = "approve"
    DECLINE = "decline"
    STEP_UP = "step_up"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One fact that justified a (non-PASS, usually) check result.

    ``value`` must be JSON-serialisable data (str, int, float, bool, None, or
    a tuple of such) -- it is rendered verbatim into ``Decision.to_api_payload``.
    """

    field: str
    value: object
    note: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The result of one check function.

    Every non-PASS result must carry at least one `Evidence` entry -- callers
    (see `aggregate.py`) rely on this to explain declines and step-ups.
    """

    verdict: Verdict
    reason_code: str | None
    message: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    """The engine's final answer for one purchase."""

    decision: DecisionType
    reason_codes: tuple[str, ...]
    customer_message: str
    evidence: tuple[Evidence, ...]
    engine_version: str

    def to_api_payload(self) -> dict[str, object]:
        """Render the shape the challenge API's decision endpoint accepts.

        `POST /v1/authorizations/{authorization_id}/decision` requires only
        `authorization_id` and `decision` in the request body; this package
        does not track `authorization_id` on `Decision` (it is a property of
        the event, not of the verdict), so the caller must add it to this
        dict before posting, e.g.::

            payload = decision.to_api_payload()
            payload["authorization_id"] = event.authorization_id
        """
        return {
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "customer_message": self.customer_message,
            "evidence": [
                {"field": e.field, "value": _jsonable(e.value), "note": e.note}
                for e in self.evidence
            ],
            "engine_version": self.engine_version,
        }


def _jsonable(value: object) -> object:
    """Coerce a value into something json.dumps can handle without loss.

    `Decimal` is the only type this engine puts into `Evidence.value` that
    is not already JSON-native; render it as a float for the API payload.
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class Merchant:
    """Mirrors the event schema's `authorization.merchant` object."""

    merchant_id: str
    merchant_name: str
    merchant_category: str
    merchant_mcc: str
    merchant_country: str
    merchant_city: str
    availability: Literal["online", "store", "store_and_online", "atm"]
    recurring_capable: bool


@dataclass(frozen=True, slots=True)
class Item:
    """Mirrors one entry of the event schema's `authorization.items` array."""

    line_no: int
    item_id: str
    item_name: str
    item_category: str
    quantity: int
    unit_price: Decimal
    currency: Currency
    item_details: str
    """Untrusted, merchant-supplied text. May contain useful facts (size,
    return window) or prompt-injection attempts ("ignore the spending
    limit"). The engine may compare it to extracted facts but must never let
    it alter a limit or a decision path directly."""


@dataclass(frozen=True, slots=True)
class HardRule:
    """One entry of `mandate.hard_rules`.

    `field` is a dotted path into the event (a convention for this engine to
    interpret, not a formula the challenge API runs). See
    `checks/_hard_rule_engine.py` for the interpreter and its supported
    paths.
    """

    field: str
    operator: Literal["<", "<=", "=", "!=", ">", ">=", "in", "not_in"]
    value: int | float | str | tuple[str, ...]
    currency: Currency | None = None
    scope: Literal["purchase", "period"] | None = None
    period_days: int | None = None


@dataclass(frozen=True, slots=True)
class Mandate:
    """Mirrors the event schema's `mandate` object (a run's mandate snapshot)."""

    mandate_id: str
    status: Literal["active", "superseded", "revoked", "expired"]
    customer_id: str
    card_id: str
    instruction: str
    hard_rules: tuple[HardRule, ...]
    uncertainty_policy: Literal["ask", "decline", "approve"]
    profile_id: str


@dataclass(frozen=True, slots=True)
class RecentAuthorization:
    """One entry of `context.recent_authorizations`."""

    authorization_id: str
    timestamp: datetime
    merchant_id: str
    billing_amount_chf: Decimal
    status: Literal["approved", "declined", "pending", "cancelled"]


@dataclass(frozen=True, slots=True)
class EventContext:
    """Mirrors the event schema's `context` object.

    `approved_spend_in_period_chf` is the platform-maintained live counter
    for the run (recomputed from decisions actually taken); it can be
    `None`. It is *not* the same as `EngineState.approved_spend_in_period_chf`,
    which is whatever the caller tracks outside a single run/event.
    """

    approved_spend_in_period_chf: Decimal | None
    recent_authorizations: tuple[RecentAuthorization, ...]


@dataclass(frozen=True, slots=True)
class Runtime:
    """Mirrors the event schema's `runtime` object."""

    received_at: datetime
    history_window_minutes: int
    context_basis: str


@dataclass(frozen=True, slots=True)
class AuthorizationEvent:
    """One proposed purchase, as the engine sees it.

    This flattens the schema's outer envelope (`request_id`, `deadline_at`)
    together with its `authorization` object, since both describe "this one
    proposed purchase" -- the schema's own wording for an event. Nested
    `merchant`, `items`, `mandate`, `context`, and `runtime` objects stay
    nested.

    `scenario_id` and `replay_order` are intentionally absent: see the
    module docstring.
    """

    request_id: str
    deadline_at: datetime

    authorization_id: str
    source_authorization_id: str
    mandate_id: str
    profile_id: str
    card_id: str
    merchant: Merchant
    timestamp: datetime
    amount: Decimal
    currency: Currency
    billing_amount_chf: Decimal
    items_subtotal: Decimal
    delivery_fee: Decimal
    channel: Literal["ecommerce", "in_store", "mobile_wallet", "recurring", "atm"]
    customer_device_id: str
    """Opaque device handle, or "" when no cardholder device is involved
    (always the case for `in_store` / `atm` channels; always populated
    otherwise)."""
    authority_status: Literal["active", "revoked", "expired"]
    card_status_at_attempt: Literal["active", "blocked"]
    spend_in_period_before_chf: Decimal | None
    recent_attempt_count_10m: int
    fulfillment_method: str
    delivery_by: date | None
    order_returnable: TrileanStr
    order_cancellable: TrileanStr
    related_authorization_id: str | None
    related_authorization_status: Literal["pending", "approved", "declined", "cancelled"] | None
    purchase_description: str
    """Merchant/agent-supplied text. Deliberately uninformative in the
    challenge fixtures and untrusted in general -- never let it change a
    limit or a decision path."""
    items: tuple[Item, ...]

    mandate: Mandate
    context: EventContext
    runtime: Runtime


@dataclass(frozen=True, slots=True)
class ApprovedPurchase:
    """One earlier, *finally approved* purchase, as tracked outside the engine.

    A step-up that is still pending customer resolution is not approved and
    must not appear here (see `EngineState`).
    """

    authorization_id: str
    timestamp: datetime
    merchant_id: str
    merchant_name: str
    merchant_country: str
    device_id: str
    billing_amount_chf: Decimal
    purchase_description: str
    item_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EngineState:
    """Everything the engine needs to know about earlier decisions.

    This is plain data assembled by the caller (Django views/worker, or an
    offline replay script) from wherever it keeps history -- a database, the
    challenge API's `context`, or the challenge history CSV. The engine never
    fetches this itself.
    """

    approved_spend_in_period_chf: Decimal | None = None
    """The caller's own running total for whatever period it tracks
    (e.g. a calendar month). Used by `checks/period.py` as a fallback only
    when a hard rule's `scope="period"` omits `period_days`; when
    `period_days` is given, the check aggregates `recent_approved_purchases`
    instead, which is exact for that window."""

    seen_authorization_ids: frozenset[str] = frozenset()
    """Live `authorization_id`s already recorded by this engine/caller, so a
    retried delivery of the same id is recognised rather than treated as a
    fresh purchase (and, in particular, is never double-counted as spend)."""

    known_merchant_ids: Mapping[str, int] = field(default_factory=dict)
    """merchant_id -> number of prior approved purchases at that merchant on
    this card (any time window, not just `recent_approved_purchases`)."""

    known_device_ids: Mapping[str, int] = field(default_factory=dict)
    """customer_device_id -> number of prior approved purchases from that
    device on this card."""

    recent_approved_purchases: tuple[ApprovedPurchase, ...] = ()
    """Enough approved history to compute rolling-window sums, merchant/
    device/name familiarity, and near-duplicate detection. The caller
    decides how far back to include; checks filter by timestamp themselves
    for any particular `period_days`."""


@dataclass(frozen=True, slots=True)
class ExtractedFacts:
    """Facts about a purchase extracted by an LLM running OUTSIDE the engine.

    This is optional, best-effort input. When `None`, `checks/item_match.py`
    and `checks/purpose_fit.py` must return `UNCERTAIN` -- never `PASS` --
    because the engine has no independent way to confirm the purchase
    matches what the customer asked for or what the merchant claims.

    The fields below are provisional placeholders for the future
    implementations described in those two modules; nothing reads them yet
    beyond checking that `facts is not None`.
    """

    items_match_description: bool | None = None
    """Whether extracted item facts (from `item_details`) are consistent
    with the claimed `item_name` / `item_category` on the same line."""

    item_match_notes: tuple[str, ...] = ()

    purpose_fit_assessment: str | None = None
    """Free-text LLM judgement of whether this purchase fits the customer's
    stated purpose in `mandate.instruction`."""

    purpose_fit_confidence: float | None = None
