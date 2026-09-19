"""Creates a scenario's reference policy as a mandate at the challenge API.

The missing step between "we have a policy" and "the worker can run": posts the
policy from `api.reference_policies` as a draft, confirms it (unless
`--draft-only`), and stores it locally together with its `intent_spec` -- the
half the challenge API does not keep, and which the worker attaches to every
live event of runs bound to this mandate.

    uv run python manage.py create_mandate --scenario SCEN0002
    uv run python manage.py run_worker --scenario SCEN0002 --mandate-id <printed id>

`--draft-only` leaves the confirmation to the customer, e.g. in the app.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from api import services
from api.reference_policies import REFERENCE_POLICIES
from viseca.client import VisecaAPIError, VisecaConnectionError


class Command(BaseCommand):
    help = "Creates (and by default confirms) a scenario's reference policy as a mandate."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--scenario", dest="scenario_id", required=True)
        parser.add_argument(
            "--draft-only",
            action="store_true",
            help="Create the draft but leave the confirmation to the customer.",
        )
        parser.add_argument(
            "--confirmed-by",
            default="create_mandate command",
            help="Recorded as who agreed to the mandate.",
        )

    def handle(self, *args, **options) -> None:
        scenario_id = options["scenario_id"]
        policy = REFERENCE_POLICIES.get(scenario_id)
        if policy is None:
            raise CommandError(
                f"No reference policy for {scenario_id!r}; known: {sorted(REFERENCE_POLICIES)}"
            )

        try:
            mandate = services.create_mandate_draft(
                instruction=policy["instruction"],
                hard_rules=policy["hard_rules"],
                uncertainty_policy=policy["uncertainty_policy"],
                guidance=policy.get("guidance"),
                open_questions=policy.get("open_questions"),
                intent_spec=policy.get("intent_spec"),
            )
            self.stdout.write(f"Draft created: local id {mandate.pk}, draft_id {mandate.draft_id}")
            if options["draft_only"]:
                self.stdout.write(
                    f"Left as a draft. Confirm it with POST /api/mandates/{mandate.pk}/confirm/."
                )
                return
            services.confirm_mandate(mandate, confirmed_by=options["confirmed_by"])
        except VisecaAPIError as exc:
            raise CommandError(
                f"The challenge API rejected the mandate ({exc.status_code}): {exc.body}"
            ) from exc
        except VisecaConnectionError as exc:
            raise CommandError(f"Could not reach the challenge API: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Mandate active: local id {mandate.pk}, mandate_id {mandate.mandate_id}"
            )
        )
        self.stdout.write("Start the run with:")
        self.stdout.write(
            f"  uv run python manage.py run_worker --scenario {scenario_id} "
            f"--mandate-id {mandate.pk}"
        )
