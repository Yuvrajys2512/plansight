"""AECV-Bench door/window/toilet/bedroom eval over a cached detector run, with the AECV gold rules as a config.

    python scripts/aecv_eval.py --det aecv-cubicasa_objects-plain.jsonl [--cfg '{"td":0.35}'] [--grid] [--split B]

Prints exact-match accuracy on split A, split B, all, and "clean" (plans that are in our detector's CubiCasa
train split removed, see runs/aecv_leakage.json). --grid searches on split A ONLY and prints the best configs.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402
from plansight.vlm.openings import merge_adjacent  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402
from scripts.aecv_report import plansight  # noqa: E402
from scripts.aecv_tune import load  # noqa: E402

REPO = Path(os.environ.get("AECV_REPO", "aecv-repo"))  # local clone of the AECV-Bench repo
BASE = dict(td=0.35, tw=0.30, gap=6, xiou=0.0, dbl=0.0, tw_low=None, style_conf=0.0, onwall=None, wsup=0.2,
            wcand=None)


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def doors_windows(rec, cfg, walls=None):
    """AECV rules on detector boxes. Returns (door boxes [(bbox, n)], window boxes)."""
    c = {**BASE, **cfg}
    dets = rec.get("dets", []) if rec else []
    # style: plans our detector is unsure about (unseen drawing style) get a lower window threshold
    top = sorted((x[1] for x in dets if x[0] in ("door", "window")), reverse=True)[:10]
    style = sum(top) / len(top) if top else 1.0
    tw = c["tw_low"] if (c["tw_low"] is not None and style < c["style_conf"]) else c["tw"]
    doors = [(x[1], tuple(x[2:])) for x in dets if x[0] == "door" and x[1] >= c["td"]]
    wins = [(x[1], tuple(x[2:])) for x in dets if x[0] == "window" and x[1] >= tw]
    if walls is not None:
        sup = lambda b: walls.get(",".join(map(str, b)), 0.0)  # noqa: E731
        if c["onwall"] is not None:  # verifier: unsure windows must sit in a wall
            wins = [w for w in wins if w[0] >= c["onwall"] or sup(w[1]) >= c["wsup"]]
        if c["wcand"] is not None:  # admit low-confidence windows that clearly sit in a wall
            wins += [(x[1], tuple(x[2:])) for x in dets if x[0] == "window" and c["wcand"] <= x[1] < tw
                     and sup(x[2:]) >= max(c["wsup"], 0.5)]
    if c["xiou"]:  # one physical opening found as both door and window: keep the more confident label
        keep_d, keep_w = [], list(wins)
        for s, b in doors:
            hit = [w for w in keep_w if _iou(b, w[1]) > c["xiou"]]
            if hit and max(h[0] for h in hit) > s:
                continue
            keep_w = [w for w in keep_w if w not in hit]
            keep_d.append((s, b))
        doors, wins = keep_d, keep_w
    # double-leaf = 2: opening much wider than this plan's typical door (boxes are thin wall-threshold boxes)
    lens = sorted(max(b[2] - b[0], b[3] - b[1]) for _, b in doors)
    med = lens[len(lens) // 2] if lens else 0
    out_d = []
    for s, b in doors:
        L = max(b[2] - b[0], b[3] - b[1])
        out_d.append((b, 2 if (c["dbl"] and len(lens) >= 3 and L >= c["dbl"] * med) else 1))
    wb = [b for _, b in wins]
    if c["gap"] is not None:
        wb = merge_adjacent(wb, c["gap"])
    return out_d, wb


class Bench:
    def __init__(self, det_name, door_det=None):
        self.door_det = load(door_det) if door_det else None
        wf = RUNS / "detcache" / f"{det_name}.walls.json"
        self.walls = json.loads(wf.read_text()) if wf.exists() else {}
        self.plans = aecv_plans(REPO)
        self.split = {p[0]: "AB"[i % 2] for i, p in enumerate(self.plans)}
        self.gold = {p[0]: p[2] for p in self.plans}
        self.det = load(det_name)
        self.ocr, self.rooms = load("aecv-ocr.jsonl"), load("aecv-cubicasa_rooms-plain.jsonl")
        fs = sorted(RUNS.glob("aecv-nemotron-v0-1536-*/results.jsonl"))
        self.nemo = {json.loads(l)["plan"]: json.loads(l) for l in open(fs[-1], encoding="utf-8")} if fs else {}
        lk = json.loads((RUNS / "aecv_leakage.json").read_text())
        self.leak = set(lk["train_overlap"])
        self._tb = {}
        for n in self.gold:  # toilet/bedroom readers (toilet symbols come from this detector cache)
            res, *_ = plansight(n, self.det, self.ocr, self.nemo, self.rooms)
            self._tb[n] = (len(res["Toilet"]), len(res["Bedroom"]))

    def predict(self, n, cfg):
        d, w = doors_windows(self.det.get(n), cfg, self.walls.get(n) if self.walls else None)
        if self.door_det is not None:  # doors from a second detector (e.g. v2), windows/toilets from the first
            d, _ = doors_windows(self.door_det.get(n), cfg)
        return {"Door": sum(k for _, k in d), "Window": len(w), "Toilet": self._tb[n][0], "Bedroom": self._tb[n][1]}

    def score(self, cfg, names):
        names = list(names)
        hit = {k: 0 for k in ("Door", "Window", "Toilet", "Bedroom")}
        for n in names:
            p = self.predict(n, cfg)
            for k in hit:
                hit[k] += p[k] == int(self.gold[n][k])
        return {k: round(100 * v / max(len(names), 1)) for k, v in hit.items()}, len(names)

    def subsets(self):
        A = [n for n in self.gold if self.split[n] == "A"]
        B = [n for n in self.gold if self.split[n] == "B"]
        return {"A": A, "B": B, "all": list(self.gold), "A_clean": [n for n in A if n not in self.leak],
                "B_clean": [n for n in B if n not in self.leak], "all_clean": [n for n in self.gold if n not in self.leak]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--det", default="aecv-cubicasa_objects-plain.jsonl")
    ap.add_argument("--door-det", default=None, help="take doors from this cache instead")
    ap.add_argument("--cfg", default="{}")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--show", default="A,A_clean", help="subsets to print; B only for finalists")
    a = ap.parse_args()
    b = Bench(a.det, a.door_det)
    S = b.subsets()
    cfg = json.loads(a.cfg)
    if a.grid:
        A = S["A"]
        res = []
        for td, tw, gap, xiou, dbl in itertools.product([.25, .3, .35, .4, .45, .5], [.2, .25, .3, .35, .4, .45],
                                                         [None, 0, 6, 15], [0, .3], [0, 1.6, 1.9]):
            c = {**cfg, "td": td, "tw": tw, "gap": gap, "xiou": xiou, "dbl": dbl}
            s, _ = b.score(c, A)
            res.append((s["Door"], s["Window"], c))
        for r in sorted(res, key=lambda r: (-r[0] - r[1]))[:8]:
            print("A door+win", r[0], r[1], json.dumps(r[2]))
        for r in sorted(res, key=lambda r: -r[0])[:4]:
            print("A door    ", r[0], r[1], json.dumps(r[2]))
        for r in sorted(res, key=lambda r: -r[1])[:4]:
            print("A window  ", r[0], r[1], json.dumps(r[2]))
        return
    for k in a.show.split(","):
        s, n = b.score(cfg, S[k])
        print(f"{k:10s} n={n:3d} door {s['Door']:3d} window {s['Window']:3d} toilet {s['Toilet']:3d} "
              f"bedroom {s['Bedroom']:3d}")


if __name__ == "__main__":
    main()
