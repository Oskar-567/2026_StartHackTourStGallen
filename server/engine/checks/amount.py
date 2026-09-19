"""Per-purchase limit: mandate `hard_rules` with `scope="purchase"` (the default).

This is the generic hard-rule interpreter from `_hard_rule_engine.py` applied
to every rule whose scope is `"purchase"` (or omitted -- `"purchase"` is the
documented default). Despite the module name, the interpreter is *not*
restricted to amount/money fields: a rule such as
``authorization.items.item_category not_in ["cosmetics"]`` is evaluated here
too, since it is also purchase-scoped. "amount" names the dominant real-world
case (spending limits), not a field-type restriction.

Deterministic tier: no LLM, no network, no randomness.
"""

from __future__ import annotations

from engine import reasons
from engine.checks._hard_rule_engine import evaluate_rule, reason_code_for_cause, rule_scope
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, HardRule, Verdict

_AMOUNT_FIELDS = frozenset(
    {
        "authorization.amount",
        "authorization.billing_amount_chf",
        "authorization.items_subtotal",
        "authorization.delivery_fee",
    }
)


def _violation_code(rule: HardRule) -> str:
    """Name the violation after what the rule is about.

    One code for every purchase rule told the customer "over your limit" when
    the shop was simply the wrong kind of shop. The code travels to the app and
    the challenge API, so it has to say what actually went wrong.
    """
    if rule.field in _AMOUNT_FIELDS:
        return reasons.AMOUNT_LIMIT_EXCEEDED
    if rule.field.startswith("authorization.merchant."):
        return reasons.MERCHANT_NOT_PERMITTED
    return reasons.HARD_RULE_VIOLATED


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    """Evaluate every purchase-scoped hard rule; combine into one result.

    Adding a rule must never weaken an existing restriction (see
    `aggregate.py`): this check treats *every* purchase-scoped rule as
    mandatory (AND), so an additional rule can only ever add a new way to
    FAIL or become UNCERTAIN, never remove one.
    """
    evidence: list[Evidence] = []
    failed_rule: HardRule | None = None
    any_uncertain = False

    for rule in event.mandate.hard_rules:
        if rule_scope(rule) != "purchase":
            continue
        satisfied, resolved, cause = evaluate_rule(event, rule)
        if satisfied is None:
            any_uncertain = True
            reason_code = reason_code_for_cause(cause)
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=resolved,
                    note=(
                        f"hard rule '{rule.field} {rule.operator} {rule.value!r}' could not "
                        f"be evaluated ({cause}); reason_code={reason_code}"
                    ),
                )
            )
        elif satisfied is False:
            failed_rule = failed_rule or rule
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=resolved,
                    note=f"violates hard rule '{rule.field} {rule.operator} {rule.value!r}'",
                )
            )

    if failed_rule is not None:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=_violation_code(failed_rule),
            message="This purchase violates one or more of the customer's per-purchase rules.",
            evidence=tuple(evidence),
        )
    if any_uncertain:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.HARD_RULE_UNINTERPRETABLE,
            message="One or more per-purchase rules could not be checked with confidence.",
            evidence=tuple(evidence),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="All per-purchase rules are satisfied.",
        evidence=(),
    )
