from datetime import datetime, timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.models import AuthorizationRecord, Decision, Mandate
from api.services import HUMAN_WINDOW_SECONDS


class MandateSerializer(serializers.ModelSerializer):
    """Read-only view of a mandate for the customer's policy-review screen.

    `intent_spec` is deliberately excluded: it is an internal field the engine
    uses to interpret the policy and is never customer-facing.
    """

    class Meta:
        model = Mandate
        fields = [
            "id",
            "instruction",
            "hard_rules",
            "uncertainty_policy",
            "guidance",
            "open_questions",
            "status",
            "draft_id",
            "mandate_id",
            "confirmed_by",
            "confirmed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


# uncertainty_policy may only move towards this value, never away from it, and
# never directly between "approve" and "ask" in either direction (mirrors the
# external challenge API's PATCH rule: approve|ask -> decline only).
_STRICTEST_UNCERTAINTY_POLICY = Mandate.UncertaintyPolicy.DECLINE


class MandateTightenSerializer(serializers.Serializer):
    """Validates a `tighten` request: hard rules may only be added to (existing
    ones must reappear unchanged), and `uncertainty_policy` may only strengthen.
    """

    hard_rules = serializers.JSONField(required=False)
    uncertainty_policy = serializers.ChoiceField(
        choices=Mandate.UncertaintyPolicy.choices, required=False
    )
    guidance = serializers.JSONField(required=False)
    open_questions = serializers.JSONField(required=False)

    def validate_hard_rules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("hard_rules must be a list of rule objects.")
        mandate: Mandate = self.context["mandate"]
        for existing_rule in mandate.hard_rules:
            if existing_rule not in value:
                raise serializers.ValidationError(
                    "Existing hard rules cannot be removed or altered, only added to: "
                    f"missing or changed rule {existing_rule!r}."
                )
        return value

    def validate_uncertainty_policy(self, value):
        mandate: Mandate = self.context["mandate"]
        current = mandate.uncertainty_policy
        if value == current:
            return value
        if value != _STRICTEST_UNCERTAINTY_POLICY:
            raise serializers.ValidationError(
                f"uncertainty_policy can only be tightened to "
                f"{_STRICTEST_UNCERTAINTY_POLICY!r}, not changed from {current!r} to {value!r}."
            )
        return value

    def validate(self, attrs):
        mandate: Mandate = self.context["mandate"]
        if mandate.status != Mandate.Status.ACTIVE:
            raise serializers.ValidationError(
                f"Only an active mandate can be tightened (status is {mandate.status!r})."
            )
        return attrs

    def save(self, **kwargs) -> Mandate:
        # Imported locally to avoid a module-level import cycle (api.services
        # does not import api.serializers, but keeping this local documents
        # the dependency direction explicitly).
        from api import services

        mandate: Mandate = self.context["mandate"]
        return services.tighten_mandate(
            mandate,
            hard_rules=self.validated_data.get("hard_rules"),
            uncertainty_policy=self.validated_data.get("uncertainty_policy"),
            guidance=self.validated_data.get("guidance"),
            open_questions=self.validated_data.get("open_questions"),
        )


class _EvidenceSerializer(serializers.Serializer):
    """One piece of evidence behind a decision, as the engine recorded it."""

    field = serializers.CharField()
    value = serializers.JSONField(allow_null=True)
    note = serializers.CharField()


class _MerchantSummarySerializer(serializers.Serializer):
    """Shape of `raw_event.authorization.merchant`, for schema purposes only."""

    merchant_id = serializers.CharField()
    merchant_name = serializers.CharField()
    merchant_category = serializers.CharField()


class _ItemSummarySerializer(serializers.Serializer):
    """Shape of one `raw_event.authorization.items[]` entry, for schema purposes only."""

    item_name = serializers.CharField()
    quantity = serializers.IntegerField()
    unit_price = serializers.FloatField()
    item_details = serializers.CharField(allow_null=True)


class StepUpSerializer(serializers.ModelSerializer):
    """One pending step-up: everything the customer needs to judge it."""

    merchant_name = serializers.SerializerMethodField()
    purchase_description = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    reason_codes = serializers.SerializerMethodField()
    customer_message = serializers.SerializerMethodField()
    evidence = serializers.SerializerMethodField()
    respond_by = serializers.SerializerMethodField()
    seconds_remaining = serializers.SerializerMethodField()
    scenario_id = serializers.CharField(source="run.scenario_id", read_only=True)

    class Meta:
        model = AuthorizationRecord
        fields = [
            "id",
            "authorization_id",
            "scenario_id",
            "merchant_name",
            "purchase_description",
            "items",
            "billing_amount_chf",
            "reason_codes",
            "customer_message",
            "evidence",
            "deadline_at",
            "respond_by",
            "seconds_remaining",
        ]

    def _authorization_payload(self, obj: AuthorizationRecord) -> dict:
        return obj.raw_event.get("authorization", {}) or obj.raw_event.get("data", {}).get(
            "authorization", {}
        )

    def get_merchant_name(self, obj: AuthorizationRecord) -> str | None:
        return self._authorization_payload(obj).get("merchant", {}).get("merchant_name")

    def get_purchase_description(self, obj: AuthorizationRecord) -> str | None:
        return self._authorization_payload(obj).get("purchase_description")

    def get_items(self, obj: AuthorizationRecord) -> list:
        return self._authorization_payload(obj).get("items", [])

    def _latest_engine_step_up(self, obj: AuthorizationRecord) -> Decision | None:
        return (
            obj.decisions.filter(source=Decision.Source.ENGINE, decision=Decision.Value.STEP_UP)
            .order_by("-created_at")
            .first()
        )

    def get_reason_codes(self, obj: AuthorizationRecord) -> list:
        decision = self._latest_engine_step_up(obj)
        return decision.reason_codes if decision else []

    def get_customer_message(self, obj: AuthorizationRecord) -> str:
        decision = self._latest_engine_step_up(obj)
        return decision.customer_message if decision else ""

    @extend_schema_field(_EvidenceSerializer(many=True))
    def get_evidence(self, obj: AuthorizationRecord) -> list:
        decision = self._latest_engine_step_up(obj)
        return decision.evidence if decision else []

    def get_respond_by(self, obj: AuthorizationRecord) -> datetime | None:
        """When the customer's window closes: the step-up plus the human window."""
        decision = self._latest_engine_step_up(obj)
        if decision is None:
            return None
        return decision.created_at + timedelta(seconds=HUMAN_WINDOW_SECONDS)

    def get_seconds_remaining(self, obj: AuthorizationRecord) -> float:
        """Seconds left for the customer to answer -- not the automated deadline."""
        respond_by = self.get_respond_by(obj)
        if respond_by is None:
            return 0.0
        return max(0.0, (respond_by - timezone.now()).total_seconds())


class StepUpResolveSerializer(serializers.Serializer):
    """The customer's answer to a pending step-up."""

    decision = serializers.ChoiceField(choices=[Decision.Value.APPROVE, Decision.Value.DECLINE])
    message = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        authorization: AuthorizationRecord = self.context["authorization"]
        already_resolved = authorization.decisions.filter(source=Decision.Source.CUSTOMER).exists()
        if already_resolved:
            raise serializers.ValidationError("This step-up has already been resolved.")
        return attrs
