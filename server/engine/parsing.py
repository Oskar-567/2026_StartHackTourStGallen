"""Raw dict -> typed `AuthorizationEvent`.

Strict about value types: this module raises `EventParsingError` rather than
silently coercing or defaulting a malformed or missing field. In particular:

- `null` stays `None` (never becomes `0`, `False`, or `"unknown"`).
- `"unknown"` and `"not_applicable"` stay as those exact strings -- they are
  never treated as `"true"`/`"false"`/permission.
- Numbers are parsed as `Decimal` (via `str()` of the JSON number) rather
  than `float`, so no binary floating-point drift enters money comparisons.
- Timestamps use `datetime.fromisoformat` after normalising a trailing "Z"
  (Python's `fromisoformat` does not accept "Z" before 3.11's partial
  support; we normalise explicitly to be safe across event sources).

Deliberate, permanent omission: `authorization.scenario_id` and
`authorization.replay_order` are read from the raw dict *only* to validate
their presence/shape (so a malformed event still fails to parse) and are
then discarded. They are never copied onto `AuthorizationEvent`. The
challenge brief forbids deciding from scenario identity or sequence
position; dropping both fields here -- the single boundary where raw JSON
becomes engine data -- makes it structurally impossible for any check
downstream to read them, rather than relying on every check to remember not
to.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from engine.types import (
    AuthorizationEvent,
    EventContext,
    HardRule,
    IntentSpec,
    Item,
    Mandate,
    Merchant,
    RecentAuthorization,
    Runtime,
)

_CURRENCIES = {"CHF", "EUR", "GBP", "USD"}
_TRILEAN = {"true", "false", "unknown", "not_applicable"}
_OPERATORS = {"<", "<=", "=", "!=", ">", ">=", "in", "not_in"}


class EventParsingError(ValueError):
    """Raised when a raw event dict does not match the expected shape."""


def _fail(path: str, msg: str) -> None:
    raise EventParsingError(f"{path}: {msg}")


def _get_dict(raw: dict[str, Any], key: str, path: str) -> dict[str, Any]:
    if key not in raw:
        _fail(path, f"missing required field {key!r}")
    value = raw[key]
    if not isinstance(value, dict):
        _fail(path, f"{key!r} must be an object, got {type(value).__name__}")
    return value


def _get_str(raw: dict[str, Any], key: str, path: str, *, allowed: set[str] | None = None) -> str:
    if key not in raw:
        _fail(path, f"missing required field {key!r}")
    value = raw[key]
    if not isinstance(value, str):
        _fail(path, f"{key!r} must be a string, got {type(value).__name__}")
    if allowed is not None and value not in allowed:
        _fail(path, f"{key!r}={value!r} is not one of {sorted(allowed)}")
    return value


def _get_optional_str(
    raw: dict[str, Any], key: str, path: str, *, allowed: set[str] | None = None
) -> str | None:
    if key not in raw:
        _fail(path, f"missing required field {key!r}")
    value = raw[key]
    if value is None:
        return None
    if not isinstance(value, str):
        _fail(path, f"{key!r} must be a string or null, got {type(value).__name__}")
    if allowed is not None and value not in allowed:
        _fail(path, f"{key!r}={value!r} is not one of {sorted(allowed)}")
    return value


def _get_bool_str(raw: dict[str, Any], key: str, path: str) -> bool:
    """Parse a strict `"true"`/`"false"` string field into a real bool.

    Only used for fields the schema restricts to exactly those two literal
    strings (e.g. `merchant.recurring_capable`) -- never for the four-state
    `order_returnable` / `order_cancellable` fields, which stay strings.
    """
    value = _get_str(raw, key, path, allowed={"true", "false"})
    return value == "true"


def _get_int(raw: dict[str, Any], key: str, path: str, *, minimum: int | None = None) -> int:
    if key not in raw:
        _fail(path, f"missing required field {key!r}")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, f"{key!r} must be an integer, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        _fail(path, f"{key!r}={value} must be >= {minimum}")
    return value


def _get_decimal(
    raw: dict[str, Any], key: str, path: str, *, allow_null: bool = False
) -> Decimal | None:
    if key not in raw:
        _fail(path, f"missing required field {key!r}")
    value = raw[key]
    if value is None:
        if allow_null:
            return None
        _fail(path, f"{key!r} must not be null")
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _fail(path, f"{key!r} must be a number, got {type(value).__name__}")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        _fail(path, f"{key!r}={value!r} is not a valid number")
        raise  # unreachable, keeps type-checkers happy


def _parse_datetime(raw_value: Any, key: str, path: str) -> datetime:
    if not isinstance(raw_value, str):
        _fail(path, f"{key!r} must be an ISO-8601 datetime string")
    text = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        _fail(path, f"{key!r}={raw_value!r} is not a valid datetime: {exc}")
        raise  # unreachable


def _parse_date(raw_value: Any, key: str, path: str) -> date | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        _fail(path, f"{key!r} must be a date string or null")
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        _fail(path, f"{key!r}={raw_value!r} is not a valid date: {exc}")
        raise  # unreachable


def _parse_merchant(raw: dict[str, Any], path: str) -> Merchant:
    return Merchant(
        merchant_id=_get_str(raw, "merchant_id", path),
        merchant_name=_get_str(raw, "merchant_name", path),
        merchant_category=_get_str(raw, "merchant_category", path),
        merchant_mcc=_get_str(raw, "merchant_mcc", path),
        merchant_country=_get_str(raw, "merchant_country", path),
        merchant_city=_get_str(raw, "merchant_city", path),
        availability=_get_str(  # type: ignore[arg-type]
            raw, "availability", path, allowed={"online", "store", "store_and_online", "atm"}
        ),
        recurring_capable=_get_bool_str(raw, "recurring_capable", path),
    )


def _parse_item(raw: dict[str, Any], path: str) -> Item:
    currency = _get_str(raw, "currency", path, allowed=_CURRENCIES)
    unit_price = _get_decimal(raw, "unit_price", path)
    assert unit_price is not None
    return Item(
        line_no=_get_int(raw, "line_no", path, minimum=1),
        item_id=_get_str(raw, "item_id", path),
        item_name=_get_str(raw, "item_name", path),
        item_category=_get_str(raw, "item_category", path),
        quantity=_get_int(raw, "quantity", path, minimum=1),
        unit_price=unit_price,
        currency=currency,  # type: ignore[arg-type]
        item_details=_get_str(raw, "item_details", path),
    )


def _parse_hard_rule(raw: dict[str, Any], path: str) -> HardRule:
    if not isinstance(raw, dict):
        _fail(path, "each hard_rules entry must be an object")
    field = _get_str(raw, "field", path)
    operator = _get_str(raw, "operator", path, allowed=_OPERATORS)
    if "value" not in raw:
        _fail(path, "missing required field 'value'")
    raw_value = raw["value"]
    value: int | float | str | tuple[str, ...]
    if isinstance(raw_value, bool):
        _fail(path, "'value' must not be a boolean")
        raise AssertionError  # unreachable
    elif isinstance(raw_value, (int, float)):
        value = raw_value
    elif isinstance(raw_value, str):
        value = raw_value
    elif isinstance(raw_value, list):
        if not all(isinstance(v, str) for v in raw_value):
            _fail(path, "'value' list must contain only strings")
        value = tuple(raw_value)
    else:
        _fail(path, f"'value' has an unsupported type: {type(raw_value).__name__}")
        raise AssertionError  # unreachable
    currency = raw.get("currency")
    if currency is not None and currency not in _CURRENCIES:
        _fail(path, f"'currency'={currency!r} is not one of {sorted(_CURRENCIES)}")
    scope = raw.get("scope")
    if scope is not None and scope not in {"purchase", "period"}:
        _fail(path, f"'scope'={scope!r} is not one of ['purchase', 'period']")
    period_days = raw.get("period_days")
    if period_days is not None and (
        isinstance(period_days, bool) or not isinstance(period_days, int) or period_days < 1
    ):
        _fail(path, f"'period_days'={period_days!r} must be a positive integer or null")
    return HardRule(
        field=field,
        operator=operator,  # type: ignore[arg-type]
        value=value,
        currency=currency,
        scope=scope,
        period_days=period_days,
    )


def _parse_mandate(raw: dict[str, Any], path: str) -> Mandate:
    raw_rules = raw.get("hard_rules")
    if not isinstance(raw_rules, list):
        _fail(path, "'hard_rules' must be a list")
    hard_rules = tuple(
        _parse_hard_rule(r, f"{path}.hard_rules[{i}]") for i, r in enumerate(raw_rules)
    )
    return Mandate(
        mandate_id=_get_str(raw, "mandate_id", path),
        status=_get_str(  # type: ignore[arg-type]
            raw, "status", path, allowed={"active", "superseded", "revoked", "expired"}
        ),
        customer_id=_get_str(raw, "customer_id", path),
        card_id=_get_str(raw, "card_id", path),
        instruction=_get_str(raw, "instruction", path),
        hard_rules=hard_rules,
        uncertainty_policy=_get_str(  # type: ignore[arg-type]
            raw, "uncertainty_policy", path, allowed={"ask", "decline", "approve"}
        ),
        profile_id=_get_str(raw, "profile_id", path),
        intent_spec=_parse_intent_spec(raw.get("intent_spec"), f"{path}.intent_spec"),
    )


def _parse_intent_spec(raw: Any, path: str) -> IntentSpec | None:
    """Optional and caller-supplied: the live event never carries it.

    A malformed spec is rejected rather than half-read. Quietly dropping the
    half we could not parse would silently widen what the customer allowed,
    and widening a policy by accident is the one failure this engine must not
    have.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail(path, "'intent_spec' must be an object when present")
    categories = raw.get("allowed_item_categories", [])
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        _fail(path, "'allowed_item_categories' must be a list of strings")
    attributes = raw.get("required_attributes", {})
    if not isinstance(attributes, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in attributes.items()
    ):
        _fail(path, "'required_attributes' must be a mapping of string to string")
    purpose = raw.get("purpose", "")
    if not isinstance(purpose, str):
        _fail(path, "'purpose' must be a string")
    return IntentSpec(
        purpose=purpose,
        allowed_item_categories=frozenset(categories),
        required_attributes=dict(attributes),
    )


