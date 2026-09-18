"""Merchant familiarity, country, and lookalike-name distance.

Deterministic tier: no LLM, no network, no randomness. Every signal here is
graded, not absolute -- per the challenge data dictionary, "no device,
merchant, category, date, channel, or currency alone determines an
outcome." This check therefore never returns FAIL by itself; it only ever
raises UNCERTAIN (deferring to the mandate's `uncertainty_policy`) or PASS.
A merchant being unfamiliar is not automatically wrong (unfamiliar purchases
are not automatically wrong, per the challenge brief), but it is a fact
worth surfacing.

The data dictionary also warns that "at least one pair of merchants has
deliberately similar names" -- i.e. two *legitimate* merchants can look
alike -- so a close name match raises UNCERTAIN (ask the customer), never a
hard FAIL, to avoid punishing a genuine near-namesake merchant.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from engine import reasons
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict

_LOOKALIKE_RATIO_THRESHOLD = 0.82


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    evidence: list[Evidence] = []

    familiar_count = state.known_merchant_ids.get(event.merchant.merchant_id, 0)
    unfamiliar_merchant = familiar_count <= 0
    if unfamiliar_merchant:
        evidence.append(
            Evidence(
                field="authorization.merchant.merchant_id",
                value=event.merchant.merchant_id,
                note="no prior approved purchase at this merchant on this card",
            )
        )

    known_countries = {p.merchant_country for p in state.recent_approved_purchases}
    unfamiliar_country = bool(known_countries) and event.merchant.merchant_country not in (
        known_countries
    )
    if unfamiliar_country:
        evidence.append(
            Evidence(
                field="authorization.merchant.merchant_country",
                value=event.merchant.merchant_country,
                note=(
                    f"no prior approved purchase in this country; known: {sorted(known_countries)}"
                ),
            )
        )

    lookalike_name: str | None = None
    for prior in state.recent_approved_purchases:
        if prior.merchant_id == event.merchant.merchant_id:
            continue
        ratio = SequenceMatcher(
            None, prior.merchant_name.lower(), event.merchant.merchant_name.lower()
        ).ratio()
        if ratio >= _LOOKALIKE_RATIO_THRESHOLD:
            lookalike_name = prior.merchant_name
            evidence.append(
                Evidence(
                    field="authorization.merchant.merchant_name",
                    value=event.merchant.merchant_name,
                    note=(
                        f"name is {ratio:.0%} similar to previously used merchant "
                        f"'{prior.merchant_name}' (different merchant_id)"
                    ),
                )
            )
            break

    if lookalike_name is not None:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.MERCHANT_LOOKALIKE_NAME,
            message="This merchant's name closely resembles one the customer has used before.",
            evidence=tuple(evidence),
        )
    if unfamiliar_merchant or unfamiliar_country:
        reason_code = (
            reasons.MERCHANT_UNFAMILIAR
            if unfamiliar_merchant
            else reasons.MERCHANT_COUNTRY_UNFAMILIAR
        )
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reason_code,
            message="This merchant (or country) has no prior approved history on this card.",
            evidence=tuple(evidence),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="Merchant is familiar.",
        evidence=(),
    )
