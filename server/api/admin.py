from django.contrib import admin

from api.models import ApprovedSpend, AuthorizationRecord, Decision, Mandate, Run


@admin.register(Mandate)
class MandateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "uncertainty_policy",
        "mandate_id",
        "confirmed_at",
        "created_at",
    )
    list_filter = ("status", "uncertainty_policy")
    search_fields = ("instruction", "draft_id", "mandate_id", "confirmed_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("id", "run_id", "scenario_id", "mandate", "status", "started_at", "finished_at")
    list_filter = ("status", "scenario_id")
    search_fields = ("run_id", "scenario_id")
    autocomplete_fields = ("mandate",)


@admin.register(AuthorizationRecord)
class AuthorizationRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "authorization_id",
        "run",
        "billing_amount_chf",
        "simulated_purchased_at",
        "deadline_at",
        "received_at",
    )
    list_filter = ("run__scenario_id",)
    search_fields = ("authorization_id", "source_authorization_id")
    autocomplete_fields = ("run",)


@admin.register(Decision)
class DecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "authorization",
        "decision",
        "source",
        "is_final",
        "forwarded_at",
        "created_at",
    )
    list_filter = ("decision", "source", "is_final")
    search_fields = ("authorization__authorization_id", "customer_message")
    autocomplete_fields = ("authorization",)


@admin.register(ApprovedSpend)
class ApprovedSpendAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "authorization",
        "mandate",
        "amount_chf",
        "simulated_purchased_at",
        "recorded_at",
    )
    list_filter = ("mandate",)
    search_fields = ("authorization__authorization_id",)
    autocomplete_fields = ("authorization", "mandate")