def _parse_recent_authorization(raw: dict[str, Any], path: str) -> RecentAuthorization:
    amount = _get_decimal(raw, "billing_amount_chf", path)
    assert amount is not None
    return RecentAuthorization(
        authorization_id=_get_str(raw, "authorization_id", path),
        timestamp=_parse_datetime(raw.get("timestamp"), "timestamp", path),
        merchant_id=_get_str(raw, "merchant_id", path),
        billing_amount_chf=amount,
        status=_get_str(  # type: ignore[arg-type]
            raw, "status", path, allowed={"approved", "declined", "pending", "cancelled"}
        ),
    )


def _parse_context(raw: dict[str, Any], path: str) -> EventContext:
    raw_recent = raw.get("recent_authorizations")
    if not isinstance(raw_recent, list):
        _fail(path, "'recent_authorizations' must be a list")
    return EventContext(
        approved_spend_in_period_chf=_get_decimal(
            raw, "approved_spend_in_period_chf", path, allow_null=True
        ),
        recent_authorizations=tuple(
            _parse_recent_authorization(r, f"{path}.recent_authorizations[{i}]")
            for i, r in enumerate(raw_recent)
        ),
    )


def _parse_runtime(raw: dict[str, Any], path: str) -> Runtime:
    return Runtime(
        received_at=_parse_datetime(raw.get("received_at"), "received_at", path),
        history_window_minutes=_get_int(raw, "history_window_minutes", path, minimum=1),
        context_basis=_get_str(
            raw,
            "context_basis",
            path,
            allowed={"run_decisions_and_scenario_timestamps"},
        ),
    )


