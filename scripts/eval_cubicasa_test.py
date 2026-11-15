"""Per-question accuracy on Stoa's CubiCasa5K questions, held-out drawings only (CubiCasa test split; our detectors
never saw them). Same scoring as plansight.eval (counts exact). Runs the live configuration (no LLM by default).

    python scripts/eval_cubicasa_test.py [--n 1000] [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PLANSIGHT_NO_LLM", "1")
from plansight.config import RUNS  # noqa: E402
from plansight.eval.data import load_questions  # noqa: E402
from plansight.eval.runner import _run_row  # noqa: E402

KINDS = ["door", "window", "toilet", "sink", "shower", "bath", "bedroom", "kitchen", "sauna", "balcon", "wc", "floor",
         "storey", "room"]


def kind_of(q: str) -> str:
    ql = q.lower()
    return next((k for k in KINDS if re.search(rf"\b{k}", ql)), "other")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    test = set()
    for line in (root / "plansight/detect/splits/test.txt").read_text().split():
        sub, num = line.strip("/").split("/")
        test.add(f"data/cubicasa5k/{sub}-{num}.png")
    rows = [r for r in load_questions() if r["source"] == "cubicasa5k" and r["path"] in test]
    random.Random(a.seed).shuffle(rows)
    rows = sorted(rows[:a.n], key=lambda r: r["path"])  # group by drawing so detector passes are cached
    out = RUNS / "cubicasa-test-eval.jsonl"
    by, by_lang, n_ok = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), 0
    with out.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            res = _run_row(r, "auto", [])
            k = kind_of(r["question"]) if r["lang"] == "en" else "non-en"
            by[k][0] += res["correct"]; by[k][1] += 1
            by_lang[r["lang"]][0] += res["correct"]; by_lang[r["lang"]][1] += 1
            n_ok += res["correct"]
            f.write(json.dumps({**res, "kind": k}, ensure_ascii=False, default=str) + "\n")
            if (i + 1) % 100 == 0:
                print(i + 1, len(rows), f"{100 * n_ok / (i + 1):.1f}%", flush=True)
    print(f"ALL {n_ok}/{len(rows)} = {100 * n_ok / len(rows):.1f}%  ({len({r['path'] for r in rows})} drawings)")
    for k, (o, n) in sorted(by.items(), key=lambda x: -x[1][1]):
        print(f"  {k:8s} {o:4d}/{n:4d} {100 * o / n:5.1f}%")
    print("by language:", {k: f"{100 * o / n:.0f}% (n={n})" for k, (o, n) in by_lang.items()})


if __name__ == "__main__":
    main()
