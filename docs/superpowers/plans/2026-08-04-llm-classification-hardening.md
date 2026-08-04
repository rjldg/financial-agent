# LLM Classification Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transaction categorization reliable by pinning known merchants deterministically and constraining the model's output at decode time, and make the model's cost predictable on a 6 GB GPU.

**Architecture:** Two tiers. A lexicon plus a strict regex settles the commonest messages (`carwash 250`) with no inference at all. Everything else goes to one Ollama `/api/chat` call whose `format` is a JSON schema generated from the existing `RouterResult` Pydantic model, so the category enum is enforced by the sampler rather than requested in prose. The category table becomes the single source of truth for the prompt, the sheet dropdown and the type system.

**Tech Stack:** Python 3.11, httpx, Pydantic v2, Ollama 0.32 (`gemma3:4b`), pytest.

## Global Constraints

- The twelve categories are **fixed**: Food, Transport, Bills, Salary, Entertainment, Shopping, Health, Utilities, Rent, Freelance, Dating, Other. Never add, rename or remove one.
- Target model is `gemma3:4b`; it serves both text and vision. Do not change `OLLAMA_MODEL` defaults.
- Ollama calls use the native `/api/chat` endpoint, never `/v1/chat/completions`.
- Decoding is greedy: `temperature: 0`, `top_k: 1`. Evals must be reproducible.
- `num_ctx: 2048`, `keep_alive: "30m"` for text calls. Measured at 2.68 GB VRAM.
- No new runtime dependencies. `httpx` and `pydantic` are already in `requirements.txt`.
- Every task ends with a passing `python -m pytest -q` and a commit.
- `tests/test_config_validation.py::test_validate_config_flags_missing_credentials_file` fails on this machine before you start (it asserts `service_account.json` is absent; it exists locally). That one pre-existing failure is expected — do not fix it, and do not count it as a regression.

## File Structure

| File | Responsibility |
| --- | --- |
| `app/categories.py` *(new)* | The taxonomy: what each category means, which words pin one down, and how to render it into a prompt. Single source of truth. |
| `app/fast_path.py` *(new)* | Tier 0. Turns an unambiguous single-spend message into a `Transaction` without the model. |
| `app/llm_parser.py` *(modify)* | Tier 1. `/api/chat` transport, schema generation, prompt assembly, receipt parsing. Legacy single-call path deleted. |
| `app/models.py` *(modify)* | Imports `CATEGORIES` from `app/categories.py` instead of redeclaring it. |
| `app/sheets/transactions.py` *(modify)* | `FORMULA_CATEGORIES` becomes an alias of `CATEGORIES`. |
| `app/config.py` *(modify)* | Drops `USE_INTENT_ROUTER`; adds vision model and Ollama tuning knobs. |
| `app/bot/handlers/transactions.py` *(modify)* | Calls Tier 0 then Tier 1; tells a parse failure apart from a genuine `unknown`. |
| `tests/fixtures/router_eval.jsonl` *(new)* | ~120 labeled cases. Ground truth for accuracy. |
| `scripts/eval_router.py` *(new)* | Scores a model+config against the fixture. Confusion matrix, latency, VRAM. |
| `scripts/benchmark_models.py` *(new)* | Sweeps candidate models and Ollama toggles into one table. |
| `pytest.ini` *(modify)* | Registers the `integration` marker and excludes it by default. |

---

### Task 1: Category taxonomy as single source of truth

Replaces five hand-maintained copies of the category list (`app/models.py:10`, `app/sheets/transactions.py:19`, and three prompt strings in `app/llm_parser.py`) with one table that also carries the meanings the model needs.

**Files:**
- Create: `app/categories.py`
- Create: `tests/test_categories.py`
- Modify: `app/models.py:10-13`
- Modify: `app/sheets/transactions.py:19-22`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CATEGORY_GUIDE: dict[str, str]` — category name to plain-English meaning.
  - `CATEGORIES: list[str]` — the twelve names, in `CATEGORY_GUIDE` order.
  - `LEXICON: dict[str, str]` — lowercase term to category name.
  - `render_category_guide() -> str`
  - `classify_by_lexicon(text: str) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_categories.py`:

```python
from typing import get_args

from app.categories import (
    CATEGORIES,
    CATEGORY_GUIDE,
    LEXICON,
    classify_by_lexicon,
    render_category_guide,
)
from app.models import Category


def test_the_four_category_lists_cannot_drift_apart():
    # A Literal must be static, so the type system cannot enforce this. A test does.
    assert set(CATEGORIES) == set(get_args(Category))
    assert set(CATEGORIES) == set(CATEGORY_GUIDE)
    assert set(LEXICON.values()) <= set(CATEGORIES)


def test_every_category_has_a_meaning():
    for name, meaning in CATEGORY_GUIDE.items():
        assert meaning.strip(), f"{name} has no meaning for the model to read"


