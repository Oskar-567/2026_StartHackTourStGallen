from unittest import mock

import pytest
from django.db import OperationalError, connections
from django.urls import reverse

from api import views


@pytest.mark.django_db
def test_health_returns_ok_and_version_when_database_is_reachable(api_client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")

    response = api_client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "abc123"}


def test_health_returns_503_when_database_is_unreachable(api_client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setattr(views, "database_is_reachable", lambda: False)

    response = api_client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error", "version": "local"}


def test_database_is_reachable_returns_false_on_database_error():
    with mock.patch.object(
        connections["default"], "cursor", side_effect=OperationalError("connection refused")
    ):
        assert views.database_is_reachable() is False
