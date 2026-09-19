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

**A new shop the customer's own rules vouch for is not a question.** When the
mandate names what kind of merchant is allowed ("only a specialist sports
retailer" -> a rule on `authorization.merchant.merchant_category`) and this
merchant satisfies every such rule, "we have not bought here before" adds
nothing the customer has not already answered. Asking anyway would step up the
very purchase the brief describes as "an unfamiliar but fully compliant
seller". Lookalike names and an unfamiliar country still raise UNCERTAIN: a
category rule says nothing about either.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from engine import reasons
from engine.checks._hard_rule_engine import evaluate_rule, rule_scope
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict

_LOOKALIKE_RATIO_THRESHOLD = 0.82


def _merchant_vouched_for_by_policy(event: AuthorizationEvent) -> bool:
    """True when the mandate constrains the merchant and this one meets every constraint.

    Only purchase-scoped rules on `authorization.merchant.*` count. A rule that
    cannot be evaluated counts as not met -- vouching must be definite.
    """
    merchant_rules = [
        rule
        for rule in event.mandate.hard_rules
        if rule.field.startswith("authorization.merchant.") and rule_scope(rule) == "purchase"
    ]
    return bool(merchant_rules) and all(
        evaluate_rule(event, rule)[0] is True for rule in merchant_rules
    )


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
    if unfamiliar_merchant and not unfamiliar_country and _merchant_vouched_for_by_policy(event):
        return CheckResult(
            verdict=Verdict.PASS,
            reason_code=None,
            message=(
                "New merchant on this card, but it meets every merchant rule the customer set."
            ),
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
