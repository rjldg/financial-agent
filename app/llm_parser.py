"""LLM-based transaction parser using a local Ollama model."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the LLM API is unavailable after retries."""


# The exact set of allowed categories — must match _FORMULA_CATEGORIES in sheets_db.py
Category = Literal[
    "Food",
    "Transport",
    "Bills",
    "Salary",
    "Entertainment",
    "Shopping",
    "Health",
    "Utilities",
    "Rent",
    "Freelance",
    "Dating",
    "Other",
]


class Transaction(BaseModel):
    """Structured financial transaction extracted from natural language."""

    amount: float = Field(..., description="The monetary amount (always positive).")
    category: Category = Field(
        ...,
        description=(
            "MUST be exactly one of: Food, Transport, Bills, Salary, "
            "Entertainment, Shopping, Health, Utilities, Rent, Freelance, "
            "Dating, Other. Do NOT invent new categories."
        ),
    )
    description: str = Field(
        ...,
        description="A short human-readable summary, e.g. 'McDo lunch'.",
    )
    type: Literal["Income", "Expense"] = Field(
        ...,
        description="'Income' if the user received money, 'Expense' if they spent it.",
    )


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

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Ollama connection failed. Retry %d/%d in %ds: %s",
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