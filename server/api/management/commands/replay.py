"""Offline replay of a scenario's purchase attempts against the engine.

No API key, no network: reads `purchase_attempts.csv`, joined with
`purchase_attempt_items.csv` and `merchants.csv`, plus `authorization_history.
csv` for the card's prior approved merchants and devices, from the local
challenge data pack (`VISECA_DATA_DIR`, see `config/settings.py`). Familiarity
is counted with `api.services.familiarity_from_rows`, the same rule the worker
applies to the history the API serves, so offline and live agree. Rows are
sorted by
`replay_order`, turned into live-event-shaped dicts, parsed with the same
`engine.parsing.parse_event` the worker uses, and run through `engine.decide`
one at a time -- carrying engine state (seen ids, familiarity, approved
purchases) forward exactly the way the worker would across a run.

This is the team's main iteration loop for the engine, so its output is a
readable per-purchase table, not just a dump of raw decisions.

The scenario's cardholder instruction (`scenario_catalogue.csv`) is not run
through a natural-language policy compiler here -- that is a different
concern (see `api/services.create_mandate_draft`, which takes an
already-structured policy). `_SCENARIO_POLICIES` below is a small, explicit,
hand-written reference policy per public scenario capturing only the
instruction's numeric limits, so this command has something to evaluate
against offline. Item/shop/terms requirements the instructions mention are
intentionally left to the engine's semantic tier, which correctly resolves
UNCERTAIN (and therefore `step_up` under `uncertainty_policy=ask`) without
LLM-extracted facts -- replay never fabricates those.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.services import familiarity_from_rows
from engine.decide import decide
from engine.parsing import EventParsingError, parse_event
from engine.types import (
    ApprovedPurchase,
    DecisionType,
    EngineState,
    ExtractedFacts,
    ItemFacts,
)

_SCENARIO_POLICIES: dict[str, dict[str, Any]] = {
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
        ],
        "uncertainty_policy": "ask",
        "intent_spec": {
            "purpose": "replacement road-running shoes in size 43",
            "allowed_item_categories": ["sporting_goods"],
            # The stand-in extractor cannot read a size out of free text, so this
            # stays UNCERTAIN until the real extractor lands -- which is exactly
            # the gap it is meant to make visible.
            "required_attributes": {"size": "43"},
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


class ReplayError(Exception):
    """Raised on any row/CSV/event-parsing failure; the command exits non-zero."""


def _num_or_none(value: str) -> float | None:
    value = (value or "").strip()
    return None if value == "" else float(value)


def _int_value(value: str, *, field: str) -> int:
    value = (value or "").strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ReplayError(f"{field}={value!r} is not an integer") from exc


def _str_or_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _stand_in_facts(event: dict) -> ExtractedFacts:
    """Facts built from the CSV's already-structured fields, as a placeholder.

    This is NOT the real extractor and is not meant to become it. The real one
    (see docs/NEXT-STEPS.md, P0-2) reads `item_details` and `item_name` with a
    language model and can therefore recover attributes like a shoe size.

    This stand-in only repeats `item_category`, which the merchant supplied. It
    exists to prove the whole path works -- intent spec in, facts in, semantic
    checks comparing, a decision out -- before any model is wired up. Because
    it invents nothing, every attribute stays unknown, and purchases whose
    policy requires one still resolve to `step_up`. That is the honest answer
    and it marks precisely where the model is needed.
    """
    return ExtractedFacts(
        items=tuple(
            ItemFacts(line_no=item["line_no"], category=item["item_category"] or None)
            for item in event["authorization"]["items"]
        ),
        source="csv-stand-in",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ReplayError(f"missing data file: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass
class ReplayState:
    """Carried forward across purchases within one replay run, mirroring what
    `api.services.build_engine_state` assembles from the ORM in production."""

    seen_ids: set[str]
    known_merchant_ids: dict[str, int]
    known_device_ids: dict[str, int]
    approved_purchases: list[ApprovedPurchase]
    approved_total_chf: Decimal

    @classmethod
    def seeded(cls, merchant_counts: dict[str, int], device_counts: dict[str, int]) -> ReplayState:
        """Start a replay from the card's prior approved history.

        Familiarity has to be seeded, not started empty: an instruction like
        "from a shop I use regularly" is unanswerable without the history the
        production worker also loads, and a cold start makes every merchant
        look unfamiliar -- which turns the whole replay into `step_up` and
        hides whether the engine is being correctly cautious or just blind.
        """
        return cls(set(), dict(merchant_counts), dict(device_counts), [], Decimal("0"))

    def as_engine_state(self) -> EngineState:
        return EngineState(
            approved_spend_in_period_chf=self.approved_total_chf,
            seen_authorization_ids=frozenset(self.seen_ids),
            known_merchant_ids=dict(self.known_merchant_ids),
            known_device_ids=dict(self.known_device_ids),
            recent_approved_purchases=tuple(self.approved_purchases),
        )

    def record(self, event: dict, decision_type: DecisionType) -> None:
        auth = event["authorization"]
        self.seen_ids.add(auth["authorization_id"])
        if decision_type is not DecisionType.APPROVE:
            return
        merchant = auth["merchant"]
        purchase = ApprovedPurchase(
            authorization_id=auth["authorization_id"],
            timestamp=datetime.fromisoformat(auth["timestamp"].replace("Z", "+00:00")),
            merchant_id=merchant["merchant_id"],
            merchant_name=merchant["merchant_name"],
            merchant_country=merchant["merchant_country"],
            device_id=auth["customer_device_id"] or "",
            billing_amount_chf=auth["billing_amount_chf"],  # Decimal, set by _build_event
            purchase_description=auth["purchase_description"],
            item_categories=tuple(item["item_category"] for item in auth["items"]),
        )
        self.approved_purchases.append(purchase)
        self.approved_total_chf += purchase.billing_amount_chf
        if purchase.merchant_id:
            self.known_merchant_ids[purchase.merchant_id] = (
                self.known_merchant_ids.get(purchase.merchant_id, 0) + 1
            )
        if purchase.device_id:
            self.known_device_ids[purchase.device_id] = (
                self.known_device_ids.get(purchase.device_id, 0) + 1
            )


def _build_event(
    row: dict[str, str],
    items: list[dict[str, str]],
    merchant: dict[str, str],
    *,
    scenario_id: str,
    policy: dict[str, Any],
    mandate_snapshot: dict[str, str],
) -> dict:
    authorization_id = row["authorization_id"]
    request_id = f"replay-{authorization_id}"
    deadline_at = (datetime.now(UTC) + timedelta(seconds=8)).isoformat().replace("+00:00", "Z")

    item_dicts = [
        {
            "line_no": _int_value(item["line_no"], field="line_no"),
            "item_id": item["item_id"],
            "item_name": item["item_name"],
            "item_category": item["item_category"],
            "quantity": _int_value(item["quantity"], field="quantity"),
            "unit_price": _num_or_none(item["unit_price"]),
            "currency": item["currency"],
            "item_details": item["item_details"],
        }
        for item in items
    ]

    event = {
        "type": "authorization.request",
        "request_id": request_id,
        "deadline_at": deadline_at,
        "authorization": {
            "authorization_id": authorization_id,
            "source_authorization_id": authorization_id,
            "scenario_id": scenario_id,
            "replay_order": _int_value(row["replay_order"], field="replay_order"),
            "mandate_id": mandate_snapshot["mandate_id"],
            "profile_id": mandate_snapshot["profile_id"],
            "card_id": row["card_id"],
            "merchant": {
                "merchant_id": merchant["merchant_id"],
                "merchant_name": merchant["merchant_name"],
                "merchant_category": merchant["merchant_category"],
                "merchant_mcc": merchant["merchant_mcc"],
                "merchant_country": merchant["merchant_country"],
                "merchant_city": merchant["merchant_city"],
                "availability": merchant["availability"],
                "recurring_capable": merchant["recurring_capable"],
            },
            "timestamp": row["timestamp"],
            "amount": _num_or_none(row["amount"]),
            "currency": row["currency"],
            "billing_amount_chf": _num_or_none(row["billing_amount_chf"]),
            "items_subtotal": _num_or_none(row["items_subtotal"]),
            "delivery_fee": _num_or_none(row["delivery_fee"]),
            "channel": row["channel"],
            "customer_device_id": row["customer_device_id"],
            "authority_status": row["authority_status"],
            "card_status_at_attempt": row["card_status_at_attempt"],
            "spend_in_period_before_chf": _num_or_none(row["spend_in_period_before_chf"]),
            "recent_attempt_count_10m": _int_value(
                row["recent_attempt_count_10m"], field="recent_attempt_count_10m"
            ),
            "fulfillment_method": row["fulfillment_method"],
            "delivery_by": _str_or_none(row["delivery_by"]),
            "order_returnable": row["order_returnable"],
            "order_cancellable": row["order_cancellable"],
            "related_authorization_id": _str_or_none(row["related_authorization_id"]),
            "related_authorization_status": _str_or_none(row["related_authorization_status"]),
            "purchase_description": row["purchase_description"],
            "items": item_dicts,
        },
        "mandate": mandate_snapshot
        | {
            "hard_rules": policy["hard_rules"],
            # Caller-supplied: the live event never carries this (see types.Mandate).
            "intent_spec": policy.get("intent_spec"),
        },
        "context": {"approved_spend_in_period_chf": None, "recent_authorizations": []},
        "runtime": {
            "received_at": deadline_at,
            "history_window_minutes": 10,
            "context_basis": "run_decisions_and_scenario_timestamps",
        },
    }
    return event


def _format_row(
    replay_order: int,
    authorization_id: str,
    merchant_name: str,
    amount_chf: str,
    decision_type: str,
    reason_codes: list[str],
    running_total: Decimal,
) -> str:
    return (
        f"{replay_order:>3}  {authorization_id:<10} {merchant_name[:22]:<22} "
        f"CHF {amount_chf:>8}  {decision_type.upper():<8} "
        f"running=CHF {running_total:>9.2f}  {', '.join(reason_codes)}"
    )


class Command(BaseCommand):
    help = (
        "Offline replay of a scenario's purchase attempts against the engine "
        "(no network, no API key)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--scenario", dest="scenario_id", default="SCEN0000")

    def handle(self, *args, **options) -> None:
        scenario_id = options["scenario_id"]
        policy = _SCENARIO_POLICIES.get(scenario_id)
        if policy is None:
            raise CommandError(
                f"No reference policy for {scenario_id!r}; known scenarios: "
                f"{sorted(_SCENARIO_POLICIES)}"
            )

        data_dir_value = getattr(settings, "VISECA_DATA_DIR", "") or ""
        if not data_dir_value:
            raise CommandError("VISECA_DATA_DIR is not set (see server/.env.example).")
        data_dir = Path(data_dir_value)

        try:
            attempts = _read_csv(data_dir / "purchase_attempts.csv")
            item_rows = _read_csv(data_dir / "purchase_attempt_items.csv")
            merchant_rows = _read_csv(data_dir / "merchants.csv")
        except ReplayError as exc:
            raise CommandError(str(exc)) from exc

        history_path = data_dir / "authorization_history.csv"
        if history_path.exists():
            history_rows = _read_csv(history_path)
        else:
            history_rows = []
            self.stderr.write(
                f"WARNING: {history_path.name} not found; every merchant and device will look "
                "unfamiliar and most purchases will resolve to step_up."
            )

        scenario_rows = [row for row in attempts if row["scenario_id"] == scenario_id]
        if not scenario_rows:
            raise CommandError(f"No purchase_attempts.csv rows for scenario {scenario_id!r}.")
        try:
            scenario_rows.sort(
                key=lambda row: _int_value(row["replay_order"], field="replay_order")
            )
        except ReplayError as exc:
            raise CommandError(str(exc)) from exc

        items_by_auth: dict[str, list[dict[str, str]]] = defaultdict(list)
        for item in item_rows:
            items_by_auth[item["authorization_id"]].append(item)
        for auth_id in items_by_auth:
            items_by_auth[auth_id].sort(key=lambda i: _int_value(i["line_no"], field="line_no"))

        merchants_by_id = {row["merchant_id"]: row for row in merchant_rows}

        first_row = scenario_rows[0]
        mandate_snapshot = {
            "mandate_id": f"REPLAY-{scenario_id}",
            "status": "active",
            "customer_id": "",
            "card_id": first_row["card_id"],
            "instruction": policy["instruction"],
            "uncertainty_policy": policy["uncertainty_policy"],
            "profile_id": f"REPLAY-{first_row['authority_id']}",
        }

        card_id = first_row["card_id"]
        merchant_counts, device_counts = familiarity_from_rows(history_rows, card_id)

        self.stdout.write(f"Replaying {scenario_id} ({len(scenario_rows)} purchases)")
        self.stdout.write(f"Instruction: {policy['instruction']}")
        self.stdout.write(
            f"Prior history for card {card_id}: {len(merchant_counts)} known merchant(s), "
            f"{len(device_counts)} known device(s)."
        )
        self.stdout.write("-" * 100)

        state = ReplayState.seeded(merchant_counts, device_counts)
        exit_code = 0
        for row in scenario_rows:
            authorization_id = row["authorization_id"]
            try:
                merchant = merchants_by_id[row["merchant_id"]]
            except KeyError as exc:
                raise CommandError(
                    f"{authorization_id}: unknown merchant_id {row['merchant_id']!r}"
                ) from exc

            try:
                event_dict = _build_event(
                    row,
                    items_by_auth.get(authorization_id, []),
                    merchant,
                    scenario_id=scenario_id,
                    policy=policy,
                    mandate_snapshot=mandate_snapshot,
                )
                parsed = parse_event(event_dict)
            except (ReplayError, EventParsingError) as exc:
                self.stderr.write(
                    self.style.ERROR(f"{authorization_id}: failed to build/parse event: {exc}")
                )
                exit_code = 1
                continue

            engine_state = state.as_engine_state()
            result = decide(parsed, engine_state, _stand_in_facts(event_dict))

            # parse_event already validated this dict; swap in the Decimal it
            # parsed so ReplayState.record carries an exact amount forward.
            event_dict["authorization"]["billing_amount_chf"] = parsed.billing_amount_chf
            state.record(event_dict, result.decision)

            self.stdout.write(
                _format_row(
                    _int_value(row["replay_order"], field="replay_order"),
                    authorization_id,
                    merchant["merchant_name"],
                    row["billing_amount_chf"],
                    result.decision.value,
                    list(result.reason_codes),
                    state.approved_total_chf,
                )
            )
            self.stdout.write(f"      {result.customer_message}")
            for evidence in result.evidence:
                self.stdout.write(f"        - {evidence.field}: {evidence.note}")

        self.stdout.write("-" * 100)
        self.stdout.write(
            f"Final approved total: CHF {state.approved_total_chf:.2f} across "
            f"{len(state.approved_purchases)} approved purchase(s)."
        )

        if exit_code:
            sys.exit(exit_code)
