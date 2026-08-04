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
        except Exception as exc:
            # Staying quiet here made a flaky poll look identical to a real unload,
            # so say something even though this path is unlikely to trigger.
            print(f"  warning: could not confirm {model} unloaded ({exc}); treat as unverified", file=sys.stderr)
            return
        if not any(m.get("name") == model for m in data.get("models", [])):
            print(f"  unloaded {model}", flush=True)
            return
    print(f"  warning: {model} still resident after unload attempt", file=sys.stderr)


def resident_models() -> list[str]:
    """Names of models Ollama currently has loaded, per /api/ps."""
    try:
        data = httpx.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5.0).json()
    except Exception as exc:
        print(f"  warning: could not query /api/ps to check GPU state ({exc})", file=sys.stderr)
        return []
    return [m.get("name", "?") for m in data.get("models", [])]


def ensure_clean_gpu(model: str) -> str | None:
    """Refuse to trust a measurement taken next to another resident model.

    This is the exact bug that corrupted a real run: two benchmark processes
    ran at once, each unloaded only the model IT had just finished with, and
    the survivor's VRAM/latency readings silently absorbed whatever the other
    process still had loaded (one row read 4.96 GB for a model that is
    actually 2.08 GB). The table gave no hint anything was wrong. /api/ps is
    the only way to catch that before it poisons this model's row.

    Returns None if the GPU is clean, otherwise a short message describing
    what is still resident (for the caller to mark that row as contaminated).
    """
    stray = [m for m in resident_models() if m != model]
    if not stray:
        return None

    print(
        f"  WARNING: unexpected model(s) resident before {model}: {', '.join(stray)} "
        "- attempting to clear before measuring",
        file=sys.stderr,
    )
    for name in stray:
        unload_model(name)

    stray = [m for m in resident_models() if m != model]
    if not stray:
        return None

    msg = f"GPU dirty before {model}: {', '.join(stray)} still resident"
    print(f"  {'!' * 10} {msg} - VRAM/latency for this row are UNRELIABLE {'!' * 10}", file=sys.stderr)
    return msg


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
    contamination: dict[str, str] = {}
    for model in CANDIDATES:
        print(f"--- benchmarking {model} ---", flush=True)
        warning = ensure_clean_gpu(model)
        if warning:
            contamination[model] = warning
        rows[model] = run_one(model)
        unload_model(model)

    width = max(len(m) for m in rows) + 3  # +1 over the old +2 to fit the "*" contamination marker
    header = "model".ljust(width) + "".join(f.ljust(16) for f in FIELDS) + "gate"
    print("\n" + header)
    print("-" * len(header))
    for model, row in rows.items():
        label = model + ("*" if model in contamination else "")
        print(label.ljust(width) + "".join(row[f].ljust(16) for f in FIELDS) + row["gate"])
    if contamination:
        print("\n* VRAM and latency are UNRELIABLE for this row - the GPU was not clean beforehand:")
        for model, warning in contamination.items():
            print(f"    {model}: {warning}")


if __name__ == "__main__":
    main()
