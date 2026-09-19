"""Has the customer already got what they asked for?

"Replace my worn road-running shoes" is a request for one pair. An agent that
proposes six plausible pairs, each within budget, each the right size, breaks no
rule we have written -- and the customer ends up with six pairs of shoes.

Nothing in a per-purchase limit catches that, because nothing about the sixth
purchase is wrong on its own. What is wrong is that the purpose was already
served by the first.

**This check speaks only when the policy says the purpose is a one-off.**
`IntentSpec.fulfilment` is `"single"` for "replace my shoes", `"recurring"` for
"order our groceries", and `None` when nobody established which -- in which case
this check stays silent rather than inventing a restriction the customer never
expressed. Guessing here is expensive in both directions: treat a weekly grocery
order as a one-off and you interrupt someone every week.

The verdict is **UNCERTAIN, never FAIL**. The system does not know whether the
customer wants a second pair; it knows only that they have one. Under
`uncertainty_policy: "ask"` that becomes a step-up, which is the honest answer
to a question the system genuinely cannot settle. Declining would presume, and
approving would be the negligence this check exists to prevent.

Deterministic tier: no LLM, no network. It compares the purpose the customer
stated against purchases this run has already approved. The categories it reads
are the merchant's own -- good enough to raise a question, and never used here
to approve anything.
"""

from __future__ import annotations

from engine import reasons
from engine.types import (
    AuthorizationEvent,
    CheckResult,
    EngineState,
    Evidence,
    Verdict,
)

_PASS = CheckResult(
    verdict=Verdict.PASS,
    reason_code=None,
    message="Nothing already approved covers what this purchase is for.",
    evidence=(),
)


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    intent = event.mandate.intent_spec
    if intent is None or intent.fulfilment != "single":
        return _PASS
    if not intent.allowed_item_categories:
        return _PASS

    purpose = {category.lower() for category in intent.allowed_item_categories}

    # Does this purchase even serve that purpose? If it does not, `purpose_fit`
    # is the check with something to say about it, not this one.
    here = {item.item_category.lower() for item in event.items if item.item_category}
    if not (here & purpose):
        return _PASS

    for prior in state.recent_approved_purchases:
        earlier = {category.lower() for category in prior.item_categories if category}
        if not (earlier & purpose):
            continue
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.PURPOSE_ALREADY_FULFILLED,
            message="The customer already has what they asked for.",
            evidence=(
                Evidence(
                    field="mandate.intent_spec.purpose",
                    value=intent.purpose or None,
                    note=(
                        f"{prior.purchase_description or prior.authorization_id!r} was already "
                        f"approved at {prior.timestamp.isoformat()} for this same purpose; the "
                        "customer asked for it once"
                    ),
                ),
            ),
        )

    return _PASS
