"""Transaction parsing against a local Ollama model."""

from __future__ import annotations

import asyncio
import base64
import functools
import json
import logging

import httpx

from app.categories import render_category_guide
from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_VISION_MODEL,
)
from app.models import RouterResult, Transaction

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 2


class RateLimitError(Exception):
    """Raised when the LLM API is unavailable after retries."""


class RouterParseError(Exception):
    """The model answered, but not in a shape we can use."""


@functools.lru_cache(maxsize=1)
def router_schema() -> dict:
    """The JSON schema Ollama constrains sampling to.

    Generated from the Pydantic model so it can never drift from what we then
    validate against. Ollama 0.32 resolves the $defs/$ref it contains.
    """
    return RouterResult.model_json_schema()


@functools.lru_cache(maxsize=1)
def render_router_prompt() -> str:
    """The system prompt: the rules, the category meanings, then worked examples."""
    return (
        "You log personal finance messages for a user in the Philippines. "
        "Respond with JSON only.\n\n"
        "RULES\n"
        "1. A thing plus a number is intent 'log' and an Expense, even with no verb.\n"
        "2. If the message ASKS something, intent is 'query' and you MUST fill the "
        '"query" object. Never leave "query" null when intent is "query".\n'
        "3. If the message has no number and asks nothing about money (greetings, "
        "chit-chat, thanks), intent is 'unknown'.\n"
        "4. Use only the categories listed below. Never invent one.\n\n"
        "CATEGORIES\n"
        f"{render_category_guide()}\n\n"
        "EXAMPLES\n"
        "user: carwash 250\n"
        '{"intent":"log","transactions":[{"amount":250,"category":"Transport",'
        '"description":"Carwash","type":"Expense"}]}\n\n'
        "user: jollibee 320 and grab 145\n"
        '{"intent":"log","transactions":[{"amount":320,"category":"Food",'
        '"description":"Jollibee","type":"Expense"},{"amount":145,'
        '"category":"Transport","description":"Grab","type":"Expense"}]}\n\n'
        # Every earlier worked log example is an Expense, which taught the model
        # that logging always means Expense - it started mis-typing real income
        # messages the same way. These two show the Income shape exists too.
        "user: this month's paycheck 20000\n"
        '{"intent":"log","transactions":[{"amount":20000,"category":"Salary",'
        '"description":"Paycheck","type":"Income"}]}\n\n'
        "user: client transferred 4000 for logo design\n"
        '{"intent":"log","transactions":[{"amount":4000,"category":"Freelance",'
        '"description":"Logo design","type":"Income"}]}\n\n'
        "user: how much did i spend on food this month\n"
        '{"intent":"query","transactions":[],"query":{"metric":"spend",'
        '"category":"Food","period":null}}\n\n'
        "user: what did i earn in 2026-07\n"
        '{"intent":"query","transactions":[],"query":{"metric":"income",'
        '"category":null,"period":"2026-07"}}\n\n'
        "user: what's my net for 2026-07\n"
        '{"intent":"query","transactions":[],"query":{"metric":"net",'
        '"category":null,"period":"2026-07"}}\n\n'
        "user: how many times did i spend on transport this month\n"
        '{"intent":"query","transactions":[],"query":{"metric":"count",'
        '"category":"Transport","period":null}}\n\n'
        "user: hello\n"
        '{"intent":"unknown","transactions":[],"query":null}\n'
    )


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


async def _chat(
    messages: list[dict],
    *,
    schema: dict | None = None,
    model: str | None = None,
    keep_alive: str | int = OLLAMA_KEEP_ALIVE,
) -> str:
    """POST to Ollama's native chat endpoint with retry/backoff; return the content.

    The native endpoint is required: keep_alive, num_ctx and top_k do not exist
    on the OpenAI-compatible one.
    """
    payload: dict = {
        "model": model or OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0,
            "top_k": 1,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": 256,
        },
    }
    if schema is not None:
        payload["format"] = schema

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat", json=payload
                )
                response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # 4xx errors are not retryable
            last_exc = exc
            # Sleeping after the last attempt only delays the "unavailable"
            # reply the user is about to get anyway - with a 120s timeout per
            # attempt that's real time wasted for nothing.
            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Ollama request failed (attempt %d/%d, retry in %ds): %s",
                    attempt + 1, _MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "Ollama request failed (attempt %d/%d, giving up): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
        except (KeyError, json.JSONDecodeError) as exc:
            raise RouterParseError(f"Unreadable response from Ollama: {exc}") from exc

    raise RateLimitError(
        f"Could not reach Ollama at {OLLAMA_BASE_URL} after {_MAX_RETRIES} retries."
    ) from last_exc


def parse_router_response(content: str) -> RouterResult:
    """Parse a router response (possibly fenced) into a RouterResult."""
    return RouterResult.model_validate_json(_strip_fences(content))


async def route_message(text: str) -> RouterResult:
    """Classify and extract a message via the local model.

    Raises RouterParseError when the answer cannot be read, so the caller can
    say something different from a genuine 'I did not understand that'.
    """
    content = await _chat(
        [
            {"role": "system", "content": render_router_prompt()},
            {"role": "user", "content": text},
        ],
        schema=router_schema(),
    )
    try:
        return parse_router_response(content)
    except Exception as exc:
        logger.error("Router parse failed for content: %s", content)
        raise RouterParseError(str(exc)) from exc


_RECEIPT_PROMPT = (
    "You read receipts. Extract the grand total, a short merchant description, "
    "the best-matching category, and type 'Expense'. Respond with JSON only.\n\n"
    "CATEGORIES\n"
    f"{render_category_guide()}"
)


def parse_receipt_response(content: str) -> Transaction:
    """Parse a receipt response (possibly fenced) into a Transaction."""
    return Transaction.model_validate_json(_strip_fences(content))


async def parse_receipt(image_bytes: bytes, mime: str = "image/jpeg") -> Transaction:
    """Extract a Transaction from a receipt image using the local vision model."""
    # Unload straight after when a separate vision model is configured, so the
    # two never fight over a 6 GB card. When they are the same model, staying
    # resident costs nothing.
    separate_model = OLLAMA_VISION_MODEL != OLLAMA_MODEL
    content = await _chat(
        [
            {"role": "system", "content": _RECEIPT_PROMPT},
            {
                "role": "user",
                "content": "Extract the transaction from this receipt.",
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            },
        ],
        schema=Transaction.model_json_schema(),
        model=OLLAMA_VISION_MODEL,
        keep_alive=0 if separate_model else OLLAMA_KEEP_ALIVE,
    )
    return parse_receipt_response(content)
