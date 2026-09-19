"""Persistence for the wallet control layer.

Two clocks matter and must never be conflated:

- **Simulated purchase time** (`AuthorizationRecord.simulated_purchased_at`,
  `ApprovedSpend.simulated_purchased_at`) is the timestamp on the purchase event
  itself, as delivered by the challenge API. Rolling spending-window limits are
  computed against this clock.
- **Real clock** (`AuthorizationRecord.deadline_at`, `AuthorizationRecord.received_at`,
  `Decision.created_at`, `ApprovedSpend.recorded_at`, ...) is wall-clock time on this
  server. It drives automated-decision and human step-up deadlines.

`server/engine/` (owned by another agent) is Django-free and never imports this
module; it is handed plain data extracted from these rows.
"""

from django.db import models
from django.db.models import OuterRef, Subquery


class Mandate(models.Model):
    """The customer's wallet policy: original instruction plus the structured
    permissions derived from it. Mirrors the external challenge API's mandate
    (draft -> confirm -> active -> tighten/revoke), plus an `intent_spec` field
    that only the engine reads and the external API never stores.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    class UncertaintyPolicy(models.TextChoices):
        ASK = "ask", "Ask the customer"
        DECLINE = "decline", "Decline"
        APPROVE = "approve", "Approve"

    # Customer's original wording, kept verbatim (never edited, only interpreted).
    instruction = models.TextField()

    # Structured checks in the challenge API's rule format (see technical_details.md
    # "Rule format"): list of {field, operator, value, currency?, scope?, period_days?}.
    hard_rules = models.JSONField(default=list, blank=True)
    uncertainty_policy = models.CharField(
        max_length=16, choices=UncertaintyPolicy.choices, default=UncertaintyPolicy.ASK
    )
    # Explanatory text and open questions shown to the customer before they confirm.
    guidance = models.JSONField(default=list, blank=True)
    open_questions = models.JSONField(default=list, blank=True)

    # Semantic permissions the engine uses to interpret hard_rules/instruction
    # (e.g. resolved merchant categories, familiar-shop heuristics). Internal only:
    # never sent to or stored by the external challenge API.
    intent_spec = models.JSONField(default=dict, blank=True)

    # External challenge API identifiers.
    draft_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    mandate_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    # Who confirmed the draft into an active mandate, and when (real clock).
    confirmed_by = models.CharField(max_length=255, blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Mandate({self.pk}, {self.status})"


class Run(models.Model):
    """One execution of a scenario against a confirmed mandate snapshot."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    run_id = models.CharField(max_length=64, db_index=True)
    scenario_id = models.CharField(max_length=64)
    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Event counters as reported by the external API's run object (e.g.
    # {"total_events": n, "remaining": n, "awaiting_customer": n, ...}); shape is
    # whatever the API returns.
    event_counters = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Run({self.run_id or self.pk}, {self.scenario_id})"


class AuthorizationRecord(models.Model):
    """One proposed purchase as delivered by the challenge API."""

    class Manager(models.Manager):
        def pending_step_ups(self) -> models.QuerySet["AuthorizationRecord"]:
            """Authorizations whose latest decision is an engine `step_up` with no
            customer resolution yet -- the step-up approval queue for the app.
            """
            latest = Decision.objects.filter(authorization=OuterRef("pk")).order_by("-created_at")
            return self.annotate(
                latest_decision_value=Subquery(latest.values("decision")[:1]),
                latest_decision_source=Subquery(latest.values("source")[:1]),
            ).filter(
                latest_decision_value=Decision.Value.STEP_UP,
                latest_decision_source=Decision.Source.ENGINE,
            )

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="authorizations")

    # Live purchase ID for this run; the worker uses it to recognise repeated
    # delivery. Unique together with the run so a retry cannot create a duplicate row.
    authorization_id = models.CharField(max_length=64)
    # Stable ID of the underlying CSV fixture row (unrelated to the live ID above).
    source_authorization_id = models.CharField(max_length=64, blank=True, default="")

    # The full authorization.request event exactly as received (envelope + data),
    # kept verbatim as the audit record and as the source for fields the API adds
    # later (merchant, items, mandate snapshot, context, runtime).
    raw_event = models.JSONField()

    # Simulated clock: when the purchase itself happened, per the event payload.
    # Used for rolling spend-window limits. Real clock: when this server received
    # the event, and the real-clock deadline by which an automated decision is due.
    simulated_purchased_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    received_at = models.DateTimeField()

    billing_amount_chf = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = Manager()

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "authorization_id"], name="unique_authorization_per_run"
            )
        ]

    def __str__(self) -> str:
        return f"AuthorizationRecord({self.authorization_id})"


class Decision(models.Model):
    """What the system (or the customer, resolving a step-up) answered for one
    authorization. An automated `step_up` and the customer's later resolution are
    two separate rows, never an overwrite, so the audit trail survives.
    """

    class Value(models.TextChoices):
        APPROVE = "approve", "Approve"
        DECLINE = "decline", "Decline"
        STEP_UP = "step_up", "Step up"

    class Source(models.TextChoices):
        ENGINE = "engine", "Automated engine decision"
        CUSTOMER = "customer", "Customer step-up resolution"

    authorization = models.ForeignKey(
        AuthorizationRecord, on_delete=models.CASCADE, related_name="decisions"
    )
    decision = models.CharField(max_length=16, choices=Value.choices)
    reason_codes = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    customer_message = models.TextField(blank=True, default="")
    engine_version = models.CharField(max_length=64, blank=True, default="")

    # False only for an engine `step_up`: it pauses the purchase rather than
    # settling it. Every customer resolution is final.
    is_final = models.BooleanField(default=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.ENGINE)

    # Set once a separate worker has forwarded a customer resolution to the
    # external challenge API's /resolve endpoint. Meaningless for engine decisions
    # (the worker sends those itself before writing the row).
    forwarded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Decision({self.authorization_id}, {self.decision}, {self.source})"


class ApprovedSpend(models.Model):
    """Ledger row written only when a purchase is finally approved. Rolling-window
    spend limits are summed from this table -- a purchase merely waiting on a
    step_up answer must never appear here.
    """

    authorization = models.OneToOneField(
        AuthorizationRecord, on_delete=models.CASCADE, related_name="approved_spend"
    )
    # Denormalized for cheap rolling-window queries scoped to one mandate.
    mandate = models.ForeignKey(Mandate, on_delete=models.CASCADE, related_name="approved_spends")

    amount_chf = models.DecimalField(max_digits=12, decimal_places=2)
    # Simulated clock: the purchase's own timestamp, not when we wrote this row.
    simulated_purchased_at = models.DateTimeField()

    # Real clock: when the approval was recorded.
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-simulated_purchased_at"]

    def __str__(self) -> str:
        return f"ApprovedSpend({self.authorization_id}, {self.amount_chf} CHF)"
