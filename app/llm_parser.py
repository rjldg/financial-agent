"""LLM-based transaction parser using Google Gemini (google-genai SDK)."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel, Field

from app.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schema — the LLM is forced to return exactly this shape
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when the Gemini API returns 429 after exhausting retries."""


class Transaction(BaseModel):
    """Structured financial transaction extracted from natural language."""

    amount: float = Field(..., description="The monetary amount (always positive).")
    category: str = Field(
        ...,
        description=(
            "Best-fit category for the transaction. "
            "Examples: Food, Transport, Bills, Salary, Entertainment, Shopping, "
            "Health, Utilities, Rent, Freelance, Dating, Other."
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


# ---------------------------------------------------------------------------
# Gemini client (lazy-initialised, module-level singleton)
# ---------------------------------------------------------------------------

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a financial transaction parser. "
    "The user will send a short natural-language message about spending or "
    "receiving money. Extract the structured transaction details. "
    "If the currency or amount is ambiguous, make a best-effort guess. "
    "Always return a single Transaction object."
)

# Retry config for 429 / rate-limit errors
_MAX_RETRIES = 3
_BASE_DELAY = 5  # seconds


async def parse_transaction(text: str) -> Transaction:
    """Parse a natural-language message into a :class:`Transaction`.

    Uses Gemini's native structured-output support (response_schema)
    to guarantee the response matches the Pydantic model.

    Retries up to 3 times on 429 (rate limit) with exponential backoff.
    Raises :class:`RateLimitError` if all retries are exhausted.
    Raises other exceptions on non-rate-limit failures.
    """
    client = _get_client()
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"{_SYSTEM_PROMPT}\n\nMessage: {text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Transaction,
                ),
            )
            return Transaction.model_validate_json(response.text)

        except ClientError as exc:
            if exc.code == 429:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Gemini rate-limited (429). Retry %d/%d in %ds.",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = exc
                await asyncio.sleep(delay)
            else:
                raise

    raise RateLimitError(
        f"Gemini API rate limit exceeded after {_MAX_RETRIES} retries."
    ) from last_exc
