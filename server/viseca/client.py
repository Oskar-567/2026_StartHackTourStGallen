"""Typed HTTP client for the challenge API (`technical_details.md`).

Two timing rules shape this module more than a typical API wrapper:

- The automated decision deadline is **8 seconds from when a request is
  queued** (challenge step 6), including time spent before delivery. A
  client that transparently retries a failed submit can burn that budget
  without the caller ever finding out, so **retries are off by default on
  every call**, and the decision-submission path (`submit_decision`) never
  retries even if a future caller asks for it elsewhere -- there is no
  `retries` parameter on that method at all.
- `GET /v1/decision-requests/next` long-polls and returns HTTP `204` with an
  empty body when there is no work yet. That is not an error and does not
  mean the run has finished (see `decision_requests_next`).

The API returns errors as JSON under `"error"`; this module checks the HTTP
status before treating any response as successful and raises `VisecaAPIError`
(carrying the status code and parsed body) otherwise. Never log the bearer
key: only method/path/status are logged, never the `Authorization` header.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("viseca.client")

#: Generic request timeout for cheap, non-deadline-sensitive calls.
DEFAULT_TIMEOUT = 10.0
#: Must exceed the `wait` query parameter passed to `decision_requests_next`
#: (the server holds the connection open for up to `wait` seconds).
DEFAULT_POLL_TIMEOUT = 30.0
#: Short timeout for the decision-submission path: leaves margin inside the
#: 8-second automated decision deadline for the response to come back and for
#: the worker's own bookkeeping.
DEFAULT_DECISION_TIMEOUT = 5.0


class VisecaConnectionError(Exception):
    """The challenge API could not be reached at all (network error or timeout)."""


class VisecaAPIError(Exception):
    """The challenge API answered with an HTTP error status.

    Carries the numeric `status_code` and the parsed response body (or raw
    text if the body was not JSON) so a caller can inspect the documented
    `error` field without this exception's message ever containing the
    bearer key.
    """

    def __init__(self, status_code: int, body: Any, *, method: str, path: str) -> None:
        self.status_code = status_code
        self.body = body
        self.method = method
        self.path = path
        detail = body.get("error") if isinstance(body, dict) else body
        super().__init__(f"{method} {path} -> HTTP {status_code}: {detail!r}")


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


class VisecaClient:
    """Thin, typed wrapper around every challenge API endpoint the worker and
    the mandate-lifecycle views need.

    Construct one per process (see `api/services.get_client`, which caches a
    single instance) rather than one per request: `httpx.Client` pools
    connections internally.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_timeout: float = DEFAULT_TIMEOUT,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
        decision_timeout: float = DEFAULT_DECISION_TIMEOUT,
        safe_retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`safe_retries` applies only to cheap, idempotent, non-deadline-sensitive
        GET calls (`healthz`, `bootstrap`, `reference_data`, `get_mandate`,
        `get_scenario_run`, `list_authorizations`, `events`); every write and
        the long-poll/decision path always use zero retries.

        `transport` is exposed purely for tests (e.g. `httpx.MockTransport`)
        so the test suite never makes a real network call; production code
        never passes it.
        """
        self._base_url = base_url.rstrip("/")
        self._default_timeout = default_timeout
        self._poll_timeout = poll_timeout
        self._decision_timeout = decision_timeout
        self._safe_retries = safe_retries
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VisecaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low-level request/response handling --------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float,
        retries: int = 0,
        raw_text: bool = False,
    ) -> Any:
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method, path, json=json, params=params, timeout=timeout
                )
            except httpx.TimeoutException as exc:
                raise VisecaConnectionError(f"{method} {path} timed out after {timeout}s") from exc
            except httpx.TransportError as exc:
                if attempt < retries:
                    attempt += 1
                    continue
                raise VisecaConnectionError(f"{method} {path} failed: {exc}") from exc

            logger.debug(
                "viseca_request",
                extra={"method": method, "path": path, "status": response.status_code},
            )

            if response.status_code == 204:
                # Long-polling's "no work yet" and a body-less DELETE/PATCH both
                # land here; callers get `None`, never an exception, for this case.
                return None
            if response.status_code >= 400:
                raise VisecaAPIError(
                    response.status_code, _safe_json(response), method=method, path=path
                )
            if raw_text:
                return response.text
            if not response.content:
                return None
            return response.json()

    # -- discovery ------------------------------------------------------------

    def healthz(self) -> dict:
        return self._request(
            "GET", "/healthz", timeout=self._default_timeout, retries=self._safe_retries
        )

    def bootstrap(self) -> dict:
        return self._request(
            "GET", "/v1/bootstrap", timeout=self._default_timeout, retries=self._safe_retries
        )

    def reference_data(self) -> dict:
        return self._request(
            "GET", "/v1/reference-data", timeout=self._default_timeout, retries=self._safe_retries
        )

    def authorization_history_csv(self) -> str:
        """Raw CSV text of the challenge API's historical authorization file."""
        return self._request(
            "GET",
            "/v1/reference-data/authorization-history.csv",
            timeout=self._default_timeout,
            retries=self._safe_retries,
            raw_text=True,
        )

    # -- mandate lifecycle ------------------------------------------------

    def create_mandate(self, payload: dict) -> dict:
        """`POST /v1/mandates`. `payload` carries `instruction`, `hard_rules`,
        `uncertainty_policy`, `guidance`, `open_questions`. Returns a body
        containing `draft_id`."""
        return self._request("POST", "/v1/mandates", json=payload, timeout=self._default_timeout)

    def confirm_mandate(self, draft_id: str) -> dict:
        """`POST /v1/mandates/{draft_id}/confirm`. Returns a body containing
        `mandate_id`. Only call this after the customer has agreed."""
        return self._request(
            "POST",
            f"/v1/mandates/{draft_id}/confirm",
            json={"confirmed": True},
            timeout=self._default_timeout,
        )

    def get_mandate(self, mandate_id: str) -> dict:
        return self._request(
            "GET",
            f"/v1/mandates/{mandate_id}",
            timeout=self._default_timeout,
            retries=self._safe_retries,
        )

    def patch_mandate(self, mandate_id: str, payload: dict) -> dict:
        """`PATCH /v1/mandates/{mandate_id}`: additive-only per the challenge
        rules (see `api/services.tighten_mandate` for the local-side checks)."""
        return self._request(
            "PATCH", f"/v1/mandates/{mandate_id}", json=payload, timeout=self._default_timeout
        )

    def delete_mandate(self, mandate_id: str) -> dict | None:
        """`DELETE /v1/mandates/{mandate_id}`: revokes the mandate."""
        return self._request("DELETE", f"/v1/mandates/{mandate_id}", timeout=self._default_timeout)

    # -- scenario runs --------------------------------------------------------

    def create_scenario_run(self, scenario_id: str, mandate_id: str) -> dict:
        return self._request(
            "POST",
            "/v1/scenario-runs",
            json={"scenario_id": scenario_id, "mandate_id": mandate_id},
            timeout=self._default_timeout,
        )

    def get_scenario_run(self, run_id: str) -> dict:
        return self._request(
            "GET",
            f"/v1/scenario-runs/{run_id}",
            timeout=self._default_timeout,
            retries=self._safe_retries,
        )

    # -- decision loop ----------------------------------------------------

    def decision_requests_next(self, *, wait: int = 25) -> dict | None:
        """Long-poll for the next decision request.

        Returns the envelope dict on HTTP `200`. Returns `None` on HTTP
        `204`: there is no work available *right now*, which is neither an
        error nor a sign that the run has finished -- the caller must check
        run progress separately and keep polling.
        """
        return self._request(
            "GET",
            "/v1/decision-requests/next",
            params={"wait": wait},
            timeout=self._poll_timeout,
            retries=0,
        )

    def submit_decision(self, authorization_id: str, payload: dict) -> dict:
        """`POST /v1/authorizations/{authorization_id}/decision`.

        Always zero retries, on a short timeout: this is the deadline-critical
        path (8 seconds from when the request was queued), and a retry here
        could cost more wall-clock time than the deadline allows.
        """
        body = {**payload, "authorization_id": authorization_id}
        return self._request(
            "POST",
            f"/v1/authorizations/{authorization_id}/decision",
            json=body,
            timeout=self._decision_timeout,
            retries=0,
        )

    def resolve(self, authorization_id: str, payload: dict) -> dict:
        """`POST /v1/authorizations/{authorization_id}/resolve`: forwards the
        real customer's answer to a `step_up`."""
        return self._request(
            "POST",
            f"/v1/authorizations/{authorization_id}/resolve",
            json=payload,
            timeout=self._default_timeout,
            retries=0,
        )

    def list_authorizations(self, **params: Any) -> dict:
        return self._request(
            "GET",
            "/v1/authorizations",
            params=params or None,
            timeout=self._default_timeout,
            retries=self._safe_retries,
        )

    def events(self, since: int = 0) -> dict:
        return self._request(
            "GET",
            "/v1/events",
            params={"since": since},
            timeout=self._default_timeout,
            retries=self._safe_retries,
        )
