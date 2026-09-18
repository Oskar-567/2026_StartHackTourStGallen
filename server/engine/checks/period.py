"""Rolling-window spend limit: mandate `hard_rules` with `scope="period"`.

Money-only aggregation (the natural case for a period-scoped hard rule: "no
more than CHF X per Y days"). Two supported fields:

- ``authorization.billing_amount_chf`` with a `period_days`: sums
  `EngineState.recent_approved_purchases` within
  `[event.timestamp - period_days, event.timestamp)` plus this purchase's
  own `billing_amount_chf`, and compares the total against the rule.
- ``context.approved_spend_in_period_chf`` (or `authorization.
  billing_amount_chf` with no `period_days`): uses the platform's own running
  counter (`event.context.approved_spend_in_period_chf`) plus this purchase's
  amount. If the platform supplied none, the caller's
  `EngineState.approved_spend_in_period_chf` is reported as evidence but
  resolves UNCERTAIN, never PASS or FAIL: it tracks whatever window the caller
  happens to keep, which need not be the window the rule names.

A period rule on any other field is not supported by this generic
aggregator: rather than silently ignore it or guess PASS, it resolves
UNCERTAIN with `PERIOD_RULE_UNSUPPORTED_FIELD`.

Deterministic tier: no LLM, no network, no randomness.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from engine import reasons
from engine.checks._hard_rule_engine import (
    _UNRESOLVED,
    _compare_scalar,
    _expected_value_for,
    rule_scope,
)
from engine.types import (
    AuthorizationEvent,
    CheckResult,
    EngineState,
    Evidence,
    HardRule,
    Verdict,
)

_SUPPORTED_FIELDS = {"authorization.billing_amount_chf", "context.approved_spend_in_period_chf"}


def _window_sum(event: AuthorizationEvent, state: EngineState, period_days: int) -> Decimal:
    cutoff = event.timestamp - timedelta(days=period_days)
    return sum(
        (
            p.billing_amount_chf
            for p in state.recent_approved_purchases
            if cutoff <= p.timestamp < event.timestamp
        ),
        start=Decimal("0"),
    )


_SOURCE_WINDOW = "window"
_SOURCE_PLATFORM = "platform"
_SOURCE_CALLER = "caller"


def _period_total(
    event: AuthorizationEvent, state: EngineState, rule: HardRule
) -> tuple[Decimal, str] | None:
    """The would-be total spend in the rule's window, including this purchase,
    together with where the baseline came from.

    The source matters. An exact window (`period_days` given) and the
    platform's own running counter both describe the window the rule names.
    `EngineState.approved_spend_in_period_chf` does not: it is whatever period
    the caller happens to track -- a calendar month, say -- so a total derived
    from it can neither confirm nor refute a rule about "any seven days", and
    the caller must not be allowed to PASS or FAIL one on that basis.
    """
    if rule.field == "authorization.billing_amount_chf" and rule.period_days is not None:
        total = _window_sum(event, state, rule.period_days) + event.billing_amount_chf
        return total, _SOURCE_WINDOW
    baseline = event.context.approved_spend_in_period_chf
    if baseline is not None:
        return baseline + event.billing_amount_chf, _SOURCE_PLATFORM
    if state.approved_spend_in_period_chf is None:
        return None
    return state.approved_spend_in_period_chf + event.billing_amount_chf, _SOURCE_CALLER


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    """Evaluate every period-scoped hard rule; combine into one result.

    Adding a rule must never weaken an existing restriction (see
    `aggregate.py`): every period-scoped rule is mandatory (AND).
    """
    evidence: list[Evidence] = []
    any_fail = False
    any_uncertain = False

    for rule in event.mandate.hard_rules:
        if rule_scope(rule) != "period":
            continue
        if rule.field not in _SUPPORTED_FIELDS:
            any_uncertain = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=None,
                    note=(
                        f"period rule on '{rule.field}' is not a supported aggregation field; "
                        f"reason_code={reasons.PERIOD_RULE_UNSUPPORTED_FIELD}"
                    ),
                )
            )
            continue

        totalled = _period_total(event, state, rule)
        if totalled is None:
            any_uncertain = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=None,
                    note="no rolling-window or running-total spend data available to evaluate "
                    "this period rule",
                )
            )
            continue
        total, source = totalled
        if source == _SOURCE_CALLER:
            # The only baseline available tracks a different, unverified window.
            any_uncertain = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=float(total),
                    note=(
                        "this period rule omits `period_days` and the platform supplied no "
                        f"running total; CHF {total} comes from the caller's own spending "
                        "window, which cannot confirm the rule's window; "
                        f"reason_code={reasons.PERIOD_WINDOW_UNVERIFIED}"
                    ),
                )
            )
            continue

        expected = _expected_value_for(rule)
        if expected is _UNRESOLVED:
            any_uncertain = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=float(total),
                    note="could not resolve the rule's comparison value (unsupported currency)",
                )
            )
            continue

        satisfied = _compare_scalar(total, rule.operator, expected)
        if satisfied is None:
            any_uncertain = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=float(total),
                    note=f"could not compare period total against '{rule.operator} {rule.value!r}'",
                )
            )
        elif satisfied is False:
            any_fail = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=float(total),
                    note=(
                        f"projected {rule.period_days or 'default'}-day total "
                        f"CHF {total} violates '{rule.field} {rule.operator} {rule.value!r}'"
                    ),
                )
            )

    if any_fail:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=reasons.PERIOD_LIMIT_EXCEEDED,
            message="This purchase would exceed the customer's rolling-window spending limit.",
            evidence=tuple(evidence),
        )
    if any_uncertain:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.PERIOD_RULE_UNCERTAIN,
            message="One or more rolling-window rules could not be checked with confidence.",
            evidence=tuple(evidence),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="All rolling-window rules are satisfied.",
        evidence=(),
    )
