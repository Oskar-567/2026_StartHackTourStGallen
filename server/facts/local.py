"""Local backend: a small model running on our own hardware, via Ollama.

Product text never leaves the machine. For a Swiss payments business owned by
banks that is a deployment property worth having, and this workload happens to
suit it: across the challenge data pack, `item_details` averages 56 characters
and never exceeds 276. Pulling a size and a return window out of one sentence
is extraction, not reasoning, and the output is schema-constrained so a small
model cannot drift into prose.

Two operational details decide whether this works in practice:

- **`keep_alive`.** Ollama unloads an idle model after a few minutes by
  default. The next request then pays a multi-second reload -- which, against
  an 8-second decision deadline, means a missed deadline. We hold the model
  resident and warm it at startup.
- **Timeouts.** A local model that stalls must fail fast enough for the
  worker's watchdog to still submit a deterministic decision in time.

Both failure modes end the same way: no facts, so the engine asks the customer
rather than guessing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from facts.base import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    ExtractedFacts,
    ExtractionItem,
    build_user_content,
    parse_response,
)

logger = logging.getLogger(__name__)


NUM_CTX = 2048
"""Context window for the request.

Our prompt is one system message plus a handful of short listings -- a few
hundred tokens. Ollama's default is larger, and every unused token still costs
KV-cache memory on a machine that is also running Postgres, Django and the app.
Raise this only if a basket ever gets long enough to be truncated.
"""

NUM_PREDICT = 512
"""Hard cap on generated tokens.

The answer is a small JSON object. Capping the output means a model that starts
rambling is cut off rather than eating the decision deadline.
"""


class OllamaExtractor:
    """Fact extraction against a local Ollama server."""

    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 4.0,
        keep_alive: int | str = -1,
        think: bool = False,
    ) -> None:
        # Imported here so a missing optional dependency only bites the backend
        # that needs it, never the worker, the tests, or CI.
        from ollama import Client

        self.name = f"ollama:{model}"
        self._model = model
        self._keep_alive = keep_alive
        self._think = think
        # Older clients have no `think` parameter. We find out on first use and
        # stop sending it, rather than failing every extraction over a keyword.
        self._send_think = True
        self._client = Client(host=host, timeout=timeout_seconds)

    def _chat(self, messages: list[dict[str, str]], **kwargs):
        """One chat call, tolerating a client that predates `think`."""
        if self._send_think:
            try:
                return self._client.chat(
                    model=self._model, messages=messages, think=self._think, **kwargs
                )
            except TypeError:
                logger.info(
                    "facts[%s]: installed ollama client has no 'think' parameter; "
                    "disable reasoning in the model or prompt instead",
                    self.name,
                )
                self._send_think = False
        return self._client.chat(model=self._model, messages=messages, **kwargs)

    def warm_up(self) -> bool:
        """Load the model before the first real purchase arrives.

        Called at worker startup. A cold first request is the single most
        likely way this backend misses a deadline, and it is entirely
        avoidable. Returns whether the model responded.
        """
        try:
            self._chat(
                [{"role": "user", "content": "ok"}],
                keep_alive=self._keep_alive,
                options={"num_predict": 1, "num_ctx": NUM_CTX},
            )
        except Exception as exc:  # noqa: BLE001 - startup probe, never fatal
            logger.warning("facts[%s]: warm-up failed (%s)", self.name, exc)
            return False
        logger.info("facts[%s]: model loaded and held resident", self.name)
        return True

    def extract(self, items: Sequence[ExtractionItem]) -> ExtractedFacts:
        if not items:
            return ExtractedFacts(source=self.name)
        try:
            response = self._chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_content(items)},
                ],
                format=RESPONSE_SCHEMA,
                keep_alive=self._keep_alive,
                options={
                    # Extraction, not creativity: the same listing must always
                    # yield the same facts, or a replay proves nothing.
                    "temperature": 0,
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                },
            )
        except Exception as exc:  # noqa: BLE001 - must never raise into the decision path
            logger.warning("facts[%s]: extraction failed (%s)", self.name, exc)
            return ExtractedFacts(source=self.name)
        return parse_response(response["message"]["content"], source=self.name)
