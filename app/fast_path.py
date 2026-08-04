"""Tier 0: settle the commonest messages without waking the model.

Deliberately narrow. Anything with a question word, a joining word, or more
than one number is handed to the model instead - booking a wrong amount costs
more than waiting a few seconds for a right one.
"""
from __future__ import annotations

import re

from app.categories import classify_by_lexicon
from app.models import Transaction

_NUMBER = re.compile(r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)(?![\w.])")
# Same shape as _NUMBER but without the word-boundary guards, so it also
# catches digits glued to a letter (e.g. the "250" in "jollibee250"). Used
# only to notice when such a hidden amount exists, never to parse a value.
_ANY_DIGIT_RUN = re.compile(r"\d[\d,]*(?:\.\d+)?")
_QUESTION = re.compile(
    r"\?|(?<!\w)(how|what|when|where|why|which|who|did|do|does|is|are|"
    r"was|were|can|show|list|total)(?!\w)",
    re.IGNORECASE,
)
_JOINING = re.compile(r"(?<!\w)(and|plus|also)(?!\w)|[+;&]", re.IGNORECASE)

# The fast path always books an Expense, so anything earned must fall through.
_INCOME_CATEGORIES = {"Salary", "Freelance"}


def try_fast_parse(text: str) -> Transaction | None:
    """A Transaction when the message is plainly one spend, else None."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    if _QUESTION.search(stripped) or _JOINING.search(stripped):
        return None

    numbers = _NUMBER.findall(stripped)
    if len(numbers) != 1:
        return None
    # A digit run stuck to a word (no space) never shows up in `numbers` above,
    # so "jollibee250 mcdo 300" would otherwise look like one clean amount and
    # silently drop the 250. If any digit run went uncounted, refuse instead.
    if len(_ANY_DIGIT_RUN.findall(stripped)) != 1:
        return None

    category = classify_by_lexicon(stripped)
    if category is None or category in _INCOME_CATEGORIES:
        return None

    try:
        amount = float(numbers[0].replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None

    description = _NUMBER.sub("", stripped).strip(" -:–—")
    return Transaction(
        amount=amount,
        category=category,
        description=description.title() or category,
        type="Expense",
    )
