"""Stand-in backend: no model at all.

Repeats the structured `item_category` the merchant already supplied and
extracts nothing from free text. It exists so the whole path -- intent spec in,
facts in, semantic checks comparing, decision out -- can be exercised without
any model, key, or network, and so that `replay` still works on a machine with
neither.

Because it invents nothing, every attribute stays unknown, and a purchase whose
policy requires one (a shoe size, say) still resolves to `step_up`. That is the
honest answer, and it marks exactly where a real backend earns its place.

It also reports `category_verified=False`, because repeating the seller's own
label is not verification. A basket therefore cannot be *approved* on stand-in
facts alone -- though an item the merchant itself labels outside the customer's
purpose is still declined.

It is also the control in the local-vs-hosted comparison: the floor that any
model has to beat.
"""

from __future__ import annotations

from collections.abc import Sequence

from engine.types import ExtractedFacts, ItemFacts
from facts.base import ITEM_CATEGORIES, ExtractionItem


class StandInExtractor:
    """Facts from already-structured fields; no text is read."""

    name = "stand-in"

    def __init__(self, categories_by_line: dict[int, str] | None = None) -> None:
        self._categories_by_line = categories_by_line or {}

    def extract(self, items: Sequence[ExtractionItem]) -> ExtractedFacts:
        return ExtractedFacts(
            items=tuple(
                ItemFacts(
                    line_no=item.line_no,
                    category=self._category_for(item.line_no),
                    # Never verified: this is the merchant's own label, repeated.
                    category_verified=False,
                )
                for item in items
            ),
            source=self.name,
        )

    def _category_for(self, line_no: int) -> str | None:
        category = self._categories_by_line.get(line_no)
        return category if category in ITEM_CATEGORIES else None
