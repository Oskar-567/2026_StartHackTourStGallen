import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def _no_model_in_tests(settings) -> None:
    """Tests never reach a model, whatever `FACTS_BACKEND` a developer's `.env` sets."""
    settings.FACTS_BACKEND = "stand-in"
