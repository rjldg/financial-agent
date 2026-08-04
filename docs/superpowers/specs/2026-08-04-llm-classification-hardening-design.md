# LLM Classification Hardening & VRAM Efficiency

**Date:** 2026-08-04
**Status:** Approved design, pending implementation plan

## Problem

Transaction categorization is unreliable and the bot silently drops messages. On a
GTX 1660 SUPER (6 GB, ~4.6 GB free after the Windows desktop), `gemma3:4b` also
raised concerns about memory pressure.

### Measured baseline

Run against the current `_ROUTER_PROMPT` on `gemma3:4b`, 2026-08-04:

| Input | Output | Failure |
| --- | --- | --- |
| `carwash 250` | `category: "Shopping"` | wrong category |
| `load 100` | `intent: "unknown"` | not recognized as a log |
| `haircut 150` | `{"intent":"shopping","category":"Other"}` | invalid schema |
| `meralco 2400` | `intent: "unknown"` | not recognized as a log |
| `gcash cash in 500` | `Other` / Income | weak but arguable |

Four of five failed. Three distinct causes:

1. **No decode-time constraint.** The request never sets `format`/`response_format`,
   so the category enum is a plaintext suggestion. `haircut 150` produced a
   structurally invalid object; Pydantic rejected it and `route_message`
   (`app/llm_parser.py:164`) returned `unknown`.
2. **No category definitions.** The prompt lists twelve bare names with no meaning
   attached, so the model guesses at "carwash".
3. **No rule for bare `<noun> <amount>` messages.** The prompt only describes
   verb-led phrasing, so `load 100` and `meralco 2400` fall through to `unknown`.

### Measured fix

Same model, same hardware, adding only a JSON-schema constraint, category
definitions and few-shot examples:

| Input | Before | After |
| --- | --- | --- |
| `carwash 250` | Shopping | **Transport** |
| `load 100` | unknown | **Bills** / "Phone load" |
| `meralco 2400` | unknown | **Utilities** |
| `haircut 150` | invalid JSON | **Health** |
| `how much did i spend on food this month` | — | **query** |

`gemma3:4b` is not the bottleneck. It loads fully onto the GPU (2.87 GB at
`num_ctx` 4096, 2.68 GB at 2048), answers in ~3.5 s, and is correct once
constrained. The prompt was the defect.

Two capabilities remain fragile under the new prompt and must be covered by the
eval set: **multi-item messages** (`jollibee 320 and grab 145` returned one
transaction, not two) and **queries** (an incomplete hand-written schema omitted
the `query` object entirely).

## Constraints

Fixed by decision during design:

- The twelve categories are **fixed**. Historical monthly tabs, the dashboard and
  the sheet's data-validation dropdown depend on these exact strings.
- Receipt OCR is **kept**, used occasionally; a few seconds of model swap is
  acceptable.
- Known merchants are resolved by a **deterministic lexicon**, with the LLM as
  fallback.
- Tuning covers Ollama parameters, prompt/schema work and a benchmarked model
  swap. **LoRA fine-tuning is out of scope.**

## Architecture

Two tiers. The lexicon alone cannot replace the LLM — it supplies only the
*category*, while amount, intent and multi-item splitting still need parsing. For
one common message shape a regex supplies the rest, and that shape is exactly
where today's failures cluster.

```
message
  |
  +- Tier 0: one number + a known lexicon term,
  |          no question word, no conjunction
  |          -> Transaction built directly. 0 ms, 0 VRAM, deterministic.
  |          covers: "carwash 250", "load 100", "meralco 2400", "grab 145"
  |
  +- Tier 1: everything else
             -> one POST /api/chat
                format  = JSON schema generated from RouterResult
                system  = rules + category guide + few-shot
             -> RouterResult, Pydantic-validated
                  |
                  +- app/bot/handlers/transactions.py (unchanged)
```

Tier 0 is deliberately narrow. Any conjunction (`and`, `+`, `,`), any question
word, or more than one number falls through to Tier 1, so multi-item messages and
queries never take the fast path.

**The lexicon does not override Tier 1 output.** It is consulted in Tier 0 only.
Tier 1 is steered by the category guide instead. Both are rendered from the same
table, so they agree by construction, and there is no override rule to surprise
the user on a message like "bought a carwash gift card at Shopee".

## Components

### `app/categories.py` (new) — single source of truth

`CATEGORIES`, `FORMULA_CATEGORIES` and three prompt strings currently hold five
hand-maintained copies of the category list. This module replaces them.

```python
CATEGORY_GUIDE: dict[str, str] = {
    "Food":      "meals, groceries, coffee, restaurants, food delivery",
    "Transport": "fare, Grab, taxi, jeep, gas, fuel, parking, toll, "
                 "carwash, car maintenance, LTO registration",
    "Utilities": "electricity (Meralco), water (Maynilad), gas utility",
    # ... all twelve
}

LEXICON: dict[str, str] = {"carwash": "Transport", "meralco": "Utilities", ...}
```

