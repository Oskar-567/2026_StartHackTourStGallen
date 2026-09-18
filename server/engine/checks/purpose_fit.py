"""Semantic check: does everything in the basket belong to what was asked for?

This is the check that catches the quiet failure mode. A customer says "order
our household groceries"; the basket contains groceries and a pair of
headphones. Every number is within limits. Nothing is fraudulent. It is simply
not what they asked for.

It compares the category of each cart line against
`mandate.intent_spec.allowed_item_categories` -- the categories the customer's
own instruction implies, established when their policy was compiled and
confirmed by them.

Where the category comes from matters. `Item.item_category` is supplied by the
merchant, and a merchant that wants an item waved through can label anything
"groceries". So the check prefers the category an extractor read independently
(`facts.items[].category`) and only falls back to the merchant's own claim
when there is nothing better -- saying so in the evidence either way, since a
decision resting on the seller's self-description deserves to be visible as
such.

Verdicts:

- **FAIL** -- a cart line's category is outside what the customer asked for.
  This holds even when the only category available is the merchant's own: a
  seller saying their item is outside the customer's purpose settles it.
- **UNCERTAIN** -- no facts, no intent spec, no stated categories, a line whose
  category nobody could determine, or a line that fits **only according to the
  merchant**. Confirming a basket on the word of the party selling it is the
  shortcut this check exists to prevent.
- **PASS** -- every line was read independently and belongs to the purpose.

The asymmetry is the point. An unverified category can convict but not
acquit. It also means that when fact extraction is unavailable, this check
degrades to asking the customer rather than quietly trusting the shop --
which is the behaviour the rest of the system promises.

Semantic tier: depends on `ExtractedFacts`, produced outside this package.
"""

from __future__ import annotations

from engine import reasons
from engine.types import (
    AuthorizationEvent,
    CheckResult,
    EngineState,
    Evidence,
    ExtractedFacts,
    Verdict,
)


def check(
    event: AuthorizationEvent, state: EngineState, facts: ExtractedFacts | None = None
) -> CheckResult:
    intent = event.mandate.intent_spec

    if intent is None or not intent.allowed_item_categories:
        # The customer never said which categories belong to this purchase, so
        # there is nothing to compare a basket against. That is a gap in the
        # policy, not a clean basket -- hence UNCERTAIN rather than PASS.
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.PURPOSE_FIT_FACTS_UNAVAILABLE,
            message="The purpose of this purchase could not be confirmed.",
            evidence=(
                Evidence(
                    field="mandate.intent_spec.allowed_item_categories",
                    value=None,
                    note="the policy does not state which item categories fit this purpose",
                ),
            ),
        )

    allowed = {category.lower() for category in intent.allowed_item_categories}
    offending: list[Evidence] = []
    unknowns: list[Evidence] = []

    for item in event.items:
        item_facts = None if facts is None else facts.for_line(item.line_no)
        verified = item_facts is not None and item_facts.category_verified
        extracted = None if item_facts is None else item_facts.category
        category = extracted if extracted else item.item_category

        if not category:
            unknowns.append(
                Evidence(
                    field=f"items[{item.line_no}].item_category",
                    value=None,
                    note=f"no category could be determined for {item.item_name!r}",
                )
            )
            continue

        if category.lower() not in allowed:
            # A seller saying their own item is outside the customer's purpose
            # settles it, whether or not we read the category independently.
            offending.append(
                Evidence(
                    field=f"items[{item.line_no}].item_category",
                    value=category,
                    note=(
                        f"{item.item_name!r} is a {category!r} item, which is outside the "
                        f"customer's stated purpose ({sorted(allowed)})"
                        + ("" if verified else " -- category as claimed by the merchant")
                    ),
                )
            )
        elif not verified:
            # It fits -- but only according to the seller. Confirming a basket
            # on the word of the party selling it is exactly the shortcut this
            # check exists to prevent, so this is a question, not approval.
            unknowns.append(
                Evidence(
                    field=f"items[{item.line_no}].item_category",
                    value=category,
                    note=(
                        f"{item.item_name!r} is within the stated purpose according to the "
                        "merchant, but nothing read it independently; "
                        f"reason_code={reasons.PURPOSE_FIT_CATEGORY_UNVERIFIED}"
                    ),
                )
            )

    if offending:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=reasons.PURPOSE_FIT_UNREQUESTED_ITEM,
            message="The basket contains something the customer did not ask for.",
            evidence=tuple(offending + unknowns),
        )
    if unknowns:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.PURPOSE_FIT_CATEGORY_UNKNOWN,
            message="Part of this basket could not be identified.",
            evidence=tuple(unknowns),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="Everything in the basket fits what the customer asked for.",
        evidence=(),
    )
