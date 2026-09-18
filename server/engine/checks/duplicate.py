"""Repeated delivery of the same authorization, and near-duplicate orders.

Deterministic tier: no LLM, no network, no randomness.

Two distinct situations, per the challenge brief's step 8:

- The *same* `authorization_id` delivered again (a retried poll/response) is
  not a new purchase and must not be double-counted; this check recognises
  it and passes it through quietly (the caller is responsible for not
  re-adding the amount to its own bookkeeping -- see `EngineState.
  seen_authorization_ids`).
- A *different* `authorization_id` that otherwise looks like the same order
  (same merchant, same amount, overlapping items, close in time) can still
  be an unwanted duplicate order and is surfaced as UNCERTAIN so the
  customer can confirm, rather than declined outright -- it may simply be a
  legitimate repeat purchase.

`_NEAR_DUPLICATE_WINDOW` is a scaffold heuristic (not derived from the data
pack, which carries no duplicate-order labels).
"""

from __future__ import annotations

from datetime import timedelta

from engine import reasons
from engine.types import AuthorizationEvent, CheckResult, EngineState, Evidence, Verdict

_NEAR_DUPLICATE_WINDOW = timedelta(hours=2)


def check(
    event: AuthorizationEvent, state: EngineState, facts: object | None = None
) -> CheckResult:
    if event.authorization_id in state.seen_authorization_ids:
        return CheckResult(
            verdict=Verdict.PASS,
            reason_code=None,
            message="This is a repeated delivery of an authorization already recorded.",
            evidence=(
                Evidence(
                    field="authorization.authorization_id",
                    value=event.authorization_id,
                    note="retry of a previously seen authorization_id; not double-counted",
                ),
            ),
        )

    current_categories = {item.item_category for item in event.items}
    for prior in state.recent_approved_purchases:
        if prior.merchant_id != event.merchant.merchant_id:
            continue
        if prior.billing_amount_chf != event.billing_amount_chf:
            continue
        if not (set(prior.item_categories) & current_categories):
            continue
        if abs(event.timestamp - prior.timestamp) > _NEAR_DUPLICATE_WINDOW:
            continue
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.DUPLICATE_SUSPECTED_ORDER,
            message="This purchase closely resembles one already approved recently.",
            evidence=(
                Evidence(
                    field="authorization.authorization_id",
                    value=event.authorization_id,
                    note=(
                        f"same merchant, same CHF amount, overlapping item categories as "
                        f"previously approved '{prior.authorization_id}' at "
                        f"{prior.timestamp.isoformat()}"
                    ),
                ),
            ),
        )

    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="No repeated or near-duplicate order detected.",
        evidence=(),
    )