- `CATEGORIES = list(CATEGORY_GUIDE)`. `app/models.py` and
  `app/sheets/transactions.py` import it.
- `Category = Literal[...]` stays hand-written in `models.py`, because a `Literal`
  must be static to type-check. A test asserts
  `set(CATEGORIES) == set(get_args(Category)) == set(CATEGORY_GUIDE)` and that
  every `LEXICON` value is a valid category. The type system cannot enforce this
  invariant, so a test does.
- `render_category_guide()` builds the prompt block from the same table.
- `classify_by_lexicon(text) -> str | None` does whole-word matching, longest term
  first, and returns `None` when two terms from different categories match.

Correcting a miscategorization is then one line in `LEXICON` (deterministic and
permanent) or one clause in `CATEGORY_GUIDE` (steers the model) — never a prompt
rewrite.

### `app/llm_parser.py` — transport migration and schema constraint

**Move from `/v1/chat/completions` to `/api/chat`.** This is required, not
cosmetic: `keep_alive`, `num_ctx` and `top_k` do not exist on the
OpenAI-compatible endpoint, and the VRAM strategy below depends on all three.
Verified working on Ollama 0.32.0.

The change is contained. `_chat()` is the only caller; the response shape moves
from `choices[0].message.content` to `message.content`; receipt images move from
data URIs to `images: [<base64>]`, which removes `build_image_data_uri`.

`_chat()` gains a `schema` parameter and sends:

```json
{
  "model": "...", "stream": false, "keep_alive": "30m",
  "format": { /* generated from RouterResult */ },
  "options": {"temperature": 0, "top_k": 1, "num_ctx": 2048, "num_predict": 256}
}
```

Greedy decoding (`temperature 0`, `top_k 1`) makes evaluation runs reproducible.

**The schema is generated from `RouterResult.model_json_schema()`, never
hand-written** — a hand-written schema is what omitted the `query` object during
design testing.

*Open risk:* Pydantic emits `$defs`/`$ref` for nested models and `anyOf` for
`Optional[QuerySpec]`. Whether Ollama 0.32's grammar converter handles `$ref` is
**unverified**. The implementation plan opens with a spike on this; if it fails,
a small helper inlines `$defs` before sending. A test asserts the generated
schema's category enum equals `CATEGORIES`.

`render_router_prompt()` composes the system prompt from the taxonomy table plus
fixed rules:

1. A message naming a thing and a number is always `log` and an Expense, even
   with no verb.
2. Use `query` only when the message asks something.
3. `unknown` is a last resort; a number almost always means a log.

Few-shot examples **must** include a multi-item case and a query case. Both were
observed to be fragile.

### Prompt/VRAM configuration

- `OLLAMA_VISION_MODEL` is a new env var defaulting to `OLLAMA_MODEL`. When the
  two are equal — the expected outcome if the benchmark keeps `gemma3:4b` — one
  model serves both text and vision and **there is no swap cost for receipts at
  all**.
- Text calls: `keep_alive: "30m"`, `num_ctx: 2048`. Measured at 2.68 GB, leaving
  roughly 2 GB of headroom against the 4.6 GB free.
- Receipt calls use `keep_alive: 0` **only when the vision model differs** from
  the text model, so it unloads immediately after use.
- `OLLAMA_FLASH_ATTENTION` and `OLLAMA_KV_CACHE_TYPE=q8_0` are **benchmark
  toggles, not defaults**. The GTX 1660 SUPER is Turing and has no tensor cores,
  so their benefit must be measured rather than assumed.

Tier 0 supplies the largest efficiency gain: the most frequent messages stop
invoking the model at all.

### Legacy path removal

`parse_transaction`, `_SYSTEM_PROMPT` and the `USE_INTENT_ROUTER` flag are
deleted, along with `_handle_log_direct` in
`app/bot/handlers/transactions.py`. No test covers them, and the hardened router
handles single transactions strictly better, so the fallback protects nothing
while keeping a duplicate category list and prompt alive. `.env.example`, the
README env table and `app/config.py` drop the flag.

## Evaluation

### `tests/fixtures/router_eval.jsonl`

Roughly 120 labeled cases, drafted during implementation and **reviewed by the
user**, who is ground truth for what "gas" or "gcash cash in" means in their
books. Each record carries `text`, expected `intent`, and for logs a list of
`{amount, category, type}`.

Coverage, weighted toward observed failures:

- Bare noun + number (Tier 0 shapes): `carwash 250`, `load 100`, `meralco 2400`
- PH merchants: jollibee, grab, shopee, lazada, maynilad, globe, smart, mercury
  drug, 7-eleven, palawan, gcash
