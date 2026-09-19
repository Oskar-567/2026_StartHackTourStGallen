"""Long-polls the challenge API and answers each proposed purchase within its
real-clock deadline.

Outline (mirrors `technical_details.md` step 6, "Prepare your worker, then
start a run"):

    while the run has work remaining:
        poll GET /v1/decision-requests/next?wait=25
        204 -> check run progress, keep polling
        error -> handled before reading any purchase data
        validate the envelope's `data` against the event schema
        already-handled authorization_id -> reconcile the saved result
        otherwise -> build state, decide, submit before deadline_at
        record what the API accepted
        step_up does not block: the loop keeps polling immediately

    separately: forward any customer resolutions that have not reached the
    API yet (`Decision.source=customer`, `forwarded_at IS NULL`)

Non-negotiable watchdog: if there is not enough real-clock margin left
before `deadline_at` to safely run the full engine, submit the best decision
available from the deterministic tier alone (no semantic/LLM tier) rather
than risk missing the deadline.

Fact extraction (`FACTS_BACKEND`) runs before `decide()` only when the margin
covers its whole timeout plus the watchdog margin; otherwise the engine decides
without facts, which makes the semantic checks ask rather than guess. The model
is warmed at startup so the first purchase does not pay the model load.
"""

from __future__ import annotations

import logging
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api import services
from api.models import AuthorizationRecord, Decision, Mandate, Run
from engine.aggregate import combine
from engine.checks import DETERMINISTIC_CHECKS
from engine.decide import ENGINE_VERSION, decide
from engine.parsing import EventParsingError, parse_event
from engine.types import AuthorizationEvent, EngineState, ExtractedFacts
from engine.types import Decision as EngineDecision
from facts import FactExtractor, build_extractor, extract_for_event
from viseca.client import VisecaAPIError, VisecaConnectionError

logger = logging.getLogger("viseca.worker")

POLL_WAIT_SECONDS = 25
#: Minimum real-clock seconds before `deadline_at` required to run the full
#: (deterministic + semantic) engine. Below this, the watchdog submits the
#: deterministic tier's own verdict instead of risking the 8s deadline.
WATCHDOG_MARGIN_SECONDS = 2.0
#: When a poll or a network call fails outright, back off briefly before
#: retrying rather than spinning a hot loop against a down API.
ERROR_BACKOFF_SECONDS = 1.0


def _configure_logging() -> None:
    root = logging.getLogger("viseca")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _deterministic_only_decision(event: AuthorizationEvent, state: EngineState) -> EngineDecision:
    """The watchdog's fallback: the deterministic tier's own verdict, with no
    semantic/LLM-backed checks run at all."""
    results = [check(event, state, None) for check in DETERMINISTIC_CHECKS]
    return combine(results, event.mandate.uncertainty_policy, ENGINE_VERSION)


def _fallback_step_up(event: AuthorizationEvent) -> EngineDecision:
    """Last-resort answer if the engine itself raises: never leave a purchase
    unanswered because of an internal error -- ask the customer instead."""
    from engine.types import DecisionType

    return EngineDecision(
        decision=DecisionType.STEP_UP,
        reason_codes=("engine_error",),
        customer_message="This purchase needs your review; our automated check could not complete.",
        evidence=(),
        engine_version=ENGINE_VERSION,
    )


