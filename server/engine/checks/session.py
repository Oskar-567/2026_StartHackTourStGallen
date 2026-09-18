"""Device novelty, velocity, and channel signals.

Deterministic tier: no LLM, no network, no randomness.

Thresholds (`_VELOCITY_FAIL_THRESHOLD`, `_VELOCITY_UNCERTAIN_THRESHOLD`) are
scaffold heuristics, not derived from the data pack's distribution -- there
is no labelled answer key to fit them against. They exist so the engine
behaves predictably out of the box; tune them once real scenario behaviour
is observed.
"""

from __future__ import annotations

from engine import reasons
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict

_DEVICE_EXPECTED_CHANNELS = {"ecommerce", "recurring", "mobile_wallet"}
_VELOCITY_FAIL_THRESHOLD = 5
_VELOCITY_UNCERTAIN_THRESHOLD = 3


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    fail_evidence: list[Evidence] = []
    uncertain_evidence: list[Evidence] = []
    fail_reason: str | None = None
    uncertain_reason: str | None = None

    # An AI shopping agent (initiator_type is always "agent" on these events)
    # withdrawing cash at an ATM is not a purchase; treat as a hard mismatch.
    if event.channel == "atm":
        fail_reason = reasons.SESSION_CHANNEL_UNEXPECTED
        fail_evidence.append(
            Evidence(
                field="authorization.channel",
                value=event.channel,
                note="an agent-initiated ATM withdrawal is not an expected purchase channel",
            )
        )

    if event.recent_attempt_count_10m >= _VELOCITY_FAIL_THRESHOLD:
        if fail_reason is None:
            fail_reason = reasons.SESSION_VELOCITY_HIGH
        fail_evidence.append(
            Evidence(
                field="authorization.recent_attempt_count_10m",
                value=event.recent_attempt_count_10m,
                note=f"{event.recent_attempt_count_10m} attempts in the last 10 minutes",
            )
        )
    elif event.recent_attempt_count_10m >= _VELOCITY_UNCERTAIN_THRESHOLD:
        uncertain_reason = reasons.SESSION_VELOCITY_ELEVATED
        uncertain_evidence.append(
            Evidence(
                field="authorization.recent_attempt_count_10m",
                value=event.recent_attempt_count_10m,
                note=f"{event.recent_attempt_count_10m} attempts in the last 10 minutes",
            )
        )

    device_expected = event.channel in _DEVICE_EXPECTED_CHANNELS
    if device_expected:
        if not event.customer_device_id:
            uncertain_reason = uncertain_reason or reasons.SESSION_NEW_DEVICE
            uncertain_evidence.append(
                Evidence(
                    field="authorization.customer_device_id",
                    value=event.customer_device_id,
                    note=f"no device id supplied for a {event.channel} purchase",
                )
            )
        elif state.known_device_ids.get(event.customer_device_id, 0) <= 0:
            uncertain_reason = uncertain_reason or reasons.SESSION_NEW_DEVICE
            uncertain_evidence.append(
                Evidence(
                    field="authorization.customer_device_id",
                    value=event.customer_device_id,
                    note="no prior approved purchase from this device on this card",
                )
            )

    if fail_reason is not None:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=fail_reason,
            message="This purchase's session signals are outside expected bounds.",
            evidence=tuple(fail_evidence + uncertain_evidence),
        )
    if uncertain_reason is not None:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=uncertain_reason,
            message="This purchase's session signals need a closer look.",
            evidence=tuple(uncertain_evidence),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="Device, velocity, and channel signals are unremarkable.",
        evidence=(),
    )
