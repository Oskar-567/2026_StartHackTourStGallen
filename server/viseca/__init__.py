"""HTTP client for the Viseca "Agent on a Leash" challenge API.

Framework-agnostic: no Django imports here. `api/services.py` is the glue that
reads `VISECA_BASE_URL` / `VISECA_API_KEY` from Django settings and builds a
`VisecaClient` for the views and the worker to share.
"""

from viseca.client import VisecaAPIError, VisecaClient, VisecaConnectionError

__all__ = ["VisecaAPIError", "VisecaClient", "VisecaConnectionError"]
