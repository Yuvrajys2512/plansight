"""Offline AECV-Bench scoring from cached detections + OCR (scripts/aecv_cache.py). Seconds per run.

    python scripts/aecv_tune.py <AECV-Bench repo> [--split A|B|all] [--show Bedroom]
Split A = even-indexed plans (tune here), B = odd-indexed (report only). Sorted by plan id, so every source is in both.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402
from plansight.solvers.room_labels import find_labels  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402

KINDS = ("Door", "Window", "Toilet", "Bedroom")
THR = {"door": 0.35, "window": 0.45, "toilet": 0.35}


def load(name):
    f = RUNS / "detcache" / name
    return {json.loads(l)["plan"]: json.loads(l) for l in f.open(encoding="utf-8")} if f.exists() else {}


def split_of(plans, which):
    if which == "all":
        return plans
    return [p for i, p in enumerate(plans) if i % 2 == (0 if which == "A" else 1)]


def predict(name, det, ocr, thr=THR):
    out = {}
    d = det.get(name)
    if d:
        for k in ("door", "window", "toilet"):
            out[k.capitalize()] = sum(1 for c, s, *_ in d["dets"] if c == k and s >= thr[k])
    o = ocr.get(name)
    if o:
        toks = [(t, c, b) for t, c, *b in o["tokens"]]
        bed = find_labels(toks, "bedroom")
        wc = find_labels(toks, "toilet")
        out["Bedroom"] = len(bed)
        out["Toilet_label"] = len(wc)
        out["_bed"], out["_wc"] = [t for t, _ in bed], [t for t, _ in wc]
        if wc:  # rooms labelled as toilets/baths: the AECV definition. No labels at all -> fall back to symbols
            out["Toilet"] = len(wc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--split", default="A")
    ap.add_argument("--det", default="aecv-cubicasa_objects-plain.jsonl")
    ap.add_argument("--show", default="")
    a = ap.parse_args()
    plans = split_of(aecv_plans(Path(a.repo)), a.split)
    det, ocr = load(a.det), load("aecv-ocr.jsonl")
    acc = defaultdict(lambda: [0, 0])
    for name, _, gold in plans:
        pred = predict(name, det, ocr)
        for k in KINDS:
            if k in pred and k in gold:
                ok = pred[k] == gold[k]
                acc[k][0] += ok
                acc[k][1] += 1
                if a.show == k and not ok:
                    extra = pred.get("_bed" if k == "Bedroom" else "_wc", "")
                    print(f"  {name} {k}: gold {gold[k]} pred {pred[k]} {extra}")
    print(f"split {a.split}: " + "  ".join(f"{k} {100 * acc[k][0] / max(acc[k][1], 1):.0f}% (n={acc[k][1]})"
                                           for k in KINDS))


if __name__ == "__main__":
    main()
