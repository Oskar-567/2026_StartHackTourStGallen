"""STUB -- semantic check: does this purchase fit the customer's stated purpose?

Not yet implemented. The customer's `mandate.instruction` (e.g. "buy black
running shoes for up to CHF 200") expresses an intent that goes beyond what
any single hard rule can encode -- whether a purchase is actually the kind
of thing the customer meant needs semantic understanding of the instruction
together with the purchase's facts (`ExtractedFacts`), not just its
structured fields.

Once implemented, this check will compare `facts.purpose_fit_assessment`
(and `facts.purpose_fit_confidence`) against `event.mandate.instruction`,
and PASS/FAIL/UNCERTAIN accordingly.

TODO: implement once an LLM-based purpose-fit assessment exists outside the
engine and populates `ExtractedFacts`.

Semantic tier: today this is a pure function of `facts is None`, so it is
still deterministic and side-effect-free, but it belongs in the semantic
tier because its real implementation will depend on LLM-extracted facts.
"""

from __future__ import annotations

from engine import reasons
from engine.types import (
    AuthorizationEvent,
    CheckResult,
    EngineState,
    Evidence,
    ExtractedFacts,
    Verdict,
)


def check(
    event: AuthorizationEvent, state: EngineState, facts: ExtractedFacts | None = None
) -> CheckResult:
    return CheckResult(
        verdict=Verdict.UNCERTAIN,
        reason_code=reasons.PURPOSE_FIT_FACTS_UNAVAILABLE,
        message="Purpose-fit assessment is not yet implemented; treating as uncertain.",
        evidence=(
            Evidence(
                field="facts",
                value=None,
                note="purpose_fit is a stub: no ExtractedFacts-based comparison exists yet",
            ),
        ),
    )
