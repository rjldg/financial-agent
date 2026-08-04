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
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "scripts" / "eval_router.py"

sys.path.insert(0, str(ROOT))
from app.config import OLLAMA_BASE_URL  # noqa: E402

import httpx  # noqa: E402

CANDIDATES = ["gemma3:4b", "qwen2.5:3b-instruct", "llama3.2:3b"]
FIELDS = ("intent", "category", "amount", "query shape", "peak VRAM", "latency")


def unload_model(model: str) -> None:
    """Free VRAM before the next model loads.

    The 1660 Super only has ~4.6 GB free, not enough to hold two of these
    models at once. Without unloading, the next run either falls back to CPU
    or thrashes VRAM, and the latency numbers stop meaning anything.
    """
    try:
        httpx.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": model, "messages": [], "keep_alive": 0},
            timeout=30.0,
        )
    except Exception:
        pass

    for _ in range(15):
        time.sleep(1)
        try:
            data = httpx.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5.0).json()
        except Exception:
            return
        if not any(m.get("name") == model for m in data.get("models", [])):
            print(f"  unloaded {model}", flush=True)
            return
    print(f"  warning: {model} still resident after unload attempt", file=sys.stderr)


def run_one(model: str) -> dict[str, str]:
    env = dict(os.environ, OLLAMA_MODEL=model)
    proc = subprocess.run(
        [sys.executable, str(EVAL), "--model", model],
        capture_output=True, text=True, env=env, cwd=ROOT,
    )
    out = proc.stdout
    print(out)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
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
        unload_model(model)

    width = max(len(m) for m in rows) + 2
    header = "model".ljust(width) + "".join(f.ljust(16) for f in FIELDS) + "gate"
    print("\n" + header)
    print("-" * len(header))
    for model, row in rows.items():
        print(model.ljust(width) + "".join(row[f].ljust(16) for f in FIELDS) + row["gate"])


if __name__ == "__main__":
    main()
