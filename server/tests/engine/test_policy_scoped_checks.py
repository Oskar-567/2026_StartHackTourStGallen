"""Regression tests: a check may only speak up about what the policy asks for.

Two bugs found by replaying the public scenarios offline:

1. `checks/terms.py` raised UNCERTAIN whenever a merchant supplied no return
   terms -- even for a grocery order under a policy that never mentions
   returns. That turns ordinary shopping into `step_up`, which the challenge
   brief counts as a failure in its own right.
2. `checks/period.py` compared a period rule against the caller's own running
   total when the rule omitted `period_days`, silently inventing a window.
"""

from __future__ import annotations

from decimal import Decimal

from engine.checks import period, terms
from engine.types import Verdict

_RETURNABLE_RULE = {
    "field": "authorization.order_returnable",
    "operator": "=",
    "value": "true",
    "scope": "purchase",
}
_PERIOD_RULE_NO_DAYS = {
    "field": "authorization.billing_amount_chf",
    "operator": "<=",
    "value": 300,
    "currency": "CHF",
    "scope": "period",
}


class TestTermsIsPolicyScoped:
    def test_unknown_terms_pass_when_the_policy_never_asks(
        self, event_factory, empty_state
    ) -> None:
        event = event_factory(
            authorization={"order_returnable": "unknown", "order_cancellable": "unknown"},
            mandate={"hard_rules": []},
        )
        assert terms.check(event, empty_state).verdict is Verdict.PASS

    def test_unknown_terms_are_uncertain_when_the_policy_does_ask(
        self, event_factory, empty_state
    ) -> None:
        event = event_factory(
            authorization={"order_returnable": "unknown", "order_cancellable": "true"},
            mandate={"hard_rules": [_RETURNABLE_RULE]},
        )
        result = terms.check(event, empty_state)
        assert result.verdict is Verdict.UNCERTAIN
        assert result.evidence

    def test_irreversible_order_passes_when_the_policy_never_asks(
        self, event_factory, empty_state
    ) -> None:
        event = event_factory(
            authorization={"order_returnable": "false", "order_cancellable": "false"},
            mandate={"hard_rules": []},
        )
        assert terms.check(event, empty_state).verdict is Verdict.PASS


class TestPeriodWindowMustBeVerifiable:
    def test_callers_own_total_is_uncertain_never_pass(self, event_factory, empty_state) -> None:
        """No `period_days` and no platform counter: the window is unknown."""
        event = event_factory(
            mandate={"hard_rules": [_PERIOD_RULE_NO_DAYS]},
            context={"approved_spend_in_period_chf": None},
        )
        state = type(empty_state)(approved_spend_in_period_chf=Decimal("10.00"))
        result = period.check(event, state)
        assert result.verdict is Verdict.UNCERTAIN, "an unverified window must not PASS"

    def test_callers_own_total_is_uncertain_even_when_it_exceeds_the_limit(
        self, event_factory, empty_state
    ) -> None:
        """A monthly total over the cap does not prove a seven-day total is."""
        event = event_factory(
            mandate={"hard_rules": [_PERIOD_RULE_NO_DAYS]},
            context={"approved_spend_in_period_chf": None},
        )
        state = type(empty_state)(approved_spend_in_period_chf=Decimal("5000.00"))
        result = period.check(event, state)
        assert result.verdict is Verdict.UNCERTAIN, "an unverified window must not FAIL either"

    def test_platform_counter_is_trusted(self, event_factory, empty_state) -> None:
        event = event_factory(
            mandate={"hard_rules": [_PERIOD_RULE_NO_DAYS]},
            context={"approved_spend_in_period_chf": 10.0},
        )
        assert period.check(event, empty_state).verdict is Verdict.PASS
