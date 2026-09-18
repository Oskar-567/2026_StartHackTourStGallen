"""The fact-extraction boundary.

Two things these tests protect. First, that a backend failing -- timeout,
crash, nonsense response -- produces *absent* facts rather than wrong ones,
because absent becomes a question to the customer while wrong becomes a wrong
decision. Second, that nothing a merchant writes can widen what comes back.

No network: every backend is exercised against a fake client.
"""

from __future__ import annotations

import sys
import types

import pytest

from facts import build_extractor
from facts.base import (
    ITEM_CATEGORIES,
    ExtractionItem,
    build_user_content,
    items_from_event,
    parse_response,
)
from facts.stand_in import StandInExtractor

_ITEMS = (
    ExtractionItem(line_no=1, item_name="Road-running shoes", item_details="size 43; returns 30d"),
)


class TestParseResponse:
    def test_reads_a_well_formed_response(self) -> None:
        facts = parse_response(
            '{"items": [{"line_no": 1, "category": "sporting_goods", "size": "43",'
            ' "colour": null, "type": "road running shoe", "material": null,'
            ' "return_days": "30"}]}',
            source="test",
        )
        item = facts.for_line(1)
        assert item is not None
        assert item.category == "sporting_goods"
        assert item.attributes == {"size": "43", "type": "road running shoe", "return_days": "30"}

    @pytest.mark.parametrize(
        "payload",
        [
            "not json at all",
            "{}",
            '{"items": "not a list"}',
            '{"items": [1, 2, 3]}',
            '{"items": [{"category": "groceries"}]}',  # no line_no
        ],
        ids=["garbage", "empty", "wrong-type", "scalars", "no-line-no"],
    )
    def test_unusable_responses_yield_no_facts_instead_of_raising(self, payload: str) -> None:
        facts = parse_response(payload, source="test")
        assert facts.items == ()
        assert facts.source == "test"

    def test_nulls_and_blanks_are_dropped_not_stored(self) -> None:
        """A dropped attribute reads as unknown downstream, which asks the customer."""
        facts = parse_response(
            '{"items": [{"line_no": 1, "category": "groceries", "size": null, "colour": "  ",'
            ' "type": 42, "material": null, "return_days": null}]}',
            source="test",
        )
        assert facts.for_line(1).attributes == {}

    def test_a_category_outside_the_vocabulary_becomes_unknown(self) -> None:
        """A model cannot invent a category that then matches nothing meaningfully."""
        facts = parse_response(
            '{"items": [{"line_no": 1, "category": "definitely_allowed", "size": null,'
            ' "colour": null, "type": null, "material": null, "return_days": null}]}',
            source="test",
        )
        assert facts.for_line(1).category is None


class TestTheExtractorIsNeverToldAboutThePolicy:
    def test_the_prompt_carries_only_the_listing(self) -> None:
        """The whole injection defence rests on this: there is no policy to leak."""
        content = build_user_content(_ITEMS)
        assert "Road-running shoes" in content
        for forbidden in ("limit", "mandate", "CHF", "budget", "policy", "approve", "decline"):
            assert forbidden.lower() not in content.lower()

    def test_only_name_and_details_leave_the_event(self) -> None:
        event = {
            "authorization": {
                "billing_amount_chf": 999.0,
                "card_id": "CA0001",
                "items": [
                    {
                        "line_no": 1,
                        "item_name": "Shoes",
                        "item_details": "size 43",
                        "unit_price": 199.0,
                    }
                ],
            }
        }
        extracted = items_from_event(event)
        assert extracted == (ExtractionItem(line_no=1, item_name="Shoes", item_details="size 43"),)


class TestStandIn:
    def test_repeats_the_structured_category_and_extracts_nothing(self) -> None:
        facts = StandInExtractor({1: "groceries"}).extract(_ITEMS)
        item = facts.for_line(1)
        assert item.category == "groceries"
        assert item.attributes == {}, "the stand-in must never invent an attribute"

    def test_a_category_outside_the_vocabulary_is_refused(self) -> None:
        assert StandInExtractor({1: "made_up"}).extract(_ITEMS).for_line(1).category is None


def _fake_module(name: str, attr: str, value) -> types.ModuleType:
    module = types.ModuleType(name)
    setattr(module, attr, value)
    return module


