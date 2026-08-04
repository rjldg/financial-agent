"""Tier 0: settle the commonest messages without waking the model.

Deliberately narrow. Anything with a question word, a joining word, or more
than one number is handed to the model instead - booking a wrong amount costs
more than waiting a few seconds for a right one.
"""
from __future__ import annotations

import re
import unicodedata

from app.categories import LEXICON, classify_by_lexicon
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

# Small connective words that carry no category meaning by themselves. The fast
# path is context-blind - it can only see "one merchant word, one amount" - so a
# message is only allowed to keep words beyond those two if they're just glue
# like this. Anything else (e.g. "cooking", "delivery") could be the very
# context that flips the category, so it must fall through to the model instead.
_FILLER_WORDS = {"spent", "paid", "for", "on", "at", "bought", "in", "to", "my", "a"}


def _has_meaningful_leftover(text: str, category: str) -> bool:
    """True when words survive after stripping the amount and matched lexicon
    term(s) that aren't just filler - i.e. there's more going on in this
    message than a bare merchant and an amount.
    """
    low = _NUMBER.sub(" ", text.lower())
    for term, term_category in LEXICON.items():
        if term_category == category:
            low = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", " ", low)
    words = re.findall(r"[a-z]+", low)
    return any(word not in _FILLER_WORDS for word in words)


def _fold_dashes(text: str) -> str:
    """Fold every dash-like character to a plain ASCII "-".

    This used to be a literal allowlist of three characters (en dash, em
    dash, minus sign), and it was patched four separate times to add one
    more character each time someone found a new way to paste a disguised
    negative in - a bank statement export, a spreadsheet, a CJK input
    method. A literal list can never close that hole, because the next dash
    character is always missing until someone reports it. Folding by
    Unicode's own dash-punctuation category ("Pd") instead means any dash
    Unicode adds - past, present, or future - is handled automatically.
    Two characters that read as a dash to a person aren't in "Pd": U+2212
    MINUS SIGN (category "Sm", used by spreadsheets for negatives) and
    U+2043 HYPHEN BULLET (category "Po"), so those are named explicitly.
    """
    return "".join(
        "-" if unicodedata.category(c) == "Pd" or c in "−⁃" else c
        for c in text
    )


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


def _wrapped_in_parens(text: str, run: re.Match[str]) -> bool:
    """Accountants and spreadsheets write a negative by wrapping it in
    parentheses instead of using a minus sign - "(145)" means -145. Booking
    that as a positive expense silently flips the sign of a real transaction,
    so it has to be refused just as hard as a leading minus is.
    """
    start, end = run.span()
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    return before.endswith("(") and after.startswith(")")


def try_fast_parse(text: str) -> Transaction | None:
    """A Transaction when the message is plainly one spend, else None."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    # Phone keyboards autocorrect a typed hyphen into an en dash or em dash,
    # and Google Sheets / most finance apps render a negative with the
    # dedicated minus sign instead - fold all dash-alike characters to a
    # plain "-" once, up front. Everything downstream (the hyphen-near-amount
    # check, then the description cleanup at the end) already only knows
    # about the ASCII hyphen, and normalising here keeps it that way instead
    # of teaching every check its own dash list.
    stripped = _fold_dashes(stripped)
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
    if _wrapped_in_parens(stripped, digit_runs[0]):
        return None

    category = classify_by_lexicon(stripped)
    if category is None or category in _INCOME_CATEGORIES:
        return None
    if _has_meaningful_leftover(stripped, category):
        return None

    try:
        amount = float(numbers[0].replace(",", ""))
    except ValueError:
        return None
    if amount <= 0:
        return None

    # No need to list en/em dash or minus sign here too - they were folded to "-" above.
    description = _NUMBER.sub("", stripped).strip(" -:")
    return Transaction(
        amount=amount,
        category=category,
        description=description.title() or category,
        type="Expense",
    )