def test_render_category_guide_lists_every_category():
    rendered = render_category_guide()
    for name in CATEGORIES:
        assert name in rendered


def test_known_merchants_resolve():
    assert classify_by_lexicon("carwash 250") == "Transport"
    assert classify_by_lexicon("meralco 2400") == "Utilities"
    assert classify_by_lexicon("jollibee 320") == "Food"
    assert classify_by_lexicon("load 100") == "Bills"
    assert classify_by_lexicon("haircut 150") == "Health"


def test_unknown_text_resolves_to_nothing():
    assert classify_by_lexicon("bought a widget 200") is None
    assert classify_by_lexicon("") is None


def test_matches_whole_words_only():
    # "load" must not fire inside "download"
    assert classify_by_lexicon("download 100") is None


def test_two_categories_in_one_message_is_refused():
    # Too mixed to pin down; Tier 1 should decide instead.
    assert classify_by_lexicon("jollibee and grab") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_categories.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.categories'`

- [ ] **Step 3: Write the implementation**

Create `app/categories.py`:

```python
"""The category taxonomy: what each category means, and which words pin one down.

This is the only place the twelve categories are described. The prompt, the
sheet's dropdown and the type alias all read from here.
"""
from __future__ import annotations

import re

CATEGORY_GUIDE: dict[str, str] = {
    "Food": "meals, groceries, coffee, restaurants, food delivery, snacks",
    "Transport": (
        "fare, jeep, bus, taxi, Grab, gas, fuel, parking, toll, carwash, "
        "car maintenance, LTO registration"
    ),
    "Bills": "phone load, internet, mobile plan, cable, streaming subscriptions",
    "Salary": "salary or payroll received from an employer",
    "Entertainment": "movies, games, concerts, bars, hobbies",
    "Shopping": "clothes, gadgets, Shopee or Lazada orders, household goods",
    "Health": "medicine, pharmacy, doctor, dentist, gym, haircut, salon, personal care",
    "Utilities": "electricity (Meralco), water (Maynilad), LPG and gas utility bills",
    "Rent": "rent, dorm, condo association dues",
    "Freelance": "income from clients or side projects",
    "Dating": "dates, gifts for a partner",
    "Other": "transfers, cash in or out, anything with no clear home",
}

CATEGORIES: list[str] = list(CATEGORY_GUIDE)

# Terms that settle a category on their own. Income categories are deliberately
# absent: the fast path always writes an Expense, so letting "salary" match here
# would book earnings as spending.
LEXICON: dict[str, str] = {
    # Transport
    "carwash": "Transport", "car wash": "Transport", "grab": "Transport",
    "angkas": "Transport", "jeep": "Transport", "jeepney": "Transport",
    "tricycle": "Transport", "toll": "Transport", "parking": "Transport",
    "gas": "Transport", "gasoline": "Transport", "fuel": "Transport",
    "shell": "Transport", "petron": "Transport", "caltex": "Transport",
    "lto": "Transport", "mrt": "Transport", "lrt": "Transport", "fare": "Transport",
    # Food
    "jollibee": "Food", "mcdo": "Food", "mcdonalds": "Food", "kfc": "Food",
    "chowking": "Food", "mang inasal": "Food", "starbucks": "Food",
    "grocery": "Food", "groceries": "Food", "puregold": "Food",
    "lunch": "Food", "dinner": "Food", "breakfast": "Food", "merienda": "Food",
    # Bills
    "load": "Bills", "globe": "Bills", "smart": "Bills", "converge": "Bills",
    "pldt": "Bills", "netflix": "Bills", "spotify": "Bills",
    # Utilities
    "meralco": "Utilities", "maynilad": "Utilities", "manila water": "Utilities",
    "lpg": "Utilities",
    # Health
    "haircut": "Health", "salon": "Health", "barber": "Health",
    "mercury drug": "Health", "watsons": "Health", "dentist": "Health",
    "gym": "Health", "medicine": "Health",
    # Shopping
    "shopee": "Shopping", "lazada": "Shopping", "uniqlo": "Shopping",
    # Rent
    "rent": "Rent",
}


def render_category_guide() -> str:
    """The category block that goes into the router prompt."""
    return "\n".join(f"{name} - {meaning}" for name, meaning in CATEGORY_GUIDE.items())


def classify_by_lexicon(text: str) -> str | None:
    """The category a message clearly belongs to, or None when it is not clear.

    Returns None when nothing matches, and also when terms from two different
    categories both appear - a mixed message is Tier 1's job, not ours.
    """
    if not text or not text.strip():
        return None
    low = text.lower()
    matched = {
        category
        for term, category in LEXICON.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", low)
    }
    if len(matched) == 1:
        return matched.pop()
    return None
```

