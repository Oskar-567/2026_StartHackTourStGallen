"""Readable terminal output for a live demo (`run_worker --pretty`, `manage.py demo`).

The worker's normal log is key=value lines for developers. On a projector the
audience needs something else: one block per purchase with the shop, the
amount, the decision in colour and the reason in plain words -- and the shop's
own words when it tried to instruct the wallet. Presentation only: nothing here
influences a decision.
"""

from __future__ import annotations

import os
import sys
import textwrap
from collections import Counter
from datetime import datetime
from typing import TextIO

from django.utils import timezone

from api.models import AuthorizationRecord, Mandate
from api.services import event_payload
from engine.types import AuthorizationEvent
from engine.types import Decision as EngineDecision

WIDTH = 78

# Mirrors app/src/services/reasons.ts so the terminal and the phone say the same thing.
REASON_LABELS: dict[str, str] = {
    "amount_limit_exceeded": "over your spending limit",
    "period_limit_exceeded": "over your limit for this period",
    "merchant_not_permitted": "a kind of shop you did not allow",
    "merchant_unfamiliar": "shop not used before",
    "merchant_country_unfamiliar": "shop in a new country",
    "merchant_lookalike_name": "name looks like a shop you use",
    "merchant_text_instruction": "shop tried to instruct the wallet",
    "session_new_device": "unknown device",
    "session_velocity_high": "unusually many attempts",
    "session_velocity_elevated": "several attempts in a short time",
    "session_channel_unexpected": "unexpected payment channel",
    "duplicate_retry_same_id": "repeated request",
    "duplicate_suspected_order": "possible duplicate order",
    "terms_return_status_unknown": "return terms not stated",
    "terms_non_reversible": "cannot be returned or cancelled",
    "hard_rule_violated": "breaks one of your rules",
    "hard_rule_uninterpretable": "a rule could not be checked",
    "item_match_facts_unavailable": "item details could not be read",
    "item_match_attribute_mismatch": "not the item you asked for",
    "item_match_attribute_unknown": "item details incomplete",
    "item_match_possible_substitute": "possibly a substitute",
    "purpose_fit_facts_unavailable": "purpose could not be confirmed",
    "purpose_fit_unrequested_item": "something you did not ask for",
    "purpose_fit_category_unknown": "not independently confirmed",
    "purpose_already_fulfilled": "you already have what you asked for",
    "engine_error": "automatic check could not complete",
}

_FIELD_LABELS: dict[str, str] = {
    "authorization.billing_amount_chf": "purchase total",
    "authorization.order_returnable": "returnable",
    "authorization.merchant.merchant_category": "kind of shop",
}
_OPERATORS: dict[str, str] = {
    "<=": "at most",
    "<": "under",
    ">=": "at least",
    ">": "over",
    "=": "must be",
    "!=": "must not be",
    "in": "one of",
    "not_in": "none of",
}


