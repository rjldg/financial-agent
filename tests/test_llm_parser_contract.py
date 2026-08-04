"""Locks down what _chat actually sends to Ollama.

Nothing else asserted on the outgoing request shape - a future edit could
drop `format` (losing the schema constraint) or revert to the OpenAI-
compatible `/v1/chat/completions` endpoint (which doesn't support
keep_alive/num_ctx/top_k at all) and every other test would still pass.

Uses httpx.MockTransport, injected through the `app.llm_parser._transport`
test seam, so no real network call happens and no new dependency is added
(httpx is already required).
"""
import json

import httpx

import app.llm_parser as llm_parser
from app.categories import CATEGORIES
from app.llm_parser import parse_receipt, route_message


def _mock_chat(content: str) -> tuple[httpx.MockTransport, dict]:
    """A MockTransport that always answers with `content` and records the
    single outgoing request's JSON body for the test to inspect."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": content}})

    return httpx.MockTransport(handler), captured


async def test_route_message_sends_the_expected_ollama_chat_request(monkeypatch):
    transport, captured = _mock_chat(
        '{"intent":"unknown","transactions":[],"query":null}'
    )
    monkeypatch.setattr(llm_parser, "_transport", transport)

    result = await route_message("hello")

    assert result.intent == "unknown"
    request, body = captured["request"], captured["body"]

    assert request.url.path == "/api/chat"
    assert "format" in body
    category_enum = body["format"]["$defs"]["Transaction"]["properties"]["category"]["enum"]
    assert category_enum == CATEGORIES
    assert body["options"]["temperature"] == 0
    assert body["options"]["top_k"] == 1
    assert body["options"]["num_ctx"] == 2048
    assert body["keep_alive"] == "30m"
    assert body["stream"] is False


async def test_parse_receipt_keeps_a_shared_vision_model_loaded(monkeypatch):
    # Unloading the model on every receipt (keep_alive=0) is only correct
    # when OLLAMA_VISION_MODEL differs from OLLAMA_MODEL. By default they're
    # the same model, so unloading it here would be a silent perf regression
    # for ordinary text messages too.
    from app.config import OLLAMA_MODEL, OLLAMA_VISION_MODEL
    assert OLLAMA_VISION_MODEL == OLLAMA_MODEL

    transport, captured = _mock_chat(
        '{"amount":100,"category":"Food","description":"receipt","type":"Expense"}'
    )
    monkeypatch.setattr(llm_parser, "_transport", transport)

    txn = await parse_receipt(b"fake-image-bytes")

    assert txn.amount == 100
    assert captured["body"]["keep_alive"] == "30m"
