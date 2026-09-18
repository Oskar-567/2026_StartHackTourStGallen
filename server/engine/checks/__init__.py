"""The check registry: two ordered tiers, deterministic then semantic.

Every check is a callable `(event, state, facts) -> CheckResult`. All checks
share this signature -- deterministic checks simply ignore `facts` -- so
callers can run either tier uniformly.

**Ordering matters for cost, not for correctness.** `DETERMINISTIC_CHECKS`
run first: they are pure computation over the event, `EngineState`, and the
mandate's `hard_rules` -- no LLM call, no network, effectively free and
instant. `SEMANTIC_CHECKS` run second and are expected to depend on
`ExtractedFacts` produced by an LLM step outside this package, which is the
slow and potentially-unavailable part of the pipeline.

`decide.py` runs `DETERMINISTIC_CHECKS` first and, if that tier already
aggregates to a FAIL (see `aggregate.combine`), **skips the semantic tier
entirely** -- a purchase that is already going to be declined on
deterministic grounds does not need an LLM call to confirm it. When the
deterministic tier does not FAIL, `decide.py` also runs `SEMANTIC_CHECKS`
before aggregating the combined result. This keeps the common "obviously
fine" and "obviously against the rules" cases fast, and only pays for
semantic analysis on purchases where it can actually change the outcome.
"""

from __future__ import annotations

from collections.abc import Callable

from engine.checks import (
    amount,
    duplicate,
    item_match,
    merchant,
    period,
    purpose_fit,
    session,
    terms,
)
from engine.types import AuthorizationEvent, CheckResult, EngineState, ExtractedFacts

Check = Callable[[AuthorizationEvent, EngineState, ExtractedFacts | None], CheckResult]

DETERMINISTIC_CHECKS: tuple[Check, ...] = (
    amount.check,
    period.check,
    merchant.check,
    session.check,
    duplicate.check,
    terms.check,
)

SEMANTIC_CHECKS: tuple[Check, ...] = (
    item_match.check,
    purpose_fit.check,
)

__all__ = ["Check", "DETERMINISTIC_CHECKS", "SEMANTIC_CHECKS"]
