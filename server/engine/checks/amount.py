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
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict


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
    any_fail = False
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
            any_fail = True
            evidence.append(
                Evidence(
                    field=rule.field,
                    value=resolved,
                    note=f"violates hard rule '{rule.field} {rule.operator} {rule.value!r}'",
                )
            )

    if any_fail:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=reasons.AMOUNT_LIMIT_EXCEEDED,
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
