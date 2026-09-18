"""Generic dotted-path hard-rule interpreter, shared by `amount.py` and `period.py`.

Not one of the required check modules itself -- this is the reusable
mechanics behind both: resolving a mandate rule's dotted `field` against an
`AuthorizationEvent`, and applying its `operator` against its `value`.

Supported field paths (anything else resolves as unknown):

- ``authorization.<scalar field>`` -- any non-nested field of
  `AuthorizationEvent` (e.g. `authorization.billing_amount_chf`,
  `authorization.channel`, `authorization.recent_attempt_count_10m`).
- ``authorization.merchant.<field>`` -- any field of `Merchant`.
- ``authorization.items.<field>`` or ``authorization.items[].<field>`` --
  any field of `Item`; resolves to a tuple of that field across every cart
  line. The rule must then hold for *every* line to PASS (a basket-wide
  restriction such as ``item_category not_in ["cosmetics"]`` fails the
  whole purchase if any one line violates it).
- ``mandate.<field>`` -- any field of `Mandate` (excluding `hard_rules`
  itself, which is not a resolvable value).
- ``context.<field>`` -- any field of `EventContext`.

An unknown field path, or a rule this interpreter cannot safely evaluate
(currency mismatch, incomparable types, a `null`/missing actual value),
never crashes and never resolves to PASS by accident: callers get back
`satisfied=None` with a `cause` explaining why, and must treat that as
UNCERTAIN.

**"unknown" vs. `null` vs. "not_applicable".** Some string fields in the
event schema (`order_returnable`, `order_cancellable`) can hold the literal
value `"unknown"`, meaning the merchant did not supply that information --
distinct from a `null` field (present but empty) and from `"not_applicable"`
(a real, known answer: the term does not apply to this kind of order). This
module treats a resolved actual value of `"unknown"` exactly like a `null`
one: `_compare_scalar` returns `None` (UNCERTAIN) for it *unconditionally*,
regardless of `operator` -- a rule requiring `= "true"` and a rule requiring
`!= "true"` both come back UNCERTAIN against an `"unknown"` actual, because
neither a match nor a non-match can be confirmed from absent information.
This is deliberately different from ordinary string inequality: comparing
`"unknown" == "true"` would otherwise resolve to a *confident* `False`
(hence FAIL a hard rule that requires `"true"`), which is the wrong product
behaviour -- declining a purchase because a shop simply didn't say whether
an item is returnable would be "blocking ordinary shopping unnecessarily"
(a failure per the challenge brief), not evidence the customer's rule was
violated. `"not_applicable"` gets no such treatment: it is known, legitimate
information, so it participates in ordinary string comparison like any
other value -- a hard rule requiring `= "true"` against an actual
`"not_applicable"` is a definite FAIL (the requirement is not met), not an
UNCERTAIN, because the merchant *did* tell us the answer; it just wasn't
the one the rule demands.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Literal

from engine import reasons
from engine.money import UnknownCurrencyError, to_chf
from engine.types import AuthorizationEvent, EventContext, HardRule, Item, Mandate, Merchant

_UNRESOLVED = object()

_AUTH_SCALAR_FIELDS = frozenset(
    f.name
    for f in dataclasses.fields(AuthorizationEvent)
    if f.name not in {"merchant", "items", "mandate", "context", "runtime"}
)
_MERCHANT_FIELDS = frozenset(f.name for f in dataclasses.fields(Merchant))
_ITEM_FIELDS = frozenset(f.name for f in dataclasses.fields(Item))
_MANDATE_FIELDS = frozenset(f.name for f in dataclasses.fields(Mandate) if f.name != "hard_rules")
_CONTEXT_FIELDS = frozenset(f.name for f in dataclasses.fields(EventContext))

# Fields already denominated in CHF: a rule's `value` is converted into CHF
# (via its optional `currency`) before comparison. Every other numeric field
# (e.g. `authorization.amount`, `authorization.items.unit_price`) is in the
# event's/line's own currency, and this generic interpreter does not attempt
# a currency-aware comparison for those -- see `_expected_value_for`.
_CHF_FIELDS = frozenset(
    {
        "authorization.billing_amount_chf",
        "authorization.spend_in_period_before_chf",
        "context.approved_spend_in_period_chf",
    }
)

Cause = Literal[
    "unknown_field", "unresolved_currency", "missing_actual", "unknown_value", "incomparable"
]

_UNKNOWN_VALUE = "unknown"
"""The literal string the event schema uses to mean "not supplied" on
`order_returnable` / `order_cancellable` (and, generically, any other string
field that might one day reuse it). Not to be confused with `"not_applicable"`."""


def resolve_field(event: AuthorizationEvent, field_path: str) -> object:
    """Resolve a dotted `field` path to a value (or tuple of values, or `_UNRESOLVED`)."""
    normalized = field_path.replace("[]", "")
    parts = [p for p in normalized.split(".") if p]
    if len(parts) < 2:
        return _UNRESOLVED
    root, *rest = parts
    if root == "authorization":
        if len(rest) == 2 and rest[0] == "merchant" and rest[1] in _MERCHANT_FIELDS:
            return getattr(event.merchant, rest[1])
        if len(rest) == 2 and rest[0] == "items" and rest[1] in _ITEM_FIELDS:
            return tuple(getattr(item, rest[1]) for item in event.items)
        if len(rest) == 1 and rest[0] in _AUTH_SCALAR_FIELDS:
            return getattr(event, rest[0])
        return _UNRESOLVED
    if root == "mandate" and len(rest) == 1 and rest[0] in _MANDATE_FIELDS:
        return getattr(event.mandate, rest[0])
    if root == "context" and len(rest) == 1 and rest[0] in _CONTEXT_FIELDS:
        return getattr(event.context, rest[0])
    return _UNRESOLVED


def _expected_value_for(rule: HardRule) -> object:
    if rule.field in _CHF_FIELDS and isinstance(rule.value, (int, float)):
        if rule.currency and rule.currency != "CHF":
            try:
                return to_chf(Decimal(str(rule.value)), rule.currency)
            except UnknownCurrencyError:
                return _UNRESOLVED
        return Decimal(str(rule.value))
    return rule.value


def _as_number(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    return None


def _loose_eq(actual: object, expected: object) -> bool | None:
    a_num, e_num = _as_number(actual), _as_number(expected)
    if a_num is not None and e_num is not None:
        return a_num == e_num
    if isinstance(actual, str) and isinstance(expected, str):
        return actual == expected
    return None


def _compare_scalar(actual: object, operator: str, expected: object) -> bool | None:
    if actual is None:
        # A null field is present but has no value: never guess.
        return None
    if actual == _UNKNOWN_VALUE:
        # "unknown" means the merchant/platform did not supply this
        # information -- never a confirmed match (=, in) nor a confirmed
        # non-match (!=, not_in). Unconditional: see the module docstring.
        return None
    if operator in {"<", "<=", ">", ">="}:
        a, e = _as_number(actual), _as_number(expected)
        if a is None or e is None:
            return None
        if operator == "<":
            return a < e
        if operator == "<=":
            return a <= e
        if operator == ">":
            return a > e
        return a >= e
    if operator == "=":
        return _loose_eq(actual, expected)
    if operator == "!=":
        eq = _loose_eq(actual, expected)
        return None if eq is None else not eq
    if operator in {"in", "not_in"}:
        if not isinstance(expected, tuple):
            return None
        is_in = actual in expected
        return is_in if operator == "in" else not is_in
    return None


def evaluate_rule(
    event: AuthorizationEvent, rule: HardRule
) -> tuple[bool | None, object, Cause | None]:
    """Evaluate one `HardRule` against `event`.

    Returns `(satisfied, resolved_value, cause)`:

    - `satisfied` is `True`/`False` when the rule could be evaluated safely,
      or `None` when it could not (treat as UNCERTAIN, never as PASS).
    - `resolved_value` is whatever was compared, for use as `Evidence.value`.
    - `cause` explains a `None` `satisfied`; `None` otherwise.
    """
    resolved = resolve_field(event, rule.field)
    if resolved is _UNRESOLVED:
        return None, None, "unknown_field"
    expected = _expected_value_for(rule)
    if expected is _UNRESOLVED:
        return None, resolved, "unresolved_currency"
    if isinstance(resolved, tuple):
        outcomes = [_compare_scalar(v, rule.operator, expected) for v in resolved]
        if any(o is None for o in outcomes):
            cause = "unknown_value" if _UNKNOWN_VALUE in resolved else "incomparable"
            return None, resolved, cause
        return all(outcomes), resolved, None
    outcome = _compare_scalar(resolved, rule.operator, expected)
    if outcome is None:
        if resolved is None:
            cause = "missing_actual"
        elif resolved == _UNKNOWN_VALUE:
            cause = "unknown_value"
        else:
            cause = "incomparable"
        return None, resolved, cause
    return outcome, resolved, None


def rule_scope(rule: HardRule) -> Literal["purchase", "period"]:
    """`scope` defaults to `"purchase"` when omitted, per the rule format docs."""
    return rule.scope or "purchase"


def reason_code_for_cause(cause: Cause) -> str:
    """The `reasons.py` constant a check should attach to a `None`-`satisfied` rule.

    Shared by `amount.py` and `period.py` so both name the same code for the
    same cause -- in particular, `"unknown_value"` always gets its own
    dedicated code (`HARD_RULE_VALUE_UNKNOWN`), never the generic
    `HARD_RULE_UNINTERPRETABLE` used for `null` fields and other
    incomparable cases.
    """
    if cause == "unknown_field":
        return reasons.HARD_RULE_UNKNOWN_FIELD
    if cause == "unknown_value":
        return reasons.HARD_RULE_VALUE_UNKNOWN
    return reasons.HARD_RULE_UNINTERPRETABLE
