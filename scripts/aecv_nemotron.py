"""Nemotron 3.5 Super VL baseline on AECV-Bench object counting, with AECV's own prompt (fair leaderboard entry).

    python scripts/aecv_nemotron.py <AECV-Bench repo> [--think] [--max-side 1536]
Writes runs/aecv-nemotron-<tag>-<ts>/results.jsonl in the same shape as scripts/aecv_bench.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from plansight.config import RUNS  # noqa: E402
from plansight.vlm import nemotron  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402

FIELDS = ("Door", "Window", "Space", "Bedroom", "Toilet")
SCHEMA = {"type": "object", "properties": {f: {"type": "integer"} for f in FIELDS}, "required": list(FIELDS)}


def prompt(repo: Path) -> str:
    ns: dict = {}
    exec((repo / "src/analyzers/prompts.py").read_text(encoding="utf-8"), ns)  # AECV's exact rules
    COUNTING_RULES = ns["COUNTING_RULES"]

    return ("You are an expert floor-plan analyst trained to interpret architectural and engineering drawings in any "
            "language.\n\nYour task is to fully understand the drawing first, then count the elements exactly "
            "according to the rules below, and then return ONLY the JSON strictly following the provided schema:\n\n"
            f"{json.dumps(SCHEMA, indent=2)}\n\n\n{COUNTING_RULES}")


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    return {f: int(d[f]) if isinstance(d.get(f), (int, float)) else None for f in FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--max-side", type=int, default=1536)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    repo = Path(a.repo)
    p = prompt(repo)
    plans = aecv_plans(repo)

    def one(pl):
        name, img, gold = pl
        r = nemotron.ask(p, [nemotron.encode_image(img, max_side=a.max_side)], think=a.think,
                         max_tokens=8192 if a.think else 256, json_schema=None if a.think else SCHEMA)
        return {"plan": name, "gold": gold, "pred": parse(r.text), "cost_usd": r.cost_usd,
                "tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "latency_ms": r.latency_ms}

    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(one, plans))
    tag = f"{'think' if a.think else 'v0'}-{a.max_side}"
    out = RUNS / f"aecv-nemotron-{tag}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    acc = {k: sum(r["pred"][k] == r["gold"].get(k) for r in rows) / len(rows) for k in FIELDS}
    cost = sum(r["cost_usd"] for r in rows)
    s = (f"Nemotron 3.5 Super VL ({tag}), {len(rows)} plans, {time.time() - t0:.0f}s, ${cost:.4f} total: "
         + "  ".join(f"{k} {100 * v:.0f}%" for k, v in acc.items()))
    (out / "summary.txt").write_text(s + "\n", encoding="utf-8")
    print(s)


if __name__ == "__main__":
    main()
