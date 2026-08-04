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
