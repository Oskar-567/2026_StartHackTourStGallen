"""STUB -- semantic check: does the merchant's item match what it claims to be?

Not yet implemented. `item_details` (and `item_name`) are untrusted,
merchant-supplied text (see `Item.item_details`); confirming that a cart
line actually is what it claims to be -- for example, that "black running
shoes" really are black running shoes and not a bait-and-switch, or that a
stated size/colour in `item_details` matches `item_name` -- needs semantic
understanding an LLM would provide (`ExtractedFacts`), not string matching.

Once implemented, this check will compare `facts.items_match_description`
(and `facts.item_match_notes`) against the claimed `item_name` /
`item_category` for each `event.items` line, and PASS/FAIL/UNCERTAIN
accordingly. It must still never let `item_details` itself change a limit
or a decision path -- only the *extracted, structured* facts may be
compared.

TODO: implement once an LLM-based fact-extraction step exists outside the
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
        reason_code=reasons.ITEM_MATCH_FACTS_UNAVAILABLE,
        message="Item-content matching is not yet implemented; treating as uncertain.",
        evidence=(
            Evidence(
                field="facts",
                value=None,
                note="item_match is a stub: no ExtractedFacts-based comparison exists yet",
            ),
        ),
    )
