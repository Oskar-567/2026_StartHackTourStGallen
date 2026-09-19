"""Hosted backend: the same extraction against the Anthropic API.

Exists to be compared against `local.py`, on identical inputs, through the
offline replay. "We measured both" is a stronger claim than "we picked one".

Model choice is an environment variable, and the default is deliberate. The
challenge brief asks for small, low-latency models in the decision path, and
this is the narrowest possible task -- roughly sixty characters in, a handful
of schema-constrained fields out. Set `FACTS_MODEL` to a larger model if the
measurement says the extraction quality is not good enough; it is one variable,
and nothing else in the system changes.

Whatever the model, it is held to the same three rules as every backend (see
`facts/base.py`): it never sees the policy, it returns only structured values,
and any failure produces absent facts rather than a guess.
"""

from __future__ import annotations

import json
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

DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicExtractor:
    """Fact extraction against the Anthropic Messages API."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str = "",
        timeout_seconds: float = 4.0,
    ) -> None:
        # Imported here so a missing optional dependency only bites the backend
        # that needs it, never the worker, the tests, or CI.
        from anthropic import Anthropic

        self.name = f"anthropic:{model}"
        self._model = model
        # max_retries=0 is not a tuning choice: the decision deadline is 8
        # seconds from when the request was queued, and the SDK's default of two
        # retries can multiply wall-clock past it. The worker's watchdog is the
        # safety net, and it only works if this call fails promptly.
        self._client = Anthropic(api_key=api_key or None, timeout=timeout_seconds, max_retries=0)

    def extract(self, items: Sequence[ExtractionItem]) -> ExtractedFacts:
        if not items:
            return ExtractedFacts(source=self.name)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_content(items)}],
                output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            )
            if response.stop_reason == "refusal":
                logger.warning("facts[%s]: request refused; treating as no facts", self.name)
                return ExtractedFacts(source=self.name)
            text = next(block.text for block in response.content if block.type == "text")
        except (StopIteration, json.JSONDecodeError) as exc:
            logger.warning("facts[%s]: unusable response (%s)", self.name, exc)
            return ExtractedFacts(source=self.name)
        except Exception as exc:  # noqa: BLE001 - must never raise into the decision path
            logger.warning("facts[%s]: extraction failed (%s)", self.name, exc)
            return ExtractedFacts(source=self.name)
        return parse_response(text, source=self.name)
