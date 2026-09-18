"""The engine's entry point: `decide(event, state, facts) -> Decision`.

Runs the deterministic check tier first. If it already aggregates to a
`decline` (any check `FAIL`s), the semantic tier is skipped entirely -- see
`checks/__init__.py` for why. Otherwise both tiers run and their results are
combined together.
"""

from __future__ import annotations

from engine.aggregate import combine
from engine.checks import DETERMINISTIC_CHECKS, SEMANTIC_CHECKS
from engine.types import (
    AuthorizationEvent,
    CheckResult,
    Decision,
    EngineState,
    ExtractedFacts,
    Verdict,
)

ENGINE_VERSION = "engine/0.1.0"


def decide(
    event: AuthorizationEvent,
    state: EngineState,
    facts: ExtractedFacts | None = None,
) -> Decision:
    """Decide `approve` / `decline` / `step_up` for one proposed purchase.

    Pure function of its inputs: no I/O, no Django, no network, no LLM call
    (an LLM, if used, runs outside this function and its output is passed in
    as `facts`).
    """
    deterministic_results: list[CheckResult] = [
        check(event, state, facts) for check in DETERMINISTIC_CHECKS
    ]

    if any(result.verdict is Verdict.FAIL for result in deterministic_results):
        return combine(deterministic_results, event.mandate.uncertainty_policy, ENGINE_VERSION)

    semantic_results: list[CheckResult] = [check(event, state, facts) for check in SEMANTIC_CHECKS]
    return combine(
        deterministic_results + semantic_results,
        event.mandate.uncertainty_policy,
        ENGINE_VERSION,
    )
