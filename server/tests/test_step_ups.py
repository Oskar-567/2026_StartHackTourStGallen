import pytest
from django.urls import reverse

from api.models import ApprovedSpend, Decision
from tests.factories import make_authorization, make_step_up_decision


@pytest.mark.django_db
def test_step_up_queue_includes_pending_step_up_with_customer_facing_details(api_client):
    authorization = make_authorization()
    make_step_up_decision(authorization)

    response = api_client.get(reverse("step-up-list"))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["authorization_id"] == "AU_LIVE_0001"
    assert item["merchant_name"] == "Example Market"
    assert item["billing_amount_chf"] == "18.00"
    assert item["items"] == [{"item_name": "Bread", "quantity": 1, "unit_price": 4.5}]
    assert item["reason_codes"] == ["customer_confirmation"]
    assert item["customer_message"] == "Please review this purchase."
    # The customer's 120s window, not the ~8s automated deadline.
    assert 100 < item["seconds_remaining"] <= 120
    assert item["respond_by"]
    assert item["evidence"] == []


@pytest.mark.django_db
def test_step_up_queue_excludes_authorization_with_no_decision(api_client):
    make_authorization()

    response = api_client.get(reverse("step-up-list"))

    assert response.json() == []


@pytest.mark.django_db
def test_step_up_queue_excludes_authorization_already_resolved_by_customer(api_client):
    authorization = make_authorization()
    make_step_up_decision(authorization)
    Decision.objects.create(
        authorization=authorization,
        decision=Decision.Value.APPROVE,
        source=Decision.Source.CUSTOMER,
        is_final=True,
    )

    response = api_client.get(reverse("step-up-list"))

    assert response.json() == []


@pytest.mark.django_db
def test_step_up_queue_excludes_authorization_engine_approved_directly(api_client):
    authorization = make_authorization()
    Decision.objects.create(
        authorization=authorization,
        decision=Decision.Value.APPROVE,
        source=Decision.Source.ENGINE,
        is_final=True,
    )

    response = api_client.get(reverse("step-up-list"))

    assert response.json() == []


@pytest.mark.django_db
def test_resolve_approve_records_customer_decision_and_writes_approved_spend(api_client):
    authorization = make_authorization(billing_amount_chf="18.00")
    make_step_up_decision(authorization)

    response = api_client.post(
        reverse("step-up-resolve", args=[authorization.pk]),
        {"decision": "approve", "message": "Looks fine."},
        format="json",
    )

    assert response.status_code == 200, response.json()
    resolution = authorization.decisions.get(source=Decision.Source.CUSTOMER)
    assert resolution.decision == Decision.Value.APPROVE
    assert resolution.customer_message == "Looks fine."
    assert resolution.is_final is True
    assert resolution.forwarded_at is None

    spend = ApprovedSpend.objects.get(authorization=authorization)
    assert str(spend.amount_chf) == "18.00"
    assert spend.simulated_purchased_at == authorization.simulated_purchased_at


@pytest.mark.django_db
def test_resolve_decline_records_customer_decision_without_approved_spend(api_client):
    authorization = make_authorization()
    make_step_up_decision(authorization)

    response = api_client.post(
        reverse("step-up-resolve", args=[authorization.pk]),
        {"decision": "decline"},
        format="json",
    )

    assert response.status_code == 200
    resolution = authorization.decisions.get(source=Decision.Source.CUSTOMER)
    assert resolution.decision == Decision.Value.DECLINE
    assert not ApprovedSpend.objects.filter(authorization=authorization).exists()


@pytest.mark.django_db
def test_double_resolve_is_a_clean_400(api_client):
    authorization = make_authorization()
    make_step_up_decision(authorization)

    first = api_client.post(
        reverse("step-up-resolve", args=[authorization.pk]),
        {"decision": "approve"},
        format="json",
    )
    second = api_client.post(
        reverse("step-up-resolve", args=[authorization.pk]),
        {"decision": "decline"},
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert authorization.decisions.filter(source=Decision.Source.CUSTOMER).count() == 1
    assert ApprovedSpend.objects.filter(authorization=authorization).count() == 1


@pytest.mark.django_db
def test_step_up_queue_leaves_out_step_ups_whose_answer_window_closed(api_client):
    from datetime import timedelta

    from django.utils import timezone

    from api import services

    open_one = make_authorization(authorization_id="AU_OPEN")
    make_step_up_decision(open_one)
    closed_one = make_authorization(authorization_id="AU_CLOSED")
    old = make_step_up_decision(closed_one)
    Decision.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(seconds=services.HUMAN_WINDOW_SECONDS + 5)
    )

    body = api_client.get(reverse("step-up-list")).json()

    assert [item["authorization_id"] for item in body] == ["AU_OPEN"]
