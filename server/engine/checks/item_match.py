"""Semantic check: is this actually the thing the customer asked for?

Some of what a customer says cannot be checked by comparing numbers. "Size
43", "road-running shoes", "a 27-inch monitor" are claims about the product,
and the only place that information exists is free text the merchant wrote:
`item_name` and `item_details`.

That text is untrusted. So this check never reads it. Instead it compares two
things that are already structured:

- `mandate.intent_spec.required_attributes` -- what the customer requires,
  derived from their own words and confirmed by them. Trusted.
- `facts.items[].attributes` -- what an extractor read out of the merchant's
  text, outside the engine, as plain key/value pairs. Untrusted in origin, but
  reduced to values that cannot carry an instruction.

The extractor that produces those facts never sees the customer's policy, so
merchant text telling it to "ignore the spending limit" is addressed to
something that holds no limits and grants no permissions. Whatever it says,
the comparison below still happens in code.

Verdicts:

- **FAIL** -- an attribute was extracted and contradicts what the customer
  required. Size 44 against a required size 43 is a definite mismatch, and so
  is a 7-day return window against a required minimum of 14.
- **UNCERTAIN** -- no facts at all, or the required attribute simply was not
  found in the merchant's text. Absence is not agreement.
- **PASS** -- every required attribute was found and matches.

A mandate with no `required_attributes` has nothing to check here, so it
passes rather than manufacturing doubt -- the same rule `checks/terms.py`
follows: a check may only speak about what the policy actually asks for.

Semantic tier: depends on `ExtractedFacts`, which an LLM step produces outside
this package. The function itself stays pure.
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


def _as_number(value: str | None) -> float | None:
    """The leading number in an extracted value, or None if there isn't one.

    Extractors are told to return digits only, but a stray "30 days" should
    still be usable. Anything genuinely unreadable returns None, which becomes
    UNCERTAIN -- a question for the customer, never a silent pass.
    """
    if value is None:
        return None
    digits = ""
    for character in value.strip():
        if character.isdigit() or (character == "." and "." not in digits):
            digits += character
        elif digits:
            break
        else:
            return None
    try:
        return float(digits)
    except ValueError:
        return None


def _normalise(value: str) -> str:
    """Compare attributes case- and whitespace-insensitively.

    "EU 43" and "eu  43" are the same size; nothing here tries to be cleverer
    than that. Real normalisation (units, synonyms) belongs in the extractor,
    which has the context to do it -- not in the comparison.
    """
    return " ".join(value.lower().split())


def check(
    event: AuthorizationEvent, state: EngineState, facts: ExtractedFacts | None = None
) -> CheckResult:
    intent = event.mandate.intent_spec

    if intent is None or not (intent.required_attributes or intent.minimum_attributes):
        return CheckResult(
            verdict=Verdict.PASS,
            reason_code=None,
            message="The customer's policy names no required item attributes.",
            evidence=(),
        )

    if facts is None:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.ITEM_MATCH_FACTS_UNAVAILABLE,
            message="The requested item's details could not be read, so this needs a look.",
            evidence=(
                Evidence(
                    field="facts",
                    value=None,
                    note=(
                        "no extracted facts available; required attributes "
                        f"{sorted({**intent.required_attributes, **intent.minimum_attributes})} "
                        "could not be confirmed"
                    ),
                ),
            ),
        )

    mismatches: list[Evidence] = []
    unknowns: list[Evidence] = []

    for item in event.items:
        item_facts = facts.for_line(item.line_no)
        for attribute, required in intent.required_attributes.items():
            found = None if item_facts is None else item_facts.attributes.get(attribute)
            if found is None:
                unknowns.append(
                    Evidence(
                        field=f"items[{item.line_no}].{attribute}",
                        value=None,
                        note=(
                            f"the customer requires {attribute}={required!r}, but the shop "
                            f"supplied nothing we could read it from (facts source: {facts.source})"
                        ),
                    )
                )
            elif _normalise(found) != _normalise(required):
                mismatches.append(
                    Evidence(
                        field=f"items[{item.line_no}].{attribute}",
                        value=found,
                        note=(
                            f"the customer requires {attribute}={required!r}, "
                            f"but this item is {found!r}"
                        ),
                    )
                )

        for attribute, minimum in intent.minimum_attributes.items():
            found = None if item_facts is None else item_facts.attributes.get(attribute)
            value = _as_number(found)
            if value is None:
                unknowns.append(
                    Evidence(
                        field=f"items[{item.line_no}].{attribute}",
                        value=found,
                        note=(
                            f"the customer requires {attribute} of at least {minimum:g}, but "
                            f"the shop supplied {'nothing readable' if found is None else found!r}"
                        ),
                    )
                )
            elif value < minimum:
                mismatches.append(
                    Evidence(
                        field=f"items[{item.line_no}].{attribute}",
                        value=found,
                        note=(
                            f"the customer requires {attribute} of at least {minimum:g}, "
                            f"but this item offers {value:g}"
                        ),
                    )
                )

    if mismatches:
        return CheckResult(
            verdict=Verdict.FAIL,
            reason_code=reasons.ITEM_MATCH_ATTRIBUTE_MISMATCH,
            message="This is not the item the customer asked for.",
            evidence=tuple(mismatches + unknowns),
        )
    if unknowns:
        return CheckResult(
            verdict=Verdict.UNCERTAIN,
            reason_code=reasons.ITEM_MATCH_ATTRIBUTE_UNKNOWN,
            message="The shop did not say enough to confirm this is the right item.",
            evidence=tuple(unknowns),
        )
    return CheckResult(
        verdict=Verdict.PASS,
        reason_code=None,
        message="The item matches what the customer asked for.",
        evidence=(),
    )