def parse_event(raw: dict[str, Any]) -> AuthorizationEvent:
    """Parse a raw `authorization.request` envelope dict into an `AuthorizationEvent`.

    Raises `EventParsingError` on any missing, mistyped, or out-of-enum
    field. Does not attempt partial/best-effort parsing: a malformed event
    should fail loudly rather than produce a half-populated event a check
    might misread as complete.
    """
    if not isinstance(raw, dict):
        raise EventParsingError("event must be a JSON object")

    _get_str(raw, "type", "$", allowed={"authorization.request"})
    request_id = _get_str(raw, "request_id", "$")
    deadline_at = _parse_datetime(raw.get("deadline_at"), "deadline_at", "$")

    auth = _get_dict(raw, "authorization", "$")
    path = "$.authorization"

    # Validate presence/shape of scenario_id and replay_order (so a malformed
    # event still fails to parse cleanly) and then deliberately drop them --
    # see the module docstring.
    _get_str(auth, "scenario_id", path)
    _get_int(auth, "replay_order", path, minimum=1)

    currency = _get_str(auth, "currency", path, allowed=_CURRENCIES)
    amount = _get_decimal(auth, "amount", path)
    billing_amount_chf = _get_decimal(auth, "billing_amount_chf", path)
    items_subtotal = _get_decimal(auth, "items_subtotal", path)
    delivery_fee = _get_decimal(auth, "delivery_fee", path)
    assert amount is not None
    assert billing_amount_chf is not None
    assert items_subtotal is not None
    assert delivery_fee is not None

    raw_items = auth.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        _fail(path, "'items' must be a non-empty list")
    items = tuple(_parse_item(item, f"{path}.items[{i}]") for i, item in enumerate(raw_items))

    return AuthorizationEvent(
        request_id=request_id,
        deadline_at=deadline_at,
        authorization_id=_get_str(auth, "authorization_id", path),
        source_authorization_id=_get_str(auth, "source_authorization_id", path),
        mandate_id=_get_str(auth, "mandate_id", path),
        profile_id=_get_str(auth, "profile_id", path),
        card_id=_get_str(auth, "card_id", path),
        merchant=_parse_merchant(_get_dict(auth, "merchant", path), f"{path}.merchant"),
        timestamp=_parse_datetime(auth.get("timestamp"), "timestamp", path),
        amount=amount,
        currency=currency,  # type: ignore[arg-type]
        billing_amount_chf=billing_amount_chf,
        items_subtotal=items_subtotal,
        delivery_fee=delivery_fee,
        channel=_get_str(  # type: ignore[arg-type]
            auth,
            "channel",
            path,
            allowed={"ecommerce", "in_store", "mobile_wallet", "recurring", "atm"},
        ),
        customer_device_id=_get_str(auth, "customer_device_id", path),
        authority_status=_get_str(  # type: ignore[arg-type]
            auth, "authority_status", path, allowed={"active", "revoked", "expired"}
        ),
        card_status_at_attempt=_get_str(  # type: ignore[arg-type]
            auth, "card_status_at_attempt", path, allowed={"active", "blocked"}
        ),
        spend_in_period_before_chf=_get_decimal(
            auth, "spend_in_period_before_chf", path, allow_null=True
        ),
        recent_attempt_count_10m=_get_int(auth, "recent_attempt_count_10m", path, minimum=0),
        fulfillment_method=_get_str(auth, "fulfillment_method", path),
        delivery_by=_parse_date(auth.get("delivery_by"), "delivery_by", path),
        order_returnable=_get_str(  # type: ignore[arg-type]
            auth, "order_returnable", path, allowed=_TRILEAN
        ),
        order_cancellable=_get_str(  # type: ignore[arg-type]
            auth, "order_cancellable", path, allowed=_TRILEAN
        ),
        related_authorization_id=_get_optional_str(auth, "related_authorization_id", path),
        related_authorization_status=_get_optional_str(  # type: ignore[arg-type]
            auth,
            "related_authorization_status",
            path,
            allowed={"pending", "approved", "declined", "cancelled"},
        ),
        purchase_description=_get_str(auth, "purchase_description", path),
        items=items,
        mandate=_parse_mandate(_get_dict(raw, "mandate", "$"), "$.mandate"),
        context=_parse_context(_get_dict(raw, "context", "$"), "$.context"),
        runtime=_parse_runtime(_get_dict(raw, "runtime", "$"), "$.runtime"),
    )
