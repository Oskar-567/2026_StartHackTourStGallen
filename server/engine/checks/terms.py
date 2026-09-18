"""`order_returnable` / `order_cancellable` requirements.

Deterministic tier: no LLM, no network, no randomness.

This check is the most literal enforcement of "missing information is never
permission": `order_returnable` and `order_cancellable` are four-state
strings (`"true"`, `"false"`, `"unknown"`, `"not_applicable"`), and
`"unknown"` must never be read as `"true"` (or as `"false"`, for that
matter) -- it means the term was not supplied at all. `"not_applicable"` is
a different, legitimate state (e.g. a digital good has no return window) and
is treated as fine, not as a concern.

A purchase that is both non-returnable *and* non-cancellable (`"false"` on
both) is a stronger signal -- an irreversible order -- and is also raised as
UNCERTAIN rather than declined outright, since plenty of ordinary purchases
(food, digital goods) are legitimately final.

All of the above applies only when the customer's mandate actually carries a
requirement about these fields (a hard rule targeting `order_returnable` or
`order_cancellable`). With no such rule the check passes: a grocery order
whose merchant supplied no return terms is not a reason to interrupt someone
who never asked about returns, and "blocking ordinary shopping unnecessarily
is also a failure" per the brief.

This mirrors, and must stay consistent with, how `checks/_hard_rule_engine.py`
treats these same two fields when a mandate hard rule targets them directly
(e.g. `authorization.order_returnable = "true"`): `"unknown"` always yields
UNCERTAIN and never a definite match or non-match, while `"not_applicable"`
is treated as ordinary, known information and never forced into UNCERTAIN
by that reason alone.
"""

from __future__ import annotations

from engine import reasons
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict

_TERM_FIELDS = frozenset({"authorization.order_returnable", "authorization.order_cancellable"})


def _mandate_requires_terms(event: AuthorizationEvent) -> bool:
    """True when the customer's policy actually says something about order terms."""
    return any(rule.field in _TERM_FIELDS for rule in event.mandate.hard_rules)


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    if not _mandate_requires_terms(event):
        # The customer never asked about returns, so absent return terms are not
        # a reason to interrupt them. Raising UNCERTAIN here anyway would stop
        # ordinary shopping over a question nobody asked -- which the brief
        # counts as a failure just as much as letting a bad purchase through.
        return CheckResult(
            verdict=Verdict.PASS,
            reason_code=None,
            message="The customer's policy sets no return or cancellation requirement.",
            evidence=(),
        )

    evidence: list[Evidence] = []

    if event.order_returnable == "unknown":
        evidence.append(
            Evidence(
                field="authorization.order_returnable",
                value=event.order_returnable,
                note="return terms were not supplied by the merchant",
            )
        )
    if event.order_cancellable == "unknown":
        evidence.append(
            Evidence(
                field="authorization.order_cancellable",
                value=event.order_cancellable,
                note="cancellation terms were not supplied by the merchant",
            )
        )
    if evidence:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.TERMS_RETURN_STATUS_UNKNOWN,
            message="The order's return or cancellation terms were not supplied.",
            evidence=tuple(evidence),
        )

    if event.order_returnable == "false" and event.order_cancellable == "false":
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.TERMS_NON_REVERSIBLE,
            message="This order cannot be returned or cancelled once placed.",
            evidence=(
                Evidence(
                    field="authorization.order_returnable",
                    value=event.order_returnable,
                    note="order is neither returnable nor cancellable",
                ),
                Evidence(
                    field="authorization.order_cancellable",
                    value=event.order_cancellable,
                    note="order is neither returnable nor cancellable",
                ),
            ),
        )

    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="Return and cancellation terms are known and acceptable.",
        evidence=(),
    )
