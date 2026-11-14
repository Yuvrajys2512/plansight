"""Cheap first, escalate when unsure: PlanSight answers every plan; only plans where PlanSight is unsure go to a
frontier model, and only the unsure kinds take the frontier's answer.

Simulated with AECV-Bench's published per-plan frontier answers and per-plan costs (the same call we'd make live).
    python scripts/aecv_escalate.py --partner gemini_35_flash --grid      # tune on split A ONLY
    python scripts/aecv_escalate.py --partner gemini_35_flash --cfg '{...}' --show A,B,B_clean
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.aecv_eval import REPO, Bench  # noqa: E402
from scripts.aecv_report import frontier, plansight  # noqa: E402

KINDS = ("Door", "Window", "Toilet", "Bedroom")


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Esc:
    def __init__(self, partner, live=False):
        self.b = Bench("aecv-cubicasa_objects-plain.jsonl")
        fr, cost = frontier(REPO)
        self.fr, self.fcost = fr[partner], cost.get(partner) or 0.0
        if live:  # our own same-day Gemini 3.5 Flash calls (scripts/aecv_escalate_live.py) instead of published ones
            f = Path(__file__).resolve().parents[1] / "runs/detcache/aecv-gemini35flash-live.jsonl"
            self.fr = {json.loads(line)["plan"]: json.loads(line) for line in f.open(encoding="utf-8")}
        self.feat, self.ours, self.our_cost = {}, {}, {}
        for n in self.b.gold:
            res, _, c, tr = plansight(n, self.b.det, self.b.ocr, self.b.nemo, self.b.rooms)
            self.ours[n] = {k: len(v) for k, v in res.items()}
            self.our_cost[n] = c
            dets = self.b.det.get(n, {}).get("dets", [])
            nm = (self.b.nemo.get(n) or {}).get("pred", {}) or {}
            f = {}
            for k, cls, t in (("Door", "door", .35), ("Window", "window", .30)):
                border = sum(1 for x in dets if x[0] == cls and t - .15 <= x[1] < t + .2)
                nv = _int(nm.get(k))
                f[k] = (border, abs(nv - self.ours[n][k]) if nv is not None else 0)
            for k in ("Toilet", "Bedroom"):
                v = [x for x in tr[k]["voters"].values() if isinstance(x, int)]
                f[k] = (max(v) - min(v) if v else 0, 0)
            self.feat[n] = f

    def predict(self, n, cfg):
        """cfg[k] = (border_thr, nemo_gap_thr): kind k is unsure if border >= thr or nemotron disagrees by >= gap."""
        unsure = [k for k in KINDS if k in cfg and (self.feat[n][k][0] >= cfg[k][0] or self.feat[n][k][1] >= cfg[k][1])]
        out = dict(self.ours[n])
        fa = self.fr.get(n, {}) or {}
        for k in unsure:
            v = _int(fa.get(k))
            if v is not None:
                out[k] = v
        return out, bool(unsure)

    def score(self, cfg, names):
        hit = {k: 0 for k in KINDS}
        esc = 0
        for n in names:
            p, e = self.predict(n, cfg)
            esc += e
            for k in KINDS:
                hit[k] += p[k] == int(self.b.gold[n][k])
        N = len(names)
        acc = {k: round(100 * v / N) for k, v in hit.items()}
        acc["Mean"] = round(sum(hit.values()) / (4 * N) * 100)
        cost = sum(self.our_cost[n] for n in names) / N + esc / N * self.fcost
        return acc, round(100 * esc / N), cost

    def frontier_alone(self, names):
        hit = {k: sum(_int((self.fr.get(n) or {}).get(k)) == int(self.b.gold[n][k]) for n in names) for k in KINDS}
        return {k: round(100 * v / len(names)) for k, v in hit.items()}, round(sum(hit.values()) / (4 * len(names)) * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partner", default="gemini_35_flash")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--cfg", default=None)
    ap.add_argument("--show", default="A")
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    e = Esc(a.partner, a.live)
    S = e.b.subsets()
    INF = 99
    if a.grid:
        A = S["A"]
        print("ours on A", e.score({}, A)[0], " partner alone", e.frontier_alone(A))
        opts = [(INF, INF), (1, INF), (2, INF), (3, INF), (5, INF), (INF, 1), (INF, 2), (INF, 3), (2, 2), (3, 2)]
        topts = [(INF, INF), (1, INF), (2, INF), (3, INF)]
        res = []
        for d, w, t, bd in itertools.product(opts, opts, topts, topts):
            cfg = {"Door": d, "Window": w, "Toilet": t, "Bedroom": bd}
            acc, esc, cost = e.score(cfg, A)
            res.append((acc["Mean"], -esc, acc, esc, cost, cfg))
        res.sort(key=lambda r: (r[0], r[1]), reverse=True)
        for r in res[:6]:
            print(r[0], "esc%", r[3], f"${r[4]:.4f}", r[2], json.dumps(r[5]))
        # cheapest config within 2 pts of the best mean
        best = res[0][0]
        cheap = min((r for r in res if r[0] >= best - 2), key=lambda r: r[4])
        print("cheapest within 2pt:", cheap[0], "esc%", cheap[3], f"${cheap[4]:.4f}", json.dumps(cheap[5]))
        return
    cfg = {k: tuple(v) for k, v in json.loads(a.cfg).items()} if a.cfg else {}
    for k in a.show.split(","):
        acc, esc, cost = e.score(cfg, S[k])
        fa, fm = e.frontier_alone(S[k])
        print(f"{k:8s} n={len(S[k])} ours+esc {acc} esc {esc}% ${cost:.4f}/plan | {a.partner} alone {fa} mean {fm} "
              f"${e.fcost:.4f}")


if __name__ == "__main__":
    main()
