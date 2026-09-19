"""Hand-written reference policies for the public scenarios.

One structured policy per scenario instruction: the `hard_rules` sent to the
challenge API, `uncertainty_policy`, and the `intent_spec` only our engine
reads. They stand in for the policy compiler that does not exist yet, and they
are shared so that `replay` (offline) and `create_mandate` (live) evaluate
exactly the same policy.

Keyed by scenario only to pick the instruction a policy was written for. The
engine never sees the scenario ID; it is discarded at parse time.
"""

from __future__ import annotations

from typing import Any

REFERENCE_POLICIES: dict[str, dict[str, Any]] = {
    "SCEN0000": {
        "instruction": (
            "Buy one ordinary grocery item for CHF 20 or less from a shop I use regularly. "
            "Ask me when uncertain."
        ),
        "hard_rules": [
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 20,
                "currency": "CHF",
                "scope": "purchase",
            },
        ],
        "uncertainty_policy": "ask",
        "intent_spec": {
            "purpose": "one ordinary grocery item",
            "allowed_item_categories": ["groceries"],
            # "Buy one ordinary grocery item" -- one item, not a standing order.
            "fulfilment": "single",
        },
    },
    "SCEN0001": {
        "instruction": (
            "Order our household groceries for delivery. Keep each order at or below CHF 120 "
            "including delivery, and keep the total across any seven days at or below CHF 300. "
            "Ask me when uncertain."
        ),
        "hard_rules": [
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 120,
                "currency": "CHF",
                "scope": "purchase",
            },
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 300,
                "currency": "CHF",
                "scope": "period",
                "period_days": 7,
            },
        ],
        "uncertainty_policy": "ask",
        "intent_spec": {
            "purpose": "household groceries for delivery",
            "allowed_item_categories": ["groceries"],
            # "Order our household groceries" -- this repeats by nature.
            "fulfilment": "recurring",
        },
    },
    "SCEN0002": {
        "instruction": (
            "Replace my worn road-running shoes in size 43. Buy only from a specialist sports "
            "retailer, only if the order can be returned within 14 days or more, and pay no "
            "more than CHF 200. Ask me when uncertain."
        ),
        "hard_rules": [
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 200,
                "currency": "CHF",
                "scope": "purchase",
            },
            # The other half of "only if the order can be returned": the platform's
            # own structured field. `false` is a definite no; `unknown` means the
            # shop said nothing and resolves to a question, not a refusal.
            {
                "field": "authorization.order_returnable",
                "operator": "=",
                "value": "true",
                "scope": "purchase",
            },
            # "Buy only from a specialist sports retailer": the shop's own category,
            # a structured platform field -- not something read from merchant text.
            {
                "field": "authorization.merchant.merchant_category",
                "operator": "in",
                "value": ["sporting_goods"],
                "scope": "purchase",
            },
        ],
        "uncertainty_policy": "ask",
        "intent_spec": {
            "purpose": "replacement road-running shoes in size 43",
            "allowed_item_categories": ["sporting_goods"],
            # The stand-in extractor cannot read a size out of free text, so this
            # stays UNCERTAIN until the real extractor lands -- which is exactly
            # the gap it is meant to make visible.
            "required_attributes": {"size": "43"},
            # "only if the order can be returned within 14 days or more"
            "minimum_attributes": {"return_days": 14},
            # "Replace my worn road-running shoes" -- one pair, not a subscription.
            "fulfilment": "single",
            # ...and road-running, so a trail-running shoe is a substitute to ask about.
            "item_type": "road-running shoe",
        },
    },
    "SCEN0003": {
        "instruction": (
            "The agent may buy clothing for me, up to CHF 250 per order, from shops I have used "
            "before. Pause anything that looks like someone other than me is driving the "
            "session. Ask me when uncertain."
        ),
        "hard_rules": [
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 250,
                "currency": "CHF",
                "scope": "purchase",
            },
        ],
        "uncertainty_policy": "ask",
    },
    "SCEN0004": {
        "instruction": (
            "Buy the 27-inch monitor I chose, from a seller I have bought from before, for CHF "
            "400 or less. Do not add anything I did not ask for. Ask me when uncertain."
        ),
        "hard_rules": [
            {
                "field": "authorization.billing_amount_chf",
                "operator": "<=",
                "value": 400,
                "currency": "CHF",
                "scope": "purchase",
            },
        ],
        "uncertainty_policy": "ask",
    },
}
