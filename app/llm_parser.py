"""LLM-based transaction parser using a local Ollama model."""

from __future__ import annotations

import base64
import asyncio
import json
import logging
import httpx
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from app.models import RouterResult, Transaction

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the LLM API is unavailable after retries."""


_SYSTEM_PROMPT = (
    "You are a financial transaction parser. "
    "The user will send a short natural-language message about spending or "
    "receiving money. Extract the structured transaction details. "
    "If the currency or amount is ambiguous, make a best-effort guess. "
    "\n\n"
    "IMPORTANT — the 'category' field MUST be EXACTLY one of these values "
    "(case-sensitive, no variations):\n"
    "  Food, Transport, Bills, Salary, Entertainment, Shopping, "
    "Health, Utilities, Rent, Freelance, Dating, Other\n"
    "Do NOT use any other category name like 'Groceries', 'Food & Dining', "
    "'Commute', etc. Map them to the closest allowed category.\n\n"
    "You MUST respond with ONLY a JSON object matching this exact schema, "
    "no other text:\n"
    '{"amount": <number>, "category": "<one of the allowed values>", '
    '"description": "<string>", "type": "<Income or Expense>"}'
)

_MAX_RETRIES = 3
_BASE_DELAY = 2


async def parse_transaction(text: str) -> Transaction:
    """Parse a natural-language message into a Transaction.

    Calls the local Ollama server's OpenAI-compatible endpoint.
    Retries up to 3 times on connection errors.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/v1/chat/completions",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": text},
                        ],
                        "temperature": 0.1,
                        "stream": False,
                    },
                )
                response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Strip markdown code fences if the model wraps its output
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            return Transaction.model_validate_json(content)

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # 4xx errors are not retryable
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Ollama request failed (attempt %d/%d, retry in %ds): %s",
                attempt + 1, _MAX_RETRIES, delay, exc,
            )
            last_exc = exc
            await asyncio.sleep(delay)

        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("Failed to parse LLM response: %s", exc)
            raise

    raise RateLimitError(
        f"Could not reach Ollama at {OLLAMA_BASE_URL} after {_MAX_RETRIES} retries."
    ) from last_exc


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


async def _chat(messages: list[dict], *, temperature: float = 0.1) -> str:
    """POST to Ollama's chat endpoint with retry/backoff; return message content."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/v1/chat/completions",
                    json={"model": OLLAMA_MODEL, "messages": messages,
                          "temperature": temperature, "stream": False},
                )
                response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # 4xx errors are not retryable
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning("Ollama request failed (attempt %d/%d, retry in %ds): %s",
                           attempt + 1, _MAX_RETRIES, delay, exc)
            last_exc = exc
            await asyncio.sleep(delay)
    raise RateLimitError(
        f"Could not reach Ollama at {OLLAMA_BASE_URL} after {_MAX_RETRIES} retries."
    ) from last_exc


_ROUTER_PROMPT = (
    "You are a finance assistant router. Classify the user's message and respond "
    "with ONLY a JSON object, no other text.\n\n"
    "Allowed categories: Food, Transport, Bills, Salary, Entertainment, Shopping, "
    "Health, Utilities, Rent, Freelance, Dating, Other. Map synonyms (Groceries->Food, "
    "Commute->Transport, etc). Never invent categories.\n\n"
    "If the user is recording one or more spends/incomes, use intent 'log' and fill "
    "'transactions' (support MULTIPLE items in one message):\n"
    '{"intent":"log","transactions":[{"amount":<number>,"category":"<allowed>",'
    '"description":"<short>","type":"Income|Expense"}]}\n\n'
    "If the user is ASKING a question about their finances, use intent 'query':\n"
    '{"intent":"query","query":{"metric":"spend|income|net|count",'
    '"category":<allowed-or-null>,"period":<"YYYY-MM"-or-null>}}\n\n'
    "If neither applies: {\"intent\":\"unknown\"}"
)


def parse_router_response(content: str) -> RouterResult:
    """Parse a router LLM response (possibly fenced) into a RouterResult."""
    return RouterResult.model_validate_json(_strip_fences(content))


async def route_message(text: str) -> RouterResult:
    """Classify + extract a message via the local LLM. Never raises on bad JSON."""
    content = await _chat(
        [{"role": "system", "content": _ROUTER_PROMPT}, {"role": "user", "content": text}]
    )
    try:
        return parse_router_response(content)
    except Exception:
        logger.error("Router parse failed for content: %s", content)
        return RouterResult(intent="unknown")


_RECEIPT_PROMPT = (
    "You read receipts. Extract the grand total amount, a short merchant/description, "
    "the best-matching category from: Food, Transport, Bills, Salary, Entertainment, "
    "Shopping, Health, Utilities, Rent, Freelance, Dating, Other, and type 'Expense'. "
    'Respond with ONLY JSON: {"amount":<number>,"category":"<allowed>",'
    '"description":"<string>","type":"Expense"}'
)


def build_image_data_uri(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    """Encode image bytes as an OpenAI-compatible data URI."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def parse_receipt_response(content: str) -> Transaction:
    """Parse a receipt LLM response (possibly fenced) into a Transaction."""
    return Transaction.model_validate_json(_strip_fences(content))


async def parse_receipt(image_bytes: bytes, mime: str = "image/jpeg") -> Transaction:
    """Extract a Transaction from a receipt image using the local vision model."""
    uri = build_image_data_uri(image_bytes, mime)
    content = await _chat([
        {"role": "system", "content": _RECEIPT_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": "Extract the transaction from this receipt."},
            {"type": "image_url", "image_url": {"url": uri}},
        ]},
    ])
    return parse_receipt_response(content)