- [ ] **Step 4: Point the old lists at the new one**

In `app/models.py`, replace lines 10-13 (the `CATEGORIES` literal) with an import. Keep the `Category` Literal exactly as it is — a `Literal` must be static for type-checking, and the test in Step 1 guards it against drift.

```python
from app.categories import CATEGORIES  # noqa: F401  (re-exported for callers)
```

Place that import directly under the existing `from pydantic import BaseModel, Field` line, and delete the `CATEGORIES: list[str] = [...]` block.

In `app/sheets/transactions.py`, replace lines 19-22 with:

```python
from app.categories import CATEGORIES

# The sheet's data-validation dropdown must offer exactly the allowed categories.
FORMULA_CATEGORIES = CATEGORIES
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all tests pass except the one pre-existing `test_config_validation` failure noted in Global Constraints.

- [ ] **Step 6: Commit**

```bash
git add app/categories.py app/models.py app/sheets/transactions.py tests/test_categories.py
git commit -m "refactor: make the category taxonomy a single source of truth"
```

---

### Task 2: Tier 0 fast path

Settles `carwash 250`, `load 100`, `meralco 2400` and friends with no inference. These are precisely the messages that failed before.

**Files:**
- Create: `app/fast_path.py`
- Create: `tests/test_fast_path.py`

**Interfaces:**
- Consumes: `classify_by_lexicon` from `app/categories.py`; `Transaction` from `app/models.py`.
- Produces: `try_fast_parse(text: str) -> Transaction | None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fast_path.py`:

```python
from app.fast_path import try_fast_parse


def test_bare_merchant_and_amount_is_parsed():
    txn = try_fast_parse("carwash 250")
    assert txn is not None
    assert txn.amount == 250
    assert txn.category == "Transport"
    assert txn.type == "Expense"
    assert txn.description


def test_amount_may_come_first():
    txn = try_fast_parse("250 carwash")
    assert txn is not None and txn.amount == 250


def test_thousands_separator_is_understood():
    txn = try_fast_parse("meralco 2,400")
    assert txn is not None and txn.amount == 2400


def test_questions_are_refused():
    assert try_fast_parse("how much did i spend on grab") is None
    assert try_fast_parse("did i pay meralco 2400?") is None


def test_multiple_items_are_refused():
    assert try_fast_parse("jollibee 320 and grab 145") is None
    assert try_fast_parse("jollibee 320, grab 145") is None


def test_more_than_one_number_is_refused():
    assert try_fast_parse("grab 145 250") is None


def test_no_number_is_refused():
    assert try_fast_parse("carwash") is None


def test_unknown_merchant_is_refused():
    assert try_fast_parse("widget 200") is None


def test_zero_and_negative_amounts_are_refused():
    assert try_fast_parse("carwash 0") is None


def test_income_never_takes_the_fast_path():
    # The fast path always writes an Expense, so income must fall through.
    from app.categories import LEXICON
    assert "salary" not in LEXICON
    assert "freelance" not in LEXICON
    assert try_fast_parse("salary 25000") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fast_path.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.fast_path'`

- [ ] **Step 3: Write the implementation**

Create `app/fast_path.py`:

```python
"""Tier 0: settle the commonest messages without waking the model.

Deliberately narrow. Anything with a question word, a joining word, or more
than one number is handed to the model instead - booking a wrong amount costs
more than waiting a few seconds for a right one.
"""
from __future__ import annotations

import re

from app.categories import classify_by_lexicon
from app.models import Transaction

_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w.])")
_QUESTION = re.compile(
    r"\?|(?<!\w)(how|what|when|where|why|which|who|did|do|does|is|are|"
    r"was|were|can|show|list|total)(?!\w)",
    re.IGNORECASE,
)
_JOINING = re.compile(r"(?<!\w)(and|plus|also)(?!\w)|[+,;&]", re.IGNORECASE)

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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_fast_path.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add app/fast_path.py tests/test_fast_path.py
git commit -m "feat: settle unambiguous single-spend messages without the model"
```

---

### Task 3: Ollama transport, schema constraint and prompt

Moves to `/api/chat` (the only endpoint exposing `keep_alive`, `num_ctx` and `top_k`), enforces the enum at decode time, and installs the prompt validated during design at 11/11 on intent and query shape.

**Files:**
- Modify: `app/config.py:15-17`
- Modify: `app/llm_parser.py` (whole file)
- Create: `tests/test_llm_parser_prompt.py`

**Interfaces:**
- Consumes: `render_category_guide` from `app/categories.py`; `RouterResult`, `Transaction` from `app/models.py`.
- Produces:
  - `RouterParseError` (exception)
  - `router_schema() -> dict`
  - `render_router_prompt() -> str`
  - `route_message(text: str) -> RouterResult` (raises `RouterParseError`, `RateLimitError`)
  - `parse_receipt(image_bytes: bytes, mime: str = "image/jpeg") -> Transaction`
  - `parse_router_response(content: str) -> RouterResult`

