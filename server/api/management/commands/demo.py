"""One command for the live demo: the right mandate, a new run, readable output.

    uv run python manage.py demo SCEN0004

Reuses the newest active mandate that still matches the scenario's reference
policy exactly (a mandate tightened in the app does not count), or creates and
confirms one at the challenge API. Then starts the worker with
`--pretty`, so the terminal tells the story while the phone shows the questions.
Picking the mandate here removes the one mistake that is easy to make under
pressure: running a scenario against another scenario's policy.
"""

from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from api import services
from api.models import Mandate
from api.reference_policies import REFERENCE_POLICIES
from viseca.client import VisecaAPIError, VisecaConnectionError


class Command(BaseCommand):
    help = "Live demo: find or create the scenario's mandate, then run it with readable output."

    def add_arguments(self, parser) -> None:
        parser.add_argument("scenario_id", help="e.g. SCEN0002 or SCEN0004")
        parser.add_argument(
            "--new-mandate",
            action="store_true",
            help="Create a fresh mandate even if a matching active one exists.",
        )

    def handle(self, *args, **options) -> None:
        scenario_id = options["scenario_id"].upper()
        policy = REFERENCE_POLICIES.get(scenario_id)
        if policy is None:
            raise CommandError(
                f"No reference policy for {scenario_id!r}; known: {sorted(REFERENCE_POLICIES)}"
            )

        mandate = None
        if not options["new_mandate"]:
            # Only a mandate that still IS the reference policy: one tightened in
            # the app (say, "decline when unsure") would quietly change the demo.
            candidates = Mandate.objects.filter(
                status=Mandate.Status.ACTIVE, instruction=policy["instruction"]
            ).order_by("-created_at")
            mandate = next(
                (
                    m
                    for m in candidates
                    if m.hard_rules == policy["hard_rules"]
                    and m.uncertainty_policy == policy["uncertainty_policy"]
                ),
                None,
            )
        if mandate is None:
            self.stdout.write(f"Creating a fresh mandate for {scenario_id} at the challenge API...")
            try:
                mandate = services.create_mandate_draft(
                    instruction=policy["instruction"],
                    hard_rules=policy["hard_rules"],
                    uncertainty_policy=policy["uncertainty_policy"],
                    guidance=policy.get("guidance"),
                    open_questions=policy.get("open_questions"),
                    intent_spec=policy.get("intent_spec"),
                )
                services.confirm_mandate(mandate, confirmed_by="demo")
            except VisecaAPIError as exc:
                raise CommandError(
                    f"The challenge API rejected the mandate ({exc.status_code}): {exc.body}"
                ) from exc
            except VisecaConnectionError as exc:
                raise CommandError(f"Could not reach the challenge API: {exc}") from exc

        call_command(
            "run_worker", "--scenario", scenario_id, "--mandate-id", str(mandate.pk), "--pretty"
        )
