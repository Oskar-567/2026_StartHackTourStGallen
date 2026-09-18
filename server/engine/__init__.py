"""Pure-Python decision engine for the "Agent on a Leash" wallet control layer.

`server/engine/` has no Django imports, no ORM access, no network calls, and
no direct LLM calls: it is a pure function of `(event, state, facts) ->
decision`. Django models, the Viseca HTTP client, and any LLM calls live
outside this package and pass plain data in. This is what makes the package
unit-testable without a database and replayable offline over the challenge
CSV fixtures.

Public API:

    from engine import decide, Decision, DecisionType, Verdict
"""

from __future__ import annotations

from engine.decide import decide
from engine.types import Decision, DecisionType, Verdict

__all__ = ["decide", "Decision", "DecisionType", "Verdict"]