class TestBackendsFailSafe:
    def test_ollama_failure_yields_no_facts(self, monkeypatch) -> None:
        class BoomClient:
            def __init__(self, **kwargs) -> None:
                pass

            def chat(self, **kwargs):
                raise TimeoutError("model did not respond in time")

        monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", "Client", BoomClient))
        from facts.local import OllamaExtractor

        facts = OllamaExtractor(model="test-model").extract(_ITEMS)
        assert facts.items == ()
        assert facts.source == "ollama:test-model"

    def test_anthropic_failure_yields_no_facts(self, monkeypatch) -> None:
        class BoomClient:
            def __init__(self, **kwargs) -> None:
                self.messages = self

            def create(self, **kwargs):
                raise TimeoutError("request timed out")

        monkeypatch.setitem(
            sys.modules, "anthropic", _fake_module("anthropic", "Anthropic", BoomClient)
        )
        from facts.hosted import AnthropicExtractor

        facts = AnthropicExtractor(model="test-model").extract(_ITEMS)
        assert facts.items == ()

    def test_reasoning_is_disabled_and_generation_is_capped(self, monkeypatch) -> None:
        """Thinking tokens on a one-sentence extraction are pure deadline risk."""
        seen: dict = {}

        class RecordingClient:
            def __init__(self, **kwargs) -> None:
                pass

            def chat(self, **kwargs):
                seen.update(kwargs)
                return {"message": {"content": '{"items": []}'}}

        monkeypatch.setitem(
            sys.modules, "ollama", _fake_module("ollama", "Client", RecordingClient)
        )
        from facts.local import NUM_CTX, NUM_PREDICT, OllamaExtractor

        OllamaExtractor(model="test-model").extract(_ITEMS)
        assert seen["think"] is False
        assert seen["options"]["num_predict"] == NUM_PREDICT
        assert seen["options"]["num_ctx"] == NUM_CTX

    def test_a_client_too_old_for_think_still_works(self, monkeypatch) -> None:
        """Rather than fail every extraction over one keyword, stop sending it."""
        calls: list[dict] = []

        class OldClient:
            def __init__(self, **kwargs) -> None:
                pass

            def chat(self, **kwargs):
                calls.append(kwargs)
                if "think" in kwargs:
                    raise TypeError("chat() got an unexpected keyword argument 'think'")
                return {"message": {"content": '{"items": []}'}}

        monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", "Client", OldClient))
        from facts.local import OllamaExtractor

        extractor = OllamaExtractor(model="test-model")
        extractor.extract(_ITEMS)
        assert len(calls) == 2, "one rejected attempt, then one without `think`"
        extractor.extract(_ITEMS)
        assert len(calls) == 3, "and it must not keep retrying on every call"

    def test_ollama_success_path_parses(self, monkeypatch) -> None:
        payload = (
            '{"items": [{"line_no": 1, "category": "sporting_goods", "size": "43",'
            ' "colour": null, "type": null, "material": null, "return_days": "30"}]}'
        )

        class OkClient:
            def __init__(self, **kwargs) -> None:
                pass

            def chat(self, **kwargs):
                assert kwargs["keep_alive"] == -1, "the model must be held resident"
                assert kwargs["options"]["temperature"] == 0
                return {"message": {"content": payload}}

        monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", "Client", OkClient))
        from facts.local import OllamaExtractor

        facts = OllamaExtractor(model="test-model").extract(_ITEMS)
        assert facts.for_line(1).attributes["size"] == "43"


class TestBuildExtractor:
    def test_default_is_the_stand_in(self) -> None:
        assert isinstance(build_extractor("stand-in"), StandInExtractor)

    def test_an_unknown_backend_falls_back_rather_than_raising(self) -> None:
        assert isinstance(build_extractor("nonsense"), StandInExtractor)

    def test_an_unbuildable_backend_falls_back(self, monkeypatch) -> None:
        """A missing Ollama install must not stop the system from deciding."""
        monkeypatch.setitem(sys.modules, "ollama", None)
        assert isinstance(build_extractor("local"), StandInExtractor)


def test_the_vocabulary_matches_the_data_pack() -> None:
    """These are the categories the challenge data actually uses."""
    assert set(ITEM_CATEGORIES) == {
        "clothing",
        "cosmetics",
        "electronics",
        "gift_card",
        "groceries",
        "sporting_goods",
        "subscriptions",
    }
