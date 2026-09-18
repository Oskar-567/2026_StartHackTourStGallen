"""Tests for `engine.aggregate.combine`: the aggregation precedence table
and the mandate's `uncertainty_policy` in all three settings.
"""

from __future__ import annotations

import pytest

from engine.aggregate import combine
from engine.types import CheckResult, DecisionType, Evidence, Verdict

_EV = Evidence(field="x", value=1, note="n")

_PASS = CheckResult(verdict=Verdict.PASS, reason_code=None, message="ok")
_FAIL = CheckResult(verdict=Verdict.FAIL, reason_code="some_fail", message="bad", evidence=(_EV,))
_UNCERTAIN = CheckResult(
    verdict=Verdict.UNCERTAIN, reason_code="some_uncertain", message="unsure", evidence=(_EV,)
)


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([_PASS, _PASS], DecisionType.APPROVE),
        ([_PASS, _UNCERTAIN], DecisionType.STEP_UP),  # ask policy in this test
        ([_PASS, _FAIL], DecisionType.DECLINE),
        ([_FAIL, _UNCERTAIN], DecisionType.DECLINE),  # FAIL beats UNCERTAIN
        ([_FAIL, _FAIL], DecisionType.DECLINE),
        ([_UNCERTAIN, _UNCERTAIN], DecisionType.STEP_UP),
    ],
)
def test_precedence_table_with_ask_policy(results, expected):
    decision = combine(results, "ask", "engine/test")
    assert decision.decision == expected


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("ask", DecisionType.STEP_UP),
        ("decline", DecisionType.DECLINE),
        ("approve", DecisionType.APPROVE),
    ],
)
def test_uncertainty_policy_all_three_settings(policy, expected):
    decision = combine([_PASS, _UNCERTAIN], policy, "engine/test")
    assert decision.decision == expected


def test_fail_always_declines_regardless_of_uncertainty_policy():
    for policy in ("ask", "decline", "approve"):
        decision = combine([_FAIL], policy, "engine/test")
        assert decision.decision == DecisionType.DECLINE


def test_collects_reason_codes_and_evidence_from_every_contributing_check():
    other_fail = CheckResult(
        verdict=Verdict.FAIL,
        reason_code="other_fail",
        message="also bad",
        evidence=(Evidence(field="y", value=2, note="n2"),),
    )
    decision = combine([_FAIL, other_fail, _PASS], "ask", "engine/test")
    assert set(decision.reason_codes) == {"some_fail", "other_fail"}
    assert len(decision.evidence) == 2


def test_all_pass_has_no_concerns_reason_code():
    decision = combine([_PASS, _PASS], "ask", "engine/test")
    assert decision.decision == DecisionType.APPROVE
    assert decision.reason_codes == ("no_concerns",)
    assert decision.evidence == ()


def test_to_api_payload_shape():
    decision = combine([_FAIL], "ask", "engine/test-1.0")
    payload = decision.to_api_payload()
    assert set(payload.keys()) == {
        "decision",
        "reason_codes",
        "customer_message",
        "evidence",
        "engine_version",
    }
    assert payload["decision"] == "decline"
    assert payload["engine_version"] == "engine/test-1.0"
    assert payload["evidence"] == [{"field": "x", "value": 1, "note": "n"}]
