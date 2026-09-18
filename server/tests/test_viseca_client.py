"""VisecaClient tests: no real network call is ever made -- every request is
served by an `httpx.MockTransport` handler.
"""

from __future__ import annotations

import json

import httpx
import pytest

from viseca.client import VisecaAPIError, VisecaClient, VisecaConnectionError


def _client(handler) -> VisecaClient:
    return VisecaClient(
        base_url="https://viseca.example",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


def test_decision_requests_next_returns_none_on_204_not_an_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/decision-requests/next"
        return httpx.Response(204)

    client = _client(handler)

    result = client.decision_requests_next(wait=25)

    assert result is None


def test_decision_requests_next_returns_envelope_on_200():
    envelope = {"run_id": "run-1", "data": {"type": "authorization.request"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    client = _client(handler)

    result = client.decision_requests_next(wait=25)

    assert result == envelope


def test_error_status_raises_viseca_api_error_with_status_and_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": {"code": "invalid_rule", "message": "bad rule"}})

    client = _client(handler)

    with pytest.raises(VisecaAPIError) as excinfo:
        client.create_mandate({"instruction": "x"})

    assert excinfo.value.status_code == 422
    assert excinfo.value.body == {"error": {"code": "invalid_rule", "message": "bad rule"}}


def test_error_status_with_non_json_body_is_still_raised_safely():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _client(handler)

    with pytest.raises(VisecaAPIError) as excinfo:
        client.healthz()

    assert excinfo.value.status_code == 500
    assert excinfo.value.body == "internal error"


def test_network_failure_raises_viseca_connection_error_not_httpx_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)

    with pytest.raises(VisecaConnectionError):
        client.bootstrap()


def test_submit_decision_never_retries_and_includes_authorization_id():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("boom")

    client = _client(handler)

    with pytest.raises(VisecaConnectionError):
        client.submit_decision("AU_LIVE_1", {"decision": "approve"})

    # No retry attempts: exactly one request was made despite the failure.
    assert len(calls) == 1


def test_submit_decision_posts_expected_path_and_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "accepted"})

    client = _client(handler)

    result = client.submit_decision("AU_LIVE_1", {"decision": "approve", "reason_codes": []})

    assert captured["path"] == "/v1/authorizations/AU_LIVE_1/decision"
    assert captured["body"]["authorization_id"] == "AU_LIVE_1"
    assert captured["body"]["decision"] == "approve"
    assert result == {"status": "accepted"}


def test_safe_get_retries_on_transport_error_then_succeeds():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("transient")
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)

    result = client.bootstrap()

    assert result == {"ok": True}
    assert attempts["count"] == 2


def test_authorization_key_never_appears_in_error_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = VisecaClient(
        base_url="https://viseca.example",
        api_key="super-secret-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(VisecaAPIError) as excinfo:
        client.healthz()

    assert "super-secret-key" not in str(excinfo.value)