def _enable_ansi_on_windows() -> bool:
    """Turn on colour escape codes in a Windows console; harmless elsewhere."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001 - colour is a nicety, never a failure
        return False


def describe_rule(rule: dict) -> str:
    """One hard rule in plain words, e.g. 'purchase total at most CHF 200'."""
    label = _FIELD_LABELS.get(rule.get("field", ""), rule.get("field", ""))
    value = rule.get("value")
    if isinstance(value, list):
        shown = ", ".join(str(v).replace("_", " ") for v in value)
    elif isinstance(value, int | float) and rule.get("currency"):
        shown = f"{rule['currency']} {value:g}"
    else:
        shown = {"true": "yes", "false": "no"}.get(str(value), str(value))
    return f"{label} {_OPERATORS.get(rule.get('operator', ''), rule.get('operator', ''))} {shown}"


def _is_readable(note: str) -> bool:
    """Evidence a judge can read as-is; rule syntax and internal field lists are not."""
    technical = ("hard rule '", "reason_code=", "required attributes", "facts source:")
    return not any(marker in note for marker in technical)


def _shorten(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."


class DemoOutput:
    """Prints the run as a story: header, one block per purchase, a closing summary."""

    def __init__(self, stream: TextIO | None = None, color: bool | None = None) -> None:
        self.out = stream or sys.stdout
        reconfigure = getattr(self.out, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
        if color is None:
            color = (
                getattr(self.out, "isatty", lambda: False)()
                and not os.environ.get("NO_COLOR")
                and _enable_ansi_on_windows()
            )
        self.color = color
        self.engine_counts: Counter[str] = Counter()
        self.customer_counts: Counter[str] = Counter()

    # -- building blocks ------------------------------------------------

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def _print(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def _rule(self, char: str = "─") -> None:
        self._print(self._c("2", char * WIDTH))

    @staticmethod
    def _clock(moment: datetime | None = None) -> str:
        return timezone.localtime(moment or timezone.now()).strftime("%H:%M:%S")

    # -- the story ------------------------------------------------------

    def header(self, scenario_id: str, mandate: Mandate, facts_backend: str, run_id: str) -> None:
        self._print()
        self._print(self._c("1", "━━━ Agent on a Leash · live demo " + "━" * (WIDTH - 33)))
        self._print(f"{self._c('2', 'Scenario ')} {scenario_id}")
        self._print(f'{self._c("2", "Customer ")} "{_shorten(mandate.instruction, WIDTH - 12)}"')
        for index, rule in enumerate(mandate.hard_rules):
            label = "Rules    " if index == 0 else "         "
            self._print(f"{self._c('2', label)} {describe_rule(rule)}")
        when_unsure = {"ask": "ask the customer", "decline": "decline", "approve": "approve"}
        self._print(
            f"{self._c('2', 'Unsure   ')} "
            f"{when_unsure.get(mandate.uncertainty_policy, mandate.uncertainty_policy)}"
        )
        self._print(f"{self._c('2', 'Facts    ')} {facts_backend}")
        self._print(f"{self._c('2', 'Run      ')} {run_id} · waiting for the agent's purchases")
        self._rule()

    def decision(
        self,
        event: AuthorizationEvent,
        decision: EngineDecision,
        seconds: float,
        facts_note: str | None = None,
    ) -> None:
        value = decision.decision.value
        self.engine_counts[value] += 1
        badge = {
            "approve": self._c("1;32", "✔ APPROVE"),
            "decline": self._c("1;31", "✖ DECLINE"),
            "step_up": self._c("1;33", "? ASK    "),
        }.get(value, value)
        shop = _shorten(event.merchant.merchant_name, 20).ljust(20)
        amount = f"CHF {event.billing_amount_chf:,.2f}".replace(",", "'").rjust(13)
        tail = self._c("33", "  → on the phone") if value == "step_up" else ""
        self._print(
            f"{self._clock()}  {shop}{amount}   {badge}  {self._c('2', f'{seconds:.2f} s')}{tail}"
        )

        items = " + ".join(f"{item.quantity} × {item.item_name}" for item in event.items)
        self._print(f"          {self._c('2', _shorten(items, WIDTH - 10))}")
        if facts_note:
            color = "33" if facts_note.startswith("no facts") else "36"
            self._print(f"          {self._c(color, _shorten(facts_note, WIDTH - 10))}")

        if value == "approve":
            self._print(f"          {self._c('32', 'every rule met, nothing uncertain')}")
        else:
            reasons = [
                REASON_LABELS.get(code, code.replace("_", " ")) for code in decision.reason_codes
            ]
            for line in textwrap.wrap(" · ".join(reasons), WIDTH - 10):
                self._print(f"          {line}")
            quote = next(
                (e for e in decision.evidence if e.note.startswith("the shop's text")), None
            )
            if quote is not None:
                self._print(f"          {self._c('1;33', '⚠ the shop wrote:')}")
                for line in textwrap.wrap(f'"{str(quote.value).strip(".")}"', WIDTH - 12)[:4]:
                    self._print(f"            {self._c('33', line)}")
            else:
                readable = next((e.note for e in decision.evidence if _is_readable(e.note)), None)
                if readable:
                    self._print(f"          {self._c('2', _shorten(readable, WIDTH - 10))}")
        self._print()

    def resolution(self, authorization: AuthorizationRecord, value: str) -> None:
        self.customer_counts[value] += 1
        data = event_payload(authorization.raw_event).get("authorization", {})
        shop = data.get("merchant", {}).get("merchant_name", "the shop")
        amount = f"CHF {authorization.billing_amount_chf:,.2f}".replace(",", "'")
        verdict = (
            self._c("1;32", "✔ customer approved")
            if value == "approve"
            else self._c("1;31", "✖ customer declined")
        )
        self._print(f"{self._clock()}  {verdict} {shop} {amount} → sent to Viseca")
        self._print()

    def summary(self, counters: dict) -> None:
        self._rule()
        engine = self.engine_counts
        self._print(
            self._c("1", "Wallet   ")
            + f"{engine['approve']} approved · {engine['decline']} declined · "
            f"{engine['step_up']} asked the customer"
        )
        answered = self.customer_counts["approve"] + self.customer_counts["decline"]
        if engine["step_up"]:
            self._print(
                self._c("1", "Customer ") + f"{self.customer_counts['approve']} approved · "
                f"{self.customer_counts['decline']} declined · "
                f"{max(engine['step_up'] - answered, 0)} left unanswered (never paid)"
            )
        if counters:
            self._print(
                self._c("1", "Viseca   ")
                + f"{counters.get('approved', 0)} approved · {counters.get('declined', 0)} declined"
                f" · {counters.get('timed_out', 0)} timed out · run complete"
            )
        self._print(self._c("1", "━" * WIDTH))