- Multi-item, two and three items
- Queries, with and without category and period
- Income: salary versus freelance
- Genuinely ambiguous: carwash, haircut, `gas` (fuel or utility), gcash cash in
- Non-finance: "hello", "thanks" — must stay `unknown`
- Adversarial amounts: `1,200`, `₱250`, `1.2k`, decimals

Scoring covers intent, transaction count, exact amount, category and type.
Description is free-form, so it is checked non-empty rather than matched —
string-matching it would penalize correct answers.

### `scripts/eval_router.py`

Runs the fixture against a given model and configuration. Reports per-field
accuracy, a **category confusion matrix** (showing what is mistaken for what, not
just an aggregate), p50/p95 latency and peak VRAM from `/api/ps`. Flags
`--tier0-only` and `--llm-only` isolate the lexicon's contribution.

### `scripts/benchmark_models.py`

Sweeps `gemma3:4b` (baseline), `qwen2.5:3b-instruct`, `llama3.2:3b` and
`qwen3:4b`, plus the flash-attention and KV-cache-quantization toggles, into one
comparison table. Requires roughly 5 GB of one-time model pulls.

Expected outcome: `gemma3:4b` is retained. It fits VRAM, is correct once
constrained, and doubles as the vision model. The benchmark exists to verify that
rather than assume it.

### Acceptance gate

- Category accuracy >= 95%
- Intent accuracy >= 98%
- Zero schema-invalid outputs
- All four measured baseline failures pass (`carwash`, `load`, `meralco`,
  `haircut`), plus multi-item and query cases

## Error handling

- **Parse failure and genuine `unknown` are distinguished.** `route_message`
  currently returns `RouterResult(intent="unknown")` for both
  (`app/llm_parser.py:164-166`), which is why the `haircut 150` schema violation
  surfaced to the user as "I couldn't understand that". A malformed response now
  raises a distinct error and produces a different user-facing message.
- **Tier 0 fails closed.** Any ambiguity — multiple numbers, a conjunction, a
  question word, two lexicon terms from different categories — falls through to
  Tier 1 rather than guessing. A wrong amount is worse than a slow answer.
- The existing three-attempt exponential backoff on connection and 5xx errors is
  unchanged.

## Testing

Fast, offline unit tests (no Ollama required):

- Lexicon resolution, including the ambiguous-match `None` case
- Tier 0 regex accept and reject cases, especially reject
- Schema generation from `RouterResult`
- Prompt rendering from the taxonomy table
- The taxonomy consistency invariant across `CATEGORIES`, `Category`,
  `CATEGORY_GUIDE` and `LEXICON`

Eval and benchmark runs need a live Ollama, so they are marked
`@pytest.mark.integration` and excluded from the default run. `pytest.ini` gains
a `markers` entry and `addopts = -m "not integration"`.

## Prerequisite

The repository's Python environment is currently broken: `sys.prefix` resolves to
the repo root, so `import encodings` fails and neither the app nor the test suite
runs. This must be repaired before implementation, since every acceptance check
depends on it.

## Out of scope

- Changing, adding or renaming categories
- LoRA or any weight-level fine-tuning
- Learning the lexicon automatically from quick-fix corrections
- Dashboard, budgets, subscriptions and scheduler behaviour

## Benchmark result

Measured 2026-08-04 against the 135-record fixture, Ollama 0.32, GTX 1660 SUPER.
VRAM figures below were re-measured with each model loaded alone; the figures
produced during the benchmark run itself were contaminated by a concurrent run
and are not reported here.

| Model | intent | category | amount | type | query shape | VRAM | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **gemma3:4b** | **100%** | **99.2%** | **99.2%** | **98.4%** | 86.4% | 2.87 GB | **PASS** |
| qwen2.5:3b-instruct | 95.6% | 91.3% | 98.4% | 96.9% | 86.4% | 2.08 GB | FAIL |
| llama3.2:3b | 97.0% | 87.5% | 91.9% | 91.2% | 68.2% | 2.32 GB | FAIL |

**Verdict: keep `gemma3:4b`.** It is the only candidate that clears the gate, and
it wins on every accuracy dimension. The smaller models are 2-4x faster and lighter
but trade away exactly the accuracy this work existed to fix. `gemma3:4b` is the
largest of the three in VRAM, so it wins on merit rather than on footprint; that it
also reads receipt images, meaning one model serves both paths with no swap, is a
bonus rather than the deciding factor.

Latency for the chosen model, measured in a clean solo run: p50 3.08s, p95 3.85s.

Note on reproducibility: greedy decoding makes runs identical while a model stays
resident, but scores drifted about one point across an unload/reload cycle. Treat
+/-1% as run-to-run noise, which leaves the 95% category gate with real headroom
rather than sitting on a knife edge.

## Outcome against the original problem

The four measured baseline failures all pass, and the malformed-JSON class of
failure is gone entirely (zero schema-invalid responses across 135 records).
`gemma3:4b` was never the bottleneck - the prompt was. 31% of fixture messages
are now settled by the lexicon fast path with no inference at all.
