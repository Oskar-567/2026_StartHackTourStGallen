/**
 * Customer-facing labels for the engine's reason codes (server/engine/reasons.py).
 * Unknown codes fall back to the code itself, so a new server code never breaks the screen.
 */
const LABELS: Record<string, string> = {
  amount_limit_exceeded: "Over your spending limit",
  amount_rule_uncertain: "Spending limit could not be checked",
  period_limit_exceeded: "Over your limit for this period",
  period_window_unverified: "Period limit could not be verified",
  merchant_not_permitted: "Shop type you did not allow",
  merchant_unfamiliar: "Shop not used before",
  merchant_country_unfamiliar: "Shop in a new country",
  merchant_lookalike_name: "Name looks like a shop you use",
  merchant_text_instruction: "Shop tried to instruct the wallet",
  session_new_device: "Unknown device",
  session_velocity_high: "Unusually many attempts",
  session_velocity_elevated: "Several attempts in a short time",
  session_channel_unexpected: "Unexpected payment channel",
  duplicate_retry_same_id: "Repeated request",
  duplicate_suspected_order: "Possible duplicate order",
  terms_return_status_unknown: "Return terms not stated",
  terms_non_reversible: "Cannot be returned or cancelled",
  hard_rule_violated: "Breaks one of your rules",
  hard_rule_uninterpretable: "A rule could not be checked",
  hard_rule_value_unknown: "Shop did not supply required information",
  item_match_facts_unavailable: "Item details could not be read",
  item_match_attribute_mismatch: "Not the item you asked for",
  item_match_attribute_unknown: "Item details incomplete",
  item_match_possible_substitute: "Possibly a substitute",
  purpose_fit_facts_unavailable: "Purpose could not be confirmed",
  purpose_fit_unrequested_item: "Contains something you did not ask for",
  purpose_fit_category_unknown: "Part of the basket unidentified",
  purpose_already_fulfilled: "You already have what you asked for",
  customer_confirmation: "Needs your confirmation",
  engine_error: "Automatic check could not complete",
};

export function reasonLabel(code: string): string {
  return LABELS[code] ?? code.replaceAll("_", " ");
}
