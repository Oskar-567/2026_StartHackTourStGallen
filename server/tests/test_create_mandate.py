from unittest.mock import MagicMock

import pytest
from django.core.management import CommandError, call_command

from api import services
from api.models import Mandate
from api.reference_policies import REFERENCE_POLICIES
from viseca.client import VisecaAPIError


@pytest.fixture
def mock_client(monkeypatch) -> MagicMock:
    client = MagicMock()
    client.create_mandate.return_value = {"draft_id": "draft-42"}
    client.confirm_mandate.return_value = {"mandate_id": "mandate-42"}
    monkeypatch.setattr(services, "get_client", lambda: client)
    return client


@pytest.mark.django_db
def test_creates_and_confirms_the_reference_policy_with_its_intent_spec(mock_client):
    call_command("create_mandate", "--scenario", "SCEN0002")

    mandate = Mandate.objects.get()
    policy = REFERENCE_POLICIES["SCEN0002"]
    assert mandate.status == Mandate.Status.ACTIVE
    assert mandate.mandate_id == "mandate-42"
    assert mandate.intent_spec == policy["intent_spec"]
    # The challenge API gets the rules but never the engine-only intent_spec.
    sent = mock_client.create_mandate.call_args.args[0]
    assert sent["hard_rules"] == policy["hard_rules"]
    assert "intent_spec" not in sent
    mock_client.confirm_mandate.assert_called_once_with("draft-42")


@pytest.mark.django_db
def test_draft_only_leaves_confirmation_to_the_customer(mock_client):
    call_command("create_mandate", "--scenario", "SCEN0002", "--draft-only")

    assert Mandate.objects.get().status == Mandate.Status.DRAFT
    mock_client.confirm_mandate.assert_not_called()


@pytest.mark.django_db
def test_an_api_rejection_is_a_readable_error(mock_client):
    mock_client.create_mandate.side_effect = VisecaAPIError(
        422, {"error": "bad rule"}, method="POST", path="/v1/mandates"
    )
    with pytest.raises(CommandError, match="bad rule"):
        call_command("create_mandate", "--scenario", "SCEN0002")


def test_an_unknown_scenario_is_refused():
    with pytest.raises(CommandError, match="No reference policy"):
        call_command("create_mandate", "--scenario", "SCEN9999")
