"""Fact extraction: one seam, three interchangeable backends.

    FACTS_BACKEND=stand-in   structured fields only, no model, no network
    FACTS_BACKEND=local      a small model on our own hardware, via Ollama
    FACTS_BACKEND=hosted     the Anthropic API

Which one runs is an environment variable, never a code change. That makes the
deployment decision reversible, makes local and hosted measurable against each
other on identical inputs through `manage.py replay`, and means that if one
backend misbehaves at a venue the other is one variable away.

Nothing downstream knows or cares which is in use -- `engine.decide()` receives
the same `ExtractedFacts` either way, and records the backend's name in the
evidence so a decision can say where its inputs came from.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from engine.types import ExtractedFacts
from facts.base import ExtractionItem, FactExtractor, items_from_event
from facts.stand_in import StandInExtractor

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionItem",
    "FactExtractor",
    "StandInExtractor",
    "build_extractor",
    "extract_for_event",
    "items_from_event",
]


def extract_for_event(extractor: FactExtractor, event: dict[str, Any]) -> ExtractedFacts:
    """Run `extractor` over one raw event's cart lines.

    The stand-in is a special case: it reports the merchant's own structured
    `item_category` rather than reading text, so it needs those categories
    handed to it. Every model-backed extractor gets the text only.
    """
    items = items_from_event(event)
    if isinstance(extractor, StandInExtractor):
        extractor = StandInExtractor(
            {line["line_no"]: line["item_category"] for line in event["authorization"]["items"]}
        )
    return extractor.extract(items)


def build_extractor(backend: str | None = None) -> FactExtractor:
    """The configured extractor, or the stand-in if it cannot be built.

    Falling back rather than raising is deliberate: a missing Ollama server or
    an unset API key must not stop the system from deciding. It degrades to
    "no facts", which the engine reads as uncertainty and turns into a question
    for the customer -- the safe direction.
    """
    name = (backend or getattr(settings, "FACTS_BACKEND", "") or "stand-in").strip().lower()

    if name in ("stand-in", "standin", "none", ""):
        return StandInExtractor()

    try:
        if name == "local":
            from facts.local import OllamaExtractor

            return OllamaExtractor(
                model=settings.OLLAMA_MODEL,
                host=settings.OLLAMA_HOST,
                timeout_seconds=settings.FACTS_TIMEOUT_SECONDS,
                think=getattr(settings, "OLLAMA_THINK", False),
            )
        if name == "hosted":
            from facts.hosted import AnthropicExtractor

            return AnthropicExtractor(
                model=settings.FACTS_MODEL,
                api_key=settings.ANTHROPIC_API_KEY,
                timeout_seconds=settings.FACTS_TIMEOUT_SECONDS,
            )
    except Exception as exc:  # noqa: BLE001 - configuration problems must not be fatal
        logger.warning(
            "facts: backend %r could not be built (%s); falling back to the stand-in", name, exc
        )
        return StandInExtractor()

    logger.warning("facts: unknown backend %r; falling back to the stand-in", name)
    return StandInExtractor()
