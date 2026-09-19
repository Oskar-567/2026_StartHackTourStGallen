/**
 * Plain-language rendering of mandate hard rules, so the customer can check what the
 * wallet will actually enforce. Unknown fields fall back to the raw rule rather than
 * hiding it: a rule the customer cannot see is a rule they did not agree to.
 */
import type { HardRule, UncertaintyPolicy } from "@/services/api";

const FIELD_LABELS: Record<string, string> = {
  "authorization.billing_amount_chf": "Purchase total",
  "authorization.amount": "Purchase amount",
  "authorization.items_subtotal": "Basket subtotal",
  "authorization.delivery_fee": "Delivery fee",
  "authorization.channel": "Payment channel",
  "authorization.order_returnable": "Order can be returned",
  "authorization.order_cancellable": "Order can be cancelled",
  "authorization.merchant.merchant_category": "Kind of shop",
  "authorization.merchant.merchant_id": "Shop",
  "authorization.merchant.merchant_country": "Shop country",
  "authorization.merchant.merchant_mcc": "Shop category code",
  "authorization.items.item_category": "Every item's category",
  "authorization.items[].item_category": "Every item's category",
};

const OPERATOR_WORDS: Record<HardRule["operator"], string> = {
  "<": "less than",
  "<=": "at most",
  "=": "must be",
  "!=": "must not be",
  ">": "more than",
  ">=": "at least",
  in: "must be one of",
  not_in: "must not be",
};

function formatValue(rule: HardRule): string {
  const { value } = rule;
  if (Array.isArray(value)) return value.map(humanize).join(", ");
  if (typeof value === "number") {
    return rule.currency ? `${rule.currency} ${value.toFixed(2)}` : String(value);
  }
  return humanize(value);
}

function humanize(value: string): string {
  if (value === "true") return "yes";
  if (value === "false") return "no";
  return value.replaceAll("_", " ");
}

export function describeRule(rule: HardRule): string {
  const label = FIELD_LABELS[rule.field] ?? rule.field;
  const window =
    rule.scope === "period"
      ? rule.period_days
        ? ` (all purchases within ${rule.period_days} days)`
        : " (all purchases in the period)"
      : "";
  return `${label}${window} ${OPERATOR_WORDS[rule.operator]} ${formatValue(rule)}`;
}

export const UNCERTAINTY_DESCRIPTIONS: Record<UncertaintyPolicy, string> = {
  ask: "When the wallet is unsure, it pauses the purchase and asks you.",
  decline: "When the wallet is unsure, it declines the purchase.",
  approve: "When the wallet is unsure, it lets the purchase through.",
};

/** The per-purchase spending limit in CHF, if the policy has one. */
export function purchaseLimitChf(rules: HardRule[]): number | null {
  const limits = rules
    .filter(
      (rule) =>
        rule.field === "authorization.billing_amount_chf" &&
        (rule.operator === "<=" || rule.operator === "<") &&
        (rule.scope ?? "purchase") === "purchase" &&
        typeof rule.value === "number",
    )
    .map((rule) => rule.value as number);
  return limits.length ? Math.min(...limits) : null;
}