- [ ] **Step 1: Add the config knobs**

In `app/config.py`, replace lines 15-17 with:

```python
# --- Local LLM (Ollama) ---
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
# gemma3:4b reads images too, so by default one model serves text and receipts
# and no swap ever happens. Point this elsewhere only if the text model changes.
OLLAMA_VISION_MODEL: str = os.environ.get("OLLAMA_VISION_MODEL", OLLAMA_MODEL)
# 2048 fits the prompt (~600 tokens) and measured 2.68 GB on a 6 GB card.
OLLAMA_NUM_CTX: int = int(os.environ.get("OLLAMA_NUM_CTX", "2048"))
OLLAMA_KEEP_ALIVE: str = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
```

Then delete the `USE_INTENT_ROUTER` flag: remove lines 66-68 (the comment block and the assignment). Leave `ENABLE_RECEIPT_OCR` alone.

- [ ] **Step 2: Write the failing test**

Create `tests/test_llm_parser_prompt.py`:

```python
from app.categories import CATEGORIES
from app.llm_parser import parse_router_response, render_router_prompt, router_schema
from app.models import RouterResult


def test_schema_is_generated_from_the_model_not_hand_written():
    schema = router_schema()
    # Hand-writing this is how the query object went missing during design.
    assert set(schema["properties"]) == {"intent", "transactions", "query"}


def test_schema_pins_the_category_enum():
    schema = router_schema()
    txn = schema["$defs"]["Transaction"]
    assert txn["properties"]["category"]["enum"] == CATEGORIES


def test_prompt_carries_every_category_meaning():
    prompt = render_router_prompt()
    for name in CATEGORIES:
        assert name in prompt


def test_prompt_teaches_the_three_intents():
    prompt = render_router_prompt()
    for shape in ('"intent":"log"', '"intent":"query"', '"intent":"unknown"'):
        assert shape in prompt


def test_prompt_shows_a_multi_item_example():
    # Single-item-only examples made the model collapse two spends into one.
    prompt = render_router_prompt()
    assert prompt.count('"amount"') >= 3


def test_parse_router_response_handles_fences():
    js = ('```json\n{"intent":"log","transactions":[{"amount":150,'
          '"category":"Food","description":"lunch","type":"Expense"}]}\n```')
    result = parse_router_response(js)
    assert isinstance(result, RouterResult)
    assert result.transactions[0].category == "Food"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_parser_prompt.py -q`
Expected: FAIL with `ImportError: cannot import name 'render_router_prompt'`

- [ ] **Step 4: Rewrite `app/llm_parser.py`**

Replace the entire file with:

```python
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
        "user: how much did i spend on food this month\n"
        '{"intent":"query","transactions":[],"query":{"metric":"spend",'
        '"category":"Food","period":null}}\n\n'
        "user: what did i earn in 2026-07\n"
        '{"intent":"query","transactions":[],"query":{"metric":"income",'
        '"category":null,"period":"2026-07"}}\n\n'
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
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Ollama request failed (attempt %d/%d, retry in %ds): %s",
                attempt + 1, _MAX_RETRIES, delay, exc,
            )
            last_exc = exc
            await asyncio.sleep(delay)
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
```

Note what this removes: `parse_transaction`, `_SYSTEM_PROMPT`, `_ROUTER_PROMPT`, `build_image_data_uri`, and the duplicated retry loop that `parse_transaction` carried.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_llm_parser_prompt.py tests/test_router.py -q`
Expected: PASS. `tests/test_router.py` still passes unchanged — `parse_router_response` keeps its signature.

- [ ] **Step 6: Verify against the real model**

Run:

```bash
python -c "import asyncio; from app.llm_parser import route_message; print(asyncio.run(route_message('meralco 2400')))"
```

Expected: `intent='log'` with one transaction, `category='Utilities'`. Requires Ollama running with `gemma3:4b`.

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/llm_parser.py tests/test_llm_parser_prompt.py
git commit -m "feat: constrain router output with a generated JSON schema over /api/chat"
```

---

### Task 4: Wire both tiers into the handler

Puts Tier 0 in front of Tier 1, deletes the legacy single-call path, and stops a malformed answer from masquerading as "I didn't understand".

**Files:**
- Modify: `app/bot/handlers/transactions.py:21-75`
- Modify: `.env.example:29-32`
- Create: `tests/test_message_routing.py`

**Interfaces:**
- Consumes: `try_fast_parse` (Task 2); `route_message`, `RouterParseError`, `RateLimitError` (Task 3).
- Produces: no new public names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_message_routing.py`:

```python
import app.bot.handlers.transactions as handlers


class _Recorder:
    """Stands in for a Telegram message, capturing what we would have sent."""

    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def test_legacy_single_call_path_is_gone():
    # The router handles single transactions strictly better; the flag protected nothing.
    assert not hasattr(handlers, "_handle_log_direct")
    import app.config
    assert not hasattr(app.config, "USE_INTENT_ROUTER")


def test_fast_path_is_tried_before_the_model(monkeypatch):
    called = {"router": False}

    async def _boom(text):
        called["router"] = True
        raise AssertionError("the model must not be called for a lexicon hit")

    monkeypatch.setattr(handlers, "route_message", _boom)
    from app.fast_path import try_fast_parse

    assert try_fast_parse("carwash 250") is not None
    assert called["router"] is False


def test_parse_failure_reads_differently_from_a_genuine_unknown():
    from app.llm_parser import RouterParseError

    assert handlers._UNREADABLE_REPLY != handlers._UNKNOWN_REPLY
    assert issubclass(RouterParseError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_message_routing.py -q`
Expected: FAIL — `_handle_log_direct` still exists and `_UNREADABLE_REPLY` is not defined.

- [ ] **Step 3: Rewrite the handler entry point**

In `app/bot/handlers/transactions.py`, change the import on line 12 to:

```python
from app.llm_parser import RateLimitError, RouterParseError, parse_receipt, route_message
```

Add below it:

```python
from app.fast_path import try_fast_parse
```

Add these module-level constants just under `logger = logging.getLogger(__name__)`:

```python
_UNKNOWN_REPLY = (
    "❌ Sorry, I couldn't understand that. Try 'spent 200 on groceries' "
    "or ask 'how much did I spend on food this month?'"
)
_UNREADABLE_REPLY = (
    "❌ The AI gave me an answer I couldn't read. Please try rephrasing that."
)
```

Replace `message_handler` (lines 21-54) and delete `_handle_log_direct` (lines 57-74) entirely:

```python
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return
    text = update.message.text
    logger.info("Received message from %s: %s", update.effective_user.id, text)

    # Tier 0: a known merchant and a single amount needs no inference at all.
    fast = try_fast_parse(text)
    if fast is not None:
        await _handle_log(update, [fast])
        return

    try:
        result = await route_message(text)
    except RateLimitError:
        await update.message.reply_text(
            "⏳ The AI service is rate-limited right now. Please wait a minute and try again."
        )
        return
    except RouterParseError:
        logger.exception("Router returned an unusable answer for: %s", text)
        await update.message.reply_text(_UNREADABLE_REPLY)
        return
    except Exception:
        logger.exception("Routing failed for message: %s", text)
        await update.message.reply_text("❌ Something went wrong understanding that message.")
        return

    if result.intent == "query" and result.query:
        await _handle_query(update, result.query)
        return
    if result.intent == "log" and result.transactions:
        await _handle_log(update, result.transactions)
        return
    await update.message.reply_text(_UNKNOWN_REPLY)
```

- [ ] **Step 4: Drop the retired flag from `.env.example`**

In `.env.example`, delete these four lines (29-32):

```
# Set to false to bypass the intent router and use the original single-call
# parser (one transaction per message; no multi-item logging or NL queries).
USE_INTENT_ROUTER=true
```

Leave the `ENABLE_RECEIPT_OCR` lines in place.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass except the known `test_config_validation` failure.

- [ ] **Step 6: Commit**

```bash
git add app/bot/handlers/transactions.py .env.example tests/test_message_routing.py
git commit -m "feat: try the fast path first and stop hiding unreadable model output"
```

---

### Task 5: Eval fixture and scorer

Makes accuracy measurable. Until this exists, every prompt or model change is unverifiable.

**Files:**
- Create: `tests/fixtures/router_eval.jsonl`
- Create: `scripts/eval_router.py`
- Create: `tests/test_eval_fixture.py`
- Modify: `pytest.ini`

**Interfaces:**
- Consumes: `try_fast_parse` (Task 2); `route_message` (Task 3); `CATEGORIES` (Task 1).
- Produces: `scripts/eval_router.py` as a CLI. Fixture record shape:
  `{"text": str, "intent": "log"|"query"|"unknown", "transactions": [{"amount": float, "category": str, "type": "Income"|"Expense"}], "query": {"metric": str, "category": str|null, "period": str|null}|null}`

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/router_eval.jsonl`, one JSON object per line. Write **at least 120** records covering every bucket below. Start with these, which encode the measured failures — then extend to the counts shown.

```jsonl
{"text":"carwash 250","intent":"log","transactions":[{"amount":250,"category":"Transport","type":"Expense"}],"query":null}
{"text":"load 100","intent":"log","transactions":[{"amount":100,"category":"Bills","type":"Expense"}],"query":null}
{"text":"meralco 2400","intent":"log","transactions":[{"amount":2400,"category":"Utilities","type":"Expense"}],"query":null}
{"text":"haircut 150","intent":"log","transactions":[{"amount":150,"category":"Health","type":"Expense"}],"query":null}
{"text":"jollibee 320 and grab 145","intent":"log","transactions":[{"amount":320,"category":"Food","type":"Expense"},{"amount":145,"category":"Transport","type":"Expense"}],"query":null}
{"text":"how much did i spend on food this month","intent":"query","transactions":[],"query":{"metric":"spend","category":"Food","period":null}}
{"text":"what did i earn in 2026-07","intent":"query","transactions":[],"query":{"metric":"income","category":null,"period":"2026-07"}}
{"text":"hello","intent":"unknown","transactions":[],"query":null}
{"text":"thanks!","intent":"unknown","transactions":[],"query":null}
{"text":"spent 1,200 on medicine and 300 for lunch","intent":"log","transactions":[{"amount":1200,"category":"Health","type":"Expense"},{"amount":300,"category":"Food","type":"Expense"}],"query":null}
{"text":"₱250 grab","intent":"log","transactions":[{"amount":250,"category":"Transport","type":"Expense"}],"query":null}
{"text":"2500 salary from freelance client","intent":"log","transactions":[{"amount":2500,"category":"Freelance","type":"Income"}],"query":null}
```

Required coverage and minimum counts:

| Bucket | Min | Notes |
| --- | --- | --- |
| Bare merchant + amount (Tier 0 shapes) | 25 | carwash, load, meralco, grab, jollibee, shopee, maynilad, globe, mercury drug, petron |
| Verb-led single spends | 20 | "spent 200 on groceries", "paid 1500 rent" |
| Multi-item | 15 | 2 and 3 items, both "and" and comma separated |
| Queries | 20 | every metric (spend/income/net/count), with and without category and period |
| Income | 10 | salary vs freelance |
| Non-finance | 10 | greetings, thanks, chit-chat — all `unknown` |
| Adversarial amounts | 10 | `1,200`, `₱250`, `1.2k`, decimals |
| Genuinely ambiguous | 10 | carwash, haircut, `gas`, gcash cash in |

**Two labels need your judgement, not mine — confirm before relying on the numbers:**
- `gas` — the lexicon maps it to **Transport** (fuel), while `lpg` maps to Utilities. Change either if you meant the cooking-gas sense.
- `gcash cash in` — currently unlisted, so it falls to the model and lands on **Other**. Add it to `LEXICON` if you want it pinned.

- [ ] **Step 2: Write the fixture-shape test**

Create `tests/test_eval_fixture.py`:

```python
import json
import pathlib

from app.categories import CATEGORIES

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "router_eval.jsonl"
VALID_INTENTS = {"log", "query", "unknown"}
VALID_METRICS = {"spend", "income", "net", "count"}


def _records():
    with FIXTURE.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_fixture_is_big_enough_to_mean_something():
    assert len(_records()) >= 120


def test_every_record_is_well_formed():
    for rec in _records():
        assert rec["text"].strip(), rec
        assert rec["intent"] in VALID_INTENTS, rec
        for txn in rec["transactions"]:
            assert txn["category"] in CATEGORIES, rec
            assert txn["type"] in {"Income", "Expense"}, rec
            assert float(txn["amount"]) > 0, rec
        if rec["query"] is not None:
            assert rec["query"]["metric"] in VALID_METRICS, rec


def test_log_records_carry_transactions_and_others_do_not():
    for rec in _records():
        if rec["intent"] == "log":
            assert rec["transactions"], rec
        else:
            assert rec["transactions"] == [], rec


def test_query_records_carry_a_query_object():
    for rec in _records():
        assert (rec["query"] is not None) == (rec["intent"] == "query"), rec


def test_the_measured_failures_are_covered():
    texts = {rec["text"] for rec in _records()}
    for required in ("carwash 250", "load 100", "meralco 2400", "haircut 150"):
        assert required in texts
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_eval_fixture.py -q`
Expected: FAIL on `test_fixture_is_big_enough_to_mean_something` until you have 120 records.

- [ ] **Step 4: Register the integration marker**

Replace `pytest.ini` with:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
addopts = -m "not integration"
markers =
    integration: needs a live Ollama server (deselected by default)
```

- [ ] **Step 5: Write the scorer**

Create `scripts/eval_router.py`:

```python
"""Score a model + prompt against the labeled fixture.

Usage:
    python scripts/eval_router.py [--model gemma3:4b] [--tier0-only|--llm-only]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import pathlib
import statistics
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import OLLAMA_BASE_URL  # noqa: E402
from app.fast_path import try_fast_parse  # noqa: E402
from app.llm_parser import route_message  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "router_eval.jsonl"


def load_records() -> list[dict]:
    with FIXTURE.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


async def predict(text: str, mode: str):
    """Return (intent, transactions, query) as plain data, mirroring the bot's order."""
    if mode != "llm-only":
        fast = try_fast_parse(text)
        if fast is not None:
            return "log", [{"amount": fast.amount, "category": fast.category,
                            "type": fast.type}], None
        if mode == "tier0-only":
            return "unknown", [], None
    result = await route_message(text)
    txns = [{"amount": t.amount, "category": t.category, "type": t.type}
            for t in result.transactions]
    query = None if result.query is None else {
        "metric": result.query.metric,
        "category": result.query.category,
        "period": result.query.period,
    }
    return result.intent, txns, query


def peak_vram_gb() -> float:
    try:
        data = httpx.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5.0).json()
    except Exception:
        return 0.0
    return sum(m.get("size_vram", 0) for m in data.get("models", [])) / 1e9


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="label only; set OLLAMA_MODEL to switch")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--tier0-only", action="store_true")
    group.add_argument("--llm-only", action="store_true")
    args = ap.parse_args()
    mode = "tier0-only" if args.tier0_only else "llm-only" if args.llm_only else "full"

    records = load_records()
    totals = collections.Counter()
    confusion: collections.Counter = collections.Counter()
    latencies: list[float] = []
    failures: list[str] = []

    for rec in records:
        started = time.perf_counter()
        try:
            intent, txns, query = await predict(rec["text"], mode)
        except Exception as exc:  # noqa: BLE001
            totals["schema_invalid"] += 1
            failures.append(f"{rec['text']!r}: {type(exc).__name__}: {exc}")
            continue
        latencies.append(time.perf_counter() - started)

        totals["n"] += 1
        totals["intent_ok"] += intent == rec["intent"]
        totals["count_ok"] += len(txns) == len(rec["transactions"])

        for got, want in zip(txns, rec["transactions"]):
            totals["amount_n"] += 1
            totals["amount_ok"] += abs(got["amount"] - float(want["amount"])) < 0.01
            totals["category_n"] += 1
            totals["category_ok"] += got["category"] == want["category"]
            totals["type_n"] += 1
            totals["type_ok"] += got["type"] == want["type"]
            if got["category"] != want["category"]:
                confusion[(want["category"], got["category"])] += 1

        if rec["intent"] == "query":
            totals["query_n"] += 1
            totals["query_ok"] += query is not None and query["metric"] == rec["query"]["metric"]

    def pct(ok: str, n: str) -> str:
        return f"{100 * totals[ok] / totals[n]:.1f}%" if totals[n] else "n/a"

    print(f"\nmode={mode}  model={args.model or 'from OLLAMA_MODEL'}  records={len(records)}")
    print(f"  intent      {pct('intent_ok', 'n')}")
    print(f"  txn count   {pct('count_ok', 'n')}")
    print(f"  amount      {pct('amount_ok', 'amount_n')}")
    print(f"  category    {pct('category_ok', 'category_n')}")
    print(f"  type        {pct('type_ok', 'type_n')}")
    print(f"  query shape {pct('query_ok', 'query_n')}")
    print(f"  schema-invalid responses: {totals['schema_invalid']}")
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[int(len(ordered) * 0.95) - 1] if len(ordered) > 1 else ordered[0]
        print(f"  latency p50={statistics.median(latencies):.2f}s p95={p95:.2f}s")
    print(f"  peak VRAM   {peak_vram_gb():.2f} GB")

    if confusion:
        print("\n  category confusion (expected -> got):")
        for (want, got), count in confusion.most_common(15):
            print(f"    {want:14} -> {got:14} {count}")
    for line in failures[:10]:
        print(f"  FAIL {line}")

    gate_ok = (
        totals["n"]
        and totals["category_ok"] / max(totals["category_n"], 1) >= 0.95
        and totals["intent_ok"] / totals["n"] >= 0.98
        and totals["schema_invalid"] == 0
    )
    print(f"\ngate: {'PASS' if gate_ok else 'FAIL'} "
          "(category >= 95%, intent >= 98%, zero schema-invalid)")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 6: Run the fixture tests, then the scorer**

Run: `python -m pytest tests/test_eval_fixture.py -q`
Expected: PASS once the fixture has 120+ well-formed records.

Run: `python scripts/eval_router.py`
Expected: a report ending in `gate: PASS`. If it fails, fix `LEXICON` or `CATEGORY_GUIDE` — not the fixture labels, unless a label is genuinely wrong.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/router_eval.jsonl scripts/eval_router.py tests/test_eval_fixture.py pytest.ini
git commit -m "test: add labeled eval fixture and router scorer"
```

---

### Task 6: Model benchmark

Answers the question the spec set out to answer: is a smaller model better, or is `gemma3:4b` fine once prompted properly?

**Files:**
- Create: `scripts/benchmark_models.py`

**Interfaces:**
- Consumes: `scripts/eval_router.py` as a subprocess.
- Produces: a comparison table on stdout.

- [ ] **Step 1: Write the benchmark**

Create `scripts/benchmark_models.py`:

```python
"""Compare candidate models on the eval fixture.

Pull the candidates first:
    ollama pull qwen2.5:3b-instruct
    ollama pull llama3.2:3b

Usage:
    python scripts/benchmark_models.py
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "scripts" / "eval_router.py"

CANDIDATES = ["gemma3:4b", "qwen2.5:3b-instruct", "llama3.2:3b"]
FIELDS = ("intent", "category", "amount", "query shape", "peak VRAM", "latency")


def run_one(model: str) -> dict[str, str]:
    env = dict(os.environ, OLLAMA_MODEL=model)
    proc = subprocess.run(
        [sys.executable, str(EVAL), "--model", model],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    out = proc.stdout
    row: dict[str, str] = {"gate": "PASS" if "gate: PASS" in out else "FAIL"}
    for field in FIELDS:
        match = re.search(rf"{re.escape(field)}\s+(.+)", out)
        row[field] = match.group(1).strip() if match else "-"
    return row


def main() -> None:
    rows = {}
    for model in CANDIDATES:
        print(f"--- benchmarking {model} ---", flush=True)
        rows[model] = run_one(model)

    width = max(len(m) for m in rows) + 2
    header = "model".ljust(width) + "".join(f.ljust(16) for f in FIELDS) + "gate"
    print("\n" + header)
    print("-" * len(header))
    for model, row in rows.items():
        print(model.ljust(width) + "".join(row[f].ljust(16) for f in FIELDS) + row["gate"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Pull the candidates**

```bash
ollama pull qwen2.5:3b-instruct
ollama pull llama3.2:3b
```

Roughly 4 GB of downloads, one time.

- [ ] **Step 3: Run the benchmark**

Run: `python scripts/benchmark_models.py`
Expected: a table with one row per model. `gemma3:4b` is expected to win or tie — it fits VRAM, is correct once constrained, and doubles as the vision model. Keep it unless a candidate beats it on category accuracy *and* fits in VRAM.

- [ ] **Step 4: Record the result**

Append the table to `docs/superpowers/specs/2026-08-04-llm-classification-hardening-design.md` under a new `## Benchmark result` heading, with a one-line verdict naming the chosen model.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_models.py docs/superpowers/specs/2026-08-04-llm-classification-hardening-design.md
git commit -m "test: add model benchmark and record the result"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| `app/categories.py` single source of truth | 1 |
| Five duplicate category lists collapsed to one | 1 |
| Taxonomy consistency invariant enforced by test | 1 |
| Tier 0 fast path, fails closed | 2 |
| Lexicon never overrides Tier 1 | 2 (only Tier 0 calls it) |
| Migrate to `/api/chat` | 3 |
| Schema generated from `RouterResult`, not hand-written | 3 |
| `keep_alive`, `num_ctx`, greedy decoding | 3 |
| Vision model defaults to text model; unload only when different | 3 |
| Legacy `parse_transaction` / `USE_INTENT_ROUTER` deleted | 3, 4 |
| Parse failure distinguished from genuine `unknown` | 4 |
| Eval fixture, ~120 labeled cases, listed coverage | 5 |
| Confusion matrix, latency, VRAM, tier isolation flags | 5 |
| Acceptance gate (category ≥95%, intent ≥98%, zero invalid) | 5 |
| `integration` marker excluded by default | 5 |
| Model benchmark across candidates | 6 |

**Resolved since the spec was written.** The spec listed an open risk: whether Ollama 0.32's grammar converter handles Pydantic's `$defs`/`$ref`. Tested directly against `gemma3:4b` — **it does**, and the generated schema also fixed the multi-item collapse that a hand-written schema caused. The spike task the spec called for is therefore not in this plan, and no `$defs`-inlining helper is needed.

**Found while validating the prompt.** With the schema attached but no `unknown` example, `hello` came back as `intent="query"`. Rule 3 and the `hello` example in `render_router_prompt()` fix it; the final prompt scored 11/11 on intent and query shape. The fixture's non-finance bucket guards against regression.

**Flash-attention and KV-cache toggles** are deliberately absent from Task 6. The GTX 1660 SUPER is Turing with no tensor cores, `gemma3:4b` already fits VRAM at 2.68 GB, and the spec called for measuring rather than assuming. Add them to `CANDIDATES` as env-var variants only if the benchmark shows VRAM pressure.

**Two fixture labels need your ruling** before the gate numbers mean anything: `gas` (Transport as fuel, vs Utilities as cooking gas) and `gcash cash in` (currently unpinned, lands on Other). Both are called out in Task 5, Step 1.
