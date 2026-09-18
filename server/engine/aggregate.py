"""Combine `CheckResult`s from one or more checks into a single `Decision`.

Aggregation precedence:

1. Any `FAIL` among the results -> `decline`.
2. Otherwise, any `UNCERTAIN` -> apply the mandate's `uncertainty_policy`:
   `"ask"` -> `step_up`, `"decline"` -> `decline`, `"approve"` -> `approve`.
3. Otherwise (every result `PASS`) -> `approve`.

`reason_codes` and `evidence` on the returned `Decision` are collected from
**every** check that contributed -- every result with verdict `FAIL` or
`UNCERTAIN` -- not just the one result that happened to decide the
precedence tier. A decline with three failing checks explains all three; a
step-up caused by one uncertain check alongside two failing ones still
explains all of it (its outcome is `decline`, from precedence rule 1, but
the customer-facing explanation is not allowed to hide the uncertain
finding).

**Invariant: adding a check (or a hard rule the checks interpret) must never
weaken an existing restriction.** This aggregator only ever *adds* FAIL/
UNCERTAIN signals into a decision that already started from "no concerns
found" (`approve`); nothing here can turn an existing FAIL into a PASS, or
skip a check because another one already fired. Any future change to this
module (or to a check) that would let one passing check override, silence,
or downgrade another check's non-PASS verdict violates this invariant.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from engine import reasons
from engine.types import CheckResult, Decision, DecisionType, Evidence, Verdict

UncertaintyPolicy = Literal["ask", "decline", "approve"]

_UNCERTAINTY_POLICY_TO_DECISION: dict[UncertaintyPolicy, DecisionType] = {
    "ask": DecisionType.STEP_UP,
    "decline": DecisionType.DECLINE,
    "approve": DecisionType.APPROVE,
}


def combine(
    results: Sequence[CheckResult],
    uncertainty_policy: UncertaintyPolicy,
    engine_version: str,
) -> Decision:
    """Aggregate `results` into a `Decision` per the precedence rules above."""
    contributing = [r for r in results if r.verdict is not Verdict.PASS]

    reason_codes: list[str] = []
    evidence: list[Evidence] = []
    for result in contributing:
        if result.reason_code is not None and result.reason_code not in reason_codes:
            reason_codes.append(result.reason_code)
        evidence.extend(result.evidence)

    any_fail = any(r.verdict is Verdict.FAIL for r in results)
    any_uncertain = any(r.verdict is Verdict.UNCERTAIN for r in results)

    if any_fail:
        decision_type = DecisionType.DECLINE
        customer_message = _first_message(contributing, Verdict.FAIL) or (
            "This purchase does not meet the wallet policy's requirements."
        )
    elif any_uncertain:
        decision_type = _UNCERTAINTY_POLICY_TO_DECISION[uncertainty_policy]
        customer_message = _first_message(contributing, Verdict.UNCERTAIN) or (
            "This purchase needs a closer look before it can be approved."
        )
    else:
        decision_type = DecisionType.APPROVE
        reason_codes = [reasons.NO_CONCERNS]
        customer_message = "This purchase meets all checks and was approved."

    return Decision(
        decision=decision_type,
        reason_codes=tuple(reason_codes),
        customer_message=customer_message,
        evidence=tuple(evidence),
        engine_version=engine_version,
    )


def _first_message(results: Sequence[CheckResult], verdict: Verdict) -> str | None:
    for result in results:
        if result.verdict is verdict:
            return result.message
    return None
