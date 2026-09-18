"""End-to-end tests for `engine.decide.decide`.

No database, no Django test marks -- `decide()` is a pure function of
`(event, state, facts)`.
"""

from __future__ import annotations

from engine.decide import decide
from engine.reasons import (
    AMOUNT_LIMIT_EXCEEDED,
    ITEM_MATCH_FACTS_UNAVAILABLE,
    PURPOSE_FIT_FACTS_UNAVAILABLE,
)
from engine.types import DecisionType, EngineState

_CLEAN_AUTH_OVERRIDES = {"order_returnable": "true", "order_cancellable": "true"}


def _clean_state() -> EngineState:
    """A state under which every deterministic check on the base fixture event PASSes."""
    return EngineState(
        known_merchant_ids={"ME_TEST_0001": 3},
        known_device_ids={"DVC-TEST": 2},
    )


def test_decide_declines_and_skips_semantic_tier_when_deterministic_fails(event_factory):
    event = event_factory(
        authorization={"billing_amount_chf": 999.0},
        mandate={
            "hard_rules": [
                {"field": "authorization.billing_amount_chf", "operator": "<=", "value": 20}
            ]
        },
    )
    decision = decide(event, EngineState())

    assert decision.decision == DecisionType.DECLINE
    assert AMOUNT_LIMIT_EXCEEDED in decision.reason_codes
    # The semantic tier must not have run: its stub reason codes must be absent.
    assert ITEM_MATCH_FACTS_UNAVAILABLE not in decision.reason_codes
    assert PURPOSE_FIT_FACTS_UNAVAILABLE not in decision.reason_codes


def test_decide_steps_up_when_deterministic_passes_but_facts_are_missing(event_factory):
    event = event_factory(
        authorization=_CLEAN_AUTH_OVERRIDES, mandate={"uncertainty_policy": "ask"}
    )
    decision = decide(event, _clean_state())

    # All deterministic checks pass, but the semantic stubs always return
    # UNCERTAIN without ExtractedFacts, so "ask" resolves to step_up.
    assert decision.decision == DecisionType.STEP_UP
    assert ITEM_MATCH_FACTS_UNAVAILABLE in decision.reason_codes
    assert PURPOSE_FIT_FACTS_UNAVAILABLE in decision.reason_codes


def test_decide_approves_when_uncertainty_policy_is_approve(event_factory):
    event = event_factory(
        authorization=_CLEAN_AUTH_OVERRIDES, mandate={"uncertainty_policy": "approve"}
    )
    decision = decide(event, _clean_state())
    assert decision.decision == DecisionType.APPROVE


def test_decide_declines_when_uncertainty_policy_is_decline(event_factory):
    event = event_factory(
        authorization=_CLEAN_AUTH_OVERRIDES, mandate={"uncertainty_policy": "decline"}
    )
    decision = decide(event, _clean_state())
    assert decision.decision == DecisionType.DECLINE


def test_decide_ignores_scenario_id_and_replay_order(event_factory):
    """Two events identical except for scenario_id/replay_order must decide identically."""
    state = _clean_state()
    event_a = event_factory(
        authorization={**_CLEAN_AUTH_OVERRIDES, "scenario_id": "SCEN0001", "replay_order": 1}
    )
    event_b = event_factory(
        authorization={**_CLEAN_AUTH_OVERRIDES, "scenario_id": "SCEN0004", "replay_order": 9}
    )

    decision_a = decide(event_a, state)
    decision_b = decide(event_b, state)

    assert decision_a.decision == decision_b.decision
    assert decision_a.reason_codes == decision_b.reason_codes
    assert decision_a.customer_message == decision_b.customer_message
