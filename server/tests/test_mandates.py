from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from api import services
from api.models import Mandate
from tests.factories import PRICE_RULE, make_mandate


@pytest.fixture
def mock_client(monkeypatch) -> MagicMock:
    """No network: every mandate-lifecycle test that reaches the external
    challenge API gets a `MagicMock` instead of a real `VisecaClient`."""
    client = MagicMock()
    monkeypatch.setattr(services, "get_client", lambda: client)
    return client


@pytest.mark.django_db
def test_mandate_list_returns_guidance_and_open_questions(api_client):
    make_mandate(guidance=["Familiar shop = used before."], open_questions=["Which card?"])

    response = api_client.get(reverse("mandate-list"))

    assert response.status_code == 200
    body = response.json()[0]
    assert body["guidance"] == ["Familiar shop = used before."]
    assert body["open_questions"] == ["Which card?"]
    assert "intent_spec" not in body


@pytest.mark.django_db
def test_mandate_detail_returns_current_permissions(api_client):
    mandate = make_mandate()

    response = api_client.get(reverse("mandate-detail", args=[mandate.pk]))

    assert response.status_code == 200
    assert response.json()["id"] == mandate.pk
    assert response.json()["hard_rules"] == [PRICE_RULE]


@pytest.mark.django_db
def test_tighten_accepts_adding_a_new_rule_and_strengthening_policy(api_client, mock_client):
    mandate = make_mandate(uncertainty_policy=Mandate.UncertaintyPolicy.ASK)
    new_rule = {
        "field": "authorization.merchant.merchant_category",
        "operator": "=",
        "value": "groceries",
    }

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"hard_rules": [PRICE_RULE, new_rule], "uncertainty_policy": "decline"},
        format="json",
    )

    assert response.status_code == 200, response.json()
    mandate.refresh_from_db()
    assert mandate.hard_rules == [PRICE_RULE, new_rule]
    assert mandate.uncertainty_policy == Mandate.UncertaintyPolicy.DECLINE
    # Forwarded to the external API before the local record was updated.
    mock_client.patch_mandate.assert_called_once_with(
        mandate.mandate_id,
        {"hard_rules": [PRICE_RULE, new_rule], "uncertainty_policy": "decline"},
    )


@pytest.mark.django_db
def test_tighten_rejects_removing_an_existing_rule(api_client, mock_client):
    mandate = make_mandate()

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"hard_rules": []},
        format="json",
    )

    assert response.status_code == 400
    mandate.refresh_from_db()
    assert mandate.hard_rules == [PRICE_RULE]


@pytest.mark.django_db
def test_tighten_rejects_altering_an_existing_rule(api_client):
    mandate = make_mandate()
    altered_rule = {**PRICE_RULE, "value": 50}

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"hard_rules": [altered_rule]},
        format="json",
    )

    assert response.status_code == 400
    mandate.refresh_from_db()
    assert mandate.hard_rules == [PRICE_RULE]


@pytest.mark.django_db
def test_tighten_rejects_weakening_uncertainty_policy_from_decline_to_ask(api_client):
    mandate = make_mandate(uncertainty_policy=Mandate.UncertaintyPolicy.DECLINE)

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"uncertainty_policy": "ask"},
        format="json",
    )

    assert response.status_code == 400
    mandate.refresh_from_db()
    assert mandate.uncertainty_policy == Mandate.UncertaintyPolicy.DECLINE


@pytest.mark.django_db
def test_tighten_rejects_changing_approve_directly_to_ask(api_client):
    mandate = make_mandate(uncertainty_policy=Mandate.UncertaintyPolicy.APPROVE)

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"uncertainty_policy": "ask"},
        format="json",
    )

    assert response.status_code == 400
    mandate.refresh_from_db()
    assert mandate.uncertainty_policy == Mandate.UncertaintyPolicy.APPROVE


@pytest.mark.django_db
def test_tighten_rejects_non_active_mandate(api_client):
    mandate = make_mandate(status=Mandate.Status.DRAFT)

    response = api_client.post(
        reverse("mandate-tighten", args=[mandate.pk]),
        {"uncertainty_policy": "decline"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_revoke_marks_an_active_mandate_revoked(api_client, mock_client):
    mandate = make_mandate(status=Mandate.Status.ACTIVE)

    response = api_client.post(reverse("mandate-revoke", args=[mandate.pk]))

    assert response.status_code == 200
    mandate.refresh_from_db()
    assert mandate.status == Mandate.Status.REVOKED
    mock_client.delete_mandate.assert_called_once_with(mandate.mandate_id)


@pytest.mark.django_db
def test_revoke_an_already_revoked_mandate_is_a_clean_400(api_client):
    mandate = make_mandate(status=Mandate.Status.REVOKED)

    response = api_client.post(reverse("mandate-revoke", args=[mandate.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_confirm_activates_a_draft_mandate_and_stores_the_returned_mandate_id(
    api_client, mock_client
):
    mock_client.confirm_mandate.return_value = {"mandate_id": "TM_NEW_0001"}
    mandate = make_mandate(status=Mandate.Status.DRAFT, draft_id="draft-xyz", mandate_id="")

    response = api_client.post(
        reverse("mandate-confirm", args=[mandate.pk]), {"confirmed_by": "alex"}, format="json"
    )

    assert response.status_code == 200, response.json()
    mandate.refresh_from_db()
    assert mandate.status == Mandate.Status.ACTIVE
    assert mandate.mandate_id == "TM_NEW_0001"
    assert mandate.confirmed_by == "alex"
    assert mandate.confirmed_at is not None
    mock_client.confirm_mandate.assert_called_once_with("draft-xyz")


@pytest.mark.django_db
def test_confirm_rejects_a_mandate_that_is_not_a_draft(api_client, mock_client):
    mandate = make_mandate(status=Mandate.Status.ACTIVE)

    response = api_client.post(reverse("mandate-confirm", args=[mandate.pk]))

    assert response.status_code == 400
    mandate.refresh_from_db()
    assert mandate.status == Mandate.Status.ACTIVE
    mock_client.confirm_mandate.assert_not_called()
