"""Reason-code string constants, grouped by the check that emits them.

Reason codes are stable strings sent to the customer-facing app and to the
challenge API's `reason_codes` field. Keep them short, snake_case, and
grouped here so a check never invents an ad-hoc string inline.
"""

# -- Generic hard-rule interpretation (checks/amount.py, checks/period.py) --
HARD_RULE_UNKNOWN_FIELD = "hard_rule_unknown_field"
HARD_RULE_UNINTERPRETABLE = "hard_rule_uninterpretable"
HARD_RULE_VALUE_UNKNOWN = "hard_rule_value_unknown"
# The field a rule targets resolved to the literal string "unknown"
# (information the merchant/platform did not supply) -- distinct from a
# `null` field (HARD_RULE_UNINTERPRETABLE) and from "not_applicable", which
# is a known, legitimate value and never uses this code.

# -- checks/amount.py: mandate hard_rules with scope="purchase" (default) --
# The failing rule's field picks the code, so a shop outside the customer's
# chosen kind of retailer is not reported as a spending-limit breach.
AMOUNT_LIMIT_EXCEEDED = "amount_limit_exceeded"
AMOUNT_RULE_UNCERTAIN = "amount_rule_uncertain"
MERCHANT_NOT_PERMITTED = "merchant_not_permitted"
HARD_RULE_VIOLATED = "hard_rule_violated"

# -- checks/period.py: mandate hard_rules with scope="period" --
PERIOD_LIMIT_EXCEEDED = "period_limit_exceeded"
PERIOD_RULE_UNSUPPORTED_FIELD = "period_rule_unsupported_field"
PERIOD_WINDOW_UNVERIFIED = "period_window_unverified"
"""A period rule was evaluated against a running total whose window we
cannot confirm matches the window the rule names (see checks/period.py).
Neither a match nor a violation is provable, so this is never a FAIL."""
PERIOD_RULE_UNCERTAIN = "period_rule_uncertain"

# -- checks/merchant.py --
MERCHANT_UNFAMILIAR = "merchant_unfamiliar"
MERCHANT_COUNTRY_UNFAMILIAR = "merchant_country_unfamiliar"
MERCHANT_LOOKALIKE_NAME = "merchant_lookalike_name"

# -- checks/session.py --
SESSION_NEW_DEVICE = "session_new_device"
SESSION_VELOCITY_HIGH = "session_velocity_high"
SESSION_VELOCITY_ELEVATED = "session_velocity_elevated"
SESSION_CHANNEL_UNEXPECTED = "session_channel_unexpected"

# -- checks/duplicate.py --
DUPLICATE_RETRY_SAME_ID = "duplicate_retry_same_id"
DUPLICATE_SUSPECTED_ORDER = "duplicate_suspected_order"

# -- checks/terms.py --
TERMS_RETURN_STATUS_UNKNOWN = "terms_return_status_unknown"
TERMS_NON_REVERSIBLE = "terms_non_reversible"

# -- checks/item_match.py (stub) --
ITEM_MATCH_FACTS_UNAVAILABLE = "item_match_facts_unavailable"
ITEM_MATCH_ATTRIBUTE_MISMATCH = "item_match_attribute_mismatch"
ITEM_MATCH_ATTRIBUTE_UNKNOWN = "item_match_attribute_unknown"
ITEM_MATCH_BELOW_MINIMUM = "item_match_below_minimum"
ITEM_MATCH_POSSIBLE_SUBSTITUTE = "item_match_possible_substitute"

# -- checks/purpose_fit.py (stub) --
PURPOSE_FIT_FACTS_UNAVAILABLE = "purpose_fit_facts_unavailable"
PURPOSE_FIT_UNREQUESTED_ITEM = "purpose_fit_unrequested_item"
PURPOSE_FIT_CATEGORY_UNKNOWN = "purpose_fit_category_unknown"
PURPOSE_FIT_CATEGORY_UNVERIFIED = "purpose_fit_category_unverified"
PURPOSE_ALREADY_FULFILLED = "purpose_already_fulfilled"

# -- aggregate.py: no check fired anything notable --
NO_CONCERNS = "no_concerns"
