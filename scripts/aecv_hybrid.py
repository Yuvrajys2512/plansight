"""AECV-Bench doors/windows: cached detector candidates -> Nemotron classifies each crop -> AECV counting rules.

    python scripts/aecv_hybrid.py <AECV-Bench repo> [--split A|B|all] [--cand 0.15] [--det plain]
Saves every vote (runs/aecv-hybrid-*/votes.jsonl) so counting rules can be re-scored offline for free.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from PIL import Image  # noqa: E402

from plansight.config import RUNS  # noqa: E402
from plansight.vlm.openings import RULES, classify_all, merge_adjacent, nms_any  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402
from scripts.aecv_tune import load, split_of  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def score(votes):
    doors = sum(RULES[v["type"]][0] for v in votes)
    wins = merge_adjacent([v["bbox"] for v in votes if RULES[v["type"]][1]])
    return doors, len(wins)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--split", default="A")
    ap.add_argument("--cand", type=float, default=0.15)
    ap.add_argument("--det", default="plain")
    ap.add_argument("--plans", type=int, default=0, help="first N plans only (smoke test)")
    a = ap.parse_args()
    det = load(f"aecv-cubicasa_objects-{a.det}.jsonl")
    plans = [p for p in split_of(aecv_plans(Path(a.repo)), a.split) if p[0] in det]
    if a.plans:
        plans = plans[:a.plans]
    out = RUNS / f"aecv-hybrid-{a.det}-{a.split}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def one(p):
        name, img, gold = p
        cands = nms_any([(c, s, tuple(b)) for c, s, *b in det[name]["dets"]
                         if c in ("door", "window", "opening") and s >= a.cand])
        votes = classify_all(Image.open(img), cands)
        vs = [{"bbox": v.bbox, "cls": v.det_cls, "conf": v.det_conf, "type": v.type, "wall": v.wall, "cost": v.cost_usd}
              for v in votes]
        return {"plan": name, "gold": gold, "votes": vs}

    with ThreadPoolExecutor(2) as ex, (out / "votes.jsonl").open("w", encoding="utf-8") as f:
        rows = []
        for r in ex.map(one, plans):
            f.write(json.dumps(r) + "\n")
            f.flush()
            rows.append(r)
    ok_d = ok_w = 0
    for r in rows:
        d, w = score(r["votes"])
        ok_d += d == r["gold"]["Door"]
        ok_w += w == r["gold"]["Window"]
    n = len(rows)
    cost = sum(v["cost"] for r in rows for v in r["votes"])
    calls = sum(len(r["votes"]) for r in rows)
    s = (f"hybrid ({a.det}, cand>={a.cand}) split {a.split}, {n} plans, {calls} crops, {time.time() - t0:.0f}s, "
         f"${cost:.4f}: Door {100 * ok_d / n:.0f}%  Window {100 * ok_w / n:.0f}%")
    (out / "summary.txt").write_text(s + "\n", encoding="utf-8")
    print(s)


if __name__ == "__main__":
    main()