class Command(BaseCommand):
    help = "Long-polls the challenge API and decides each proposed purchase within its deadline."

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Tracks the Run this process is driving so repeated envelopes for the
        # same run_id don't need a DB lookup every time. None until `handle()`
        # starts a run, or a test calls `_handle_envelope`/`_reconcile` directly.
        self._run: Run | None = None
        # Built on first use so tests that drive `_handle_envelope` directly get
        # the configured backend too; `handle()` builds and warms it up front.
        self._extractor: FactExtractor | None = None

    def _get_extractor(self) -> FactExtractor:
        if self._extractor is None:
            self._extractor = build_extractor()
        return self._extractor

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--scenario", dest="scenario_id", default=None, help="Scenario to start a new run for."
        )
        parser.add_argument(
            "--mandate-id",
            dest="mandate_pk",
            default=None,
            help="Local Mandate primary key (must be active) to bind a new --scenario run to.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process a single poll cycle then exit (useful for scripts/tests).",
        )

    def handle(self, *args, **options) -> None:
        _configure_logging()
        client = services.get_client()

        scenario_id = options.get("scenario_id")
        mandate_pk = options.get("mandate_pk")
        once = options.get("once", False)

        if scenario_id:
            if not mandate_pk:
                raise CommandError("--scenario requires --mandate-id.")
            mandate = Mandate.objects.get(pk=mandate_pk)
            if mandate.status != Mandate.Status.ACTIVE:
                raise CommandError(
                    f"Mandate {mandate_pk} is not active (status={mandate.status!r})."
                )
            self._run = self._start_run(client, scenario_id, mandate)

        extractor = self._get_extractor()
        warm_up = getattr(extractor, "warm_up", None)
        warmed = warm_up() if callable(warm_up) else None
        logger.info("facts_backend=%s warm_up=%s", extractor.name, warmed)

        logger.info("worker_starting run_id=%s", self._run.run_id if self._run else "<resuming>")

        while True:
            self._forward_pending_resolutions(client)
            envelope = self._poll(client)
            if envelope is None:
                if self._run is not None and self._run_finished(client, self._run):
                    logger.info("run_complete run_id=%s", self._run.run_id)
                    break
                if once:
                    break
                continue

            self._handle_envelope(client, envelope)
            if once:
                break

    # -- run lifecycle --------------------------------------------------

    def _start_run(self, client, scenario_id: str, mandate: Mandate) -> Run:
        response = client.create_scenario_run(scenario_id, mandate.mandate_id) or {}
        return Run.objects.create(
            run_id=response.get("run_id", ""),
            scenario_id=scenario_id,
            mandate=mandate,
            status=Run.Status.RUNNING,
            started_at=timezone.now(),
            event_counters=response.get("event_counters", {}) or {},
        )

    def _run_finished(self, client, run: Run) -> bool:
        try:
            data = client.get_scenario_run(run.run_id) or {}
        except (VisecaAPIError, VisecaConnectionError) as exc:
            logger.warning("run_progress_check_failed run_id=%s error=%s", run.run_id, exc)
            return False
        counters = data.get("event_counters", data) or {}
        run.event_counters = counters
        run.save(update_fields=["event_counters"])
        total = counters.get("events_total")
        processed = counters.get("events_processed")
        finished = total is not None and processed is not None and processed >= total
        if finished and run.status == Run.Status.RUNNING:
            run.status = Run.Status.COMPLETED
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at"])
        return finished

    def _resolve_run(self, run_id: str) -> Run | None:
        if self._run is not None and self._run.run_id == run_id:
            return self._run
        run = Run.objects.filter(run_id=run_id).first()
        if run is not None:
            self._run = run
        return run

    # -- polling ---------------------------------------------------------

    def _poll(self, client) -> dict | None:
        try:
            return client.decision_requests_next(wait=POLL_WAIT_SECONDS)
        except VisecaConnectionError as exc:
            logger.warning("poll_failed error=%s", exc)
            time.sleep(ERROR_BACKOFF_SECONDS)
            return None
        except VisecaAPIError as exc:
            logger.error("poll_api_error status=%s body=%s", exc.status_code, exc.body)
            time.sleep(ERROR_BACKOFF_SECONDS)
            return None

    # -- one envelope -----------------------------------------------------

    def _handle_envelope(self, client, envelope: dict) -> None:
        run_id = envelope.get("run_id", "")
        event_dict = envelope.get("data")
        if not isinstance(event_dict, dict):
            logger.error("envelope_missing_data run_id=%s", run_id)
            return

        run = self._resolve_run(run_id)
        if run is None:
            logger.error(
                "unknown_run run_id=%s authorization_id=%s",
                run_id,
                envelope.get("authorization_id"),
            )
            return

        try:
            parsed = parse_event(services.with_intent_spec(event_dict, run))
        except EventParsingError as exc:
            logger.error("event_parse_failed run_id=%s error=%s", run_id, exc)
            return

        existing = AuthorizationRecord.objects.filter(
            run=run, authorization_id=parsed.authorization_id
        ).first()
        if existing is not None:
            self._reconcile(client, existing)
            return

        authorization = AuthorizationRecord.objects.create(
            run=run,
            authorization_id=parsed.authorization_id,
            source_authorization_id=parsed.source_authorization_id,
            raw_event=envelope,
            simulated_purchased_at=parsed.timestamp,
            deadline_at=parsed.deadline_at,
            received_at=timezone.now(),
            billing_amount_chf=parsed.billing_amount_chf,
        )
        self._decide_and_submit(client, authorization, parsed)

    def _reconcile(self, client, authorization: AuthorizationRecord) -> None:
        """A repeated delivery of an already-recorded authorization_id: never
        run the engine a second time. Recover an interrupted decision if one
        is missing, otherwise re-affirm the decision already on file so a
        retried delivery cannot produce two different automated answers.
        """
        decision = (
            authorization.decisions.filter(source=Decision.Source.ENGINE)
            .order_by("-created_at")
            .first()
        )
        if decision is None:
            logger.info(
                "reconcile_recovering_incomplete_decision authorization_id=%s",
                authorization.authorization_id,
            )
            try:
                parsed = parse_event(
                    services.with_intent_spec(
                        services.event_payload(authorization.raw_event), authorization.run
                    )
                )
            except EventParsingError as exc:
                logger.error(
                    "reconcile_reparse_failed authorization_id=%s error=%s",
                    authorization.authorization_id,
                    exc,
                )
                return
            self._decide_and_submit(client, authorization, parsed)
            return

        logger.info(
            "reconcile_repeated_delivery authorization_id=%s decision=%s",
            authorization.authorization_id,
            decision.decision,
        )
        try:
            client.submit_decision(
                authorization.authorization_id,
                {
                    "decision": decision.decision,
                    "reason_codes": decision.reason_codes,
                    "customer_message": decision.customer_message,
                    "evidence": decision.evidence,
                    "engine_version": decision.engine_version,
                },
            )
        except (VisecaAPIError, VisecaConnectionError) as exc:
            logger.warning(
                "reconcile_resubmit_failed authorization_id=%s error=%s",
                authorization.authorization_id,
                exc,
            )

    def _decide_and_submit(
        self, client, authorization: AuthorizationRecord, event: AuthorizationEvent
    ) -> None:
        state = services.build_engine_state(authorization.run, authorization)

        margin = (authorization.deadline_at - timezone.now()).total_seconds()
        try:
            if margin <= WATCHDOG_MARGIN_SECONDS:
                logger.warning(
                    "watchdog_deterministic_only authorization_id=%s margin=%.2fs",
                    authorization.authorization_id,
                    margin,
                )
                engine_decision = _deterministic_only_decision(event, state)
            else:
                facts = self._extract_within_deadline(authorization, margin)
                engine_decision = decide(event, state, facts)
        except Exception:  # noqa: BLE001 - the engine must never leave a purchase unanswered
            logger.exception("engine_raised authorization_id=%s", authorization.authorization_id)
            engine_decision = _fallback_step_up(event)

        try:
            services.record_decision(authorization, engine_decision, client=client)
        except (VisecaAPIError, VisecaConnectionError) as exc:
            logger.error(
                "submit_failed authorization_id=%s error=%s", authorization.authorization_id, exc
            )
            return

        logger.info(
            "decision authorization_id=%s decision=%s reason_codes=%s",
            authorization.authorization_id,
            engine_decision.decision.value,
            list(engine_decision.reason_codes),
        )

    def _extract_within_deadline(
        self, authorization: AuthorizationRecord, margin: float
    ) -> ExtractedFacts | None:
        """Facts for this purchase, or None when there is no time or it failed.

        Runs only if the extractor's full timeout still leaves the watchdog
        margin -- a slow model must never be the reason a deadline is missed.
        None is safe: the semantic checks then return UNCERTAIN.
        """
        budget = margin - WATCHDOG_MARGIN_SECONDS
        if budget < settings.FACTS_TIMEOUT_SECONDS:
            logger.warning(
                "facts_skipped authorization_id=%s margin=%.2fs",
                authorization.authorization_id,
                margin,
            )
            return None
        extractor = self._get_extractor()
        started = time.monotonic()
        try:
            facts = extract_for_event(extractor, services.event_payload(authorization.raw_event))
        except Exception:  # noqa: BLE001 - extraction must never block a decision
            logger.exception("facts_failed authorization_id=%s", authorization.authorization_id)
            return None
        logger.info(
            "facts authorization_id=%s source=%s lines_read=%d/%d elapsed=%.2fs",
            authorization.authorization_id,
            facts.source,
            sum(1 for item in facts.items if item.category or item.attributes),
            len(services.event_payload(authorization.raw_event)["authorization"]["items"]),
            time.monotonic() - started,
        )
        return facts

    # -- customer resolutions --------------------------------------------

    def _forward_pending_resolutions(self, client) -> None:
        pending = Decision.objects.filter(
            source=Decision.Source.CUSTOMER, forwarded_at__isnull=True
        )
        for decision in pending:
            try:
                services.forward_customer_resolution(decision, client=client)
            except (VisecaAPIError, VisecaConnectionError) as exc:
                logger.warning(
                    "forward_resolution_failed decision_id=%s error=%s", decision.pk, exc
                )
