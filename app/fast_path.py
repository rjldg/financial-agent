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


def _hyphen_touches_number(text: str, run: re.Match[str]) -> bool:
    """A hyphen sitting right against the amount, glued or spaced out either way.

    "carwash-50", "carwash - 50" and "carwash -50" all read as a negative or
    typo'd amount to a person, but _NUMBER's word-boundary lookbehind only
    catches the minus when it's glued straight to the digits with nothing in
    between - a letter or a stray space in front of the hyphen makes it invisible
    to that check. Rather than special-case every way a hyphen can hide near a
    number, just strip the surrounding whitespace and see what's touching it.
    """
    start, end = run.span()
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    return before.endswith("-") or after.startswith("-")


def try_fast_parse(text: str) -> Transaction | None:
    """A Transaction when the message is plainly one spend, else None."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    # Phone keyboards autocorrect a typed hyphen into an en dash or em dash,
    # so fold those to a plain "-" once, up front. Everything downstream
    # (the hyphen-near-amount check, then the description cleanup at the
    # end) already only knows about the ASCII hyphen, and normalising here
    # keeps it that way instead of teaching every check its own dash list.
    stripped = stripped.replace("–", "-").replace("—", "-")
    if _QUESTION.search(stripped) or _JOINING.search(stripped):
        return None

    numbers = _NUMBER.findall(stripped)
    if len(numbers) != 1:
        return None
    # A digit run stuck to a word (no space) never shows up in `numbers` above,
    # so "jollibee250 mcdo 300" would otherwise look like one clean amount and
    # silently drop the 250. If any digit run went uncounted, refuse instead.
    digit_runs = list(_ANY_DIGIT_RUN.finditer(stripped))
    if len(digit_runs) != 1:
        return None
    if _hyphen_touches_number(stripped, digit_runs[0]):
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

    # No need to list en/em dash here too - they were folded to "-" above.
    description = _NUMBER.sub("", stripped).strip(" -:")
    return Transaction(
        amount=amount,
        category=category,
        description=description.title() or category,
        type="Expense",
    )
