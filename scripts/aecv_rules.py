"""Re-score saved hybrid votes (scripts/aecv_hybrid.py) under different detector+Nemotron combination rules. Free.

    python scripts/aecv_rules.py <votes.jsonl> [--grid] [--rule td,tw,mode]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.vlm.openings import merge_adjacent  # noqa: E402

DROP = {"garage_door", "sliding_closet_door"}
WINDOWISH = {"casement_window", "window", "french_door", "sliding_glass_door"}


def count(r, td=0.35, tw=0.3, ext_door_to_win=True, double=True, merge_gap=6, veto=0.0, wincand=False):
    """detector decides IF there is an opening (its class + threshold); Nemotron decides WHAT it counts as."""
    d, wins = 0, []
    for v in r["votes"]:
        c, s, t, wall = v["cls"], v["conf"], v["type"], v.get("wall", "unsure")
        if t in DROP:
            continue
        if c == "door" and s >= td:
            if t in WINDOWISH and (ext_door_to_win or wall == "exterior"):
                wins.append(v["bbox"])
                continue
            if t in ("opening_no_door", "not_an_opening") and s < veto:
                continue
            d += 2 if (double and t == "double_swing_door") else 1
        elif c == "window" and s >= tw:
            if t in ("opening_no_door", "not_an_opening") and s < veto:
                continue
            if t in ("swing_door", "double_swing_door") and wall == "interior" and s < 0.5:
                d += 2 if (double and t == "double_swing_door") else 1
                continue
            wins.append(v["bbox"])
        elif wincand and c == "window" and s >= 0.15 and t in ("window", "casement_window"):
            wins.append(v["bbox"])
    nw = len(wins) if merge_gap is None else len(merge_adjacent(wins, merge_gap))
    return d, nw


def acc(rows, **kw):
    od = ow = 0
    for r in rows:
        d, w = count(r, **kw)
        od += d == r["gold"]["Door"]
        ow += w == r["gold"]["Window"]
    return od / len(rows), ow / len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("votes")
    ap.add_argument("--grid", action="store_true")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.votes, encoding="utf-8")]
    print("detector only:", acc(rows, ext_door_to_win=False, double=False) if False else None)
    base = [0, 0]
    for r in rows:
        dd = sum(1 for v in r["votes"] if v["cls"] == "door" and v["conf"] >= 0.35)
        ww = sum(1 for v in r["votes"] if v["cls"] == "window" and v["conf"] >= 0.45)
        base[0] += dd == r["gold"]["Door"]
        base[1] += ww == r["gold"]["Window"]
    print(f"detector only (0.35/0.45): door {base[0] / len(rows):.2f} window {base[1] / len(rows):.2f}")
    if a.grid:
        res = []
        for td, tw, e2w, dbl, mg, veto, wc in itertools.product(
                [.3, .35, .4, .45, .5], [.2, .25, .3, .35, .4, .45], [0, 1], [0, 1], [None, 0, 6], [0, .5, .7], [0, 1]):
            d, w = acc(rows, td=td, tw=tw, ext_door_to_win=bool(e2w), double=bool(dbl), merge_gap=mg, veto=veto,
                       wincand=bool(wc))
            res.append((d, w, dict(td=td, tw=tw, e2w=e2w, dbl=dbl, mg=mg, veto=veto, wc=wc)))
        for r in sorted(res, key=lambda r: -r[0])[:5]:
            print("best door", f"{r[0]:.2f}", f"{r[1]:.2f}", r[2])
        for r in sorted(res, key=lambda r: -r[1])[:5]:
            print("best win ", f"{r[0]:.2f}", f"{r[1]:.2f}", r[2])
    by = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        d, w = count(r)
        s = r["plan"][:4]
        by[s][0] += d == r["gold"]["Door"]
        by[s][1] += w == r["gold"]["Window"]
        by[s][2] += 1
    print("default rule by source:", {k: f"d{v[0]}/w{v[1]}/n{v[2]}" for k, v in sorted(by.items())})


if __name__ == "__main__":
    main()
