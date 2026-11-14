"""Count accuracy of the cubicasa solver on CubiCasa's official test split (plans never used in training).

    python -m plansight.detect.evaluate --split test --mode det        # detector only
    python -m plansight.detect.evaluate --split test --mode det+vlm    # + Nemotron on borderline detections

Gold = the Junction dataset answers (English questions; Finnish ones carry the same answer). Writes
runs/det-<mode>-<split>-<ts>/{results.jsonl,summary.md}.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from plansight.config import QUESTIONS, RUNS
from plansight.router.english import parse_cubicasa_en
from plansight.solvers.cubicasa import count

SPLITS = Path(__file__).with_name("splits")


def plans(split: str) -> set[str]:
    return {f"data/cubicasa5k/{x.strip('/').replace('/', '-')}.png" for x in (SPLITS / f"{split}.txt").read_text().split()}


def rows(split: str, kinds=None):
    want = plans(split)
    out = []
    for line in QUESTIONS.open(encoding="utf-8"):
        r = json.loads(line)
        if r["path"] in want and (p := parse_cubicasa_en(r["question"])):
            k = p[1]["kind"]
            if kinds is None or k in kinds:
                out.append({**r, "kind": k})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m plansight.detect.evaluate")
    ap.add_argument("--split", default="test")
    ap.add_argument("--mode", default="det", choices=["det", "det+vlm"])
    ap.add_argument("--kinds", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    qs = rows(a.split, set(a.kinds.split(",")) if a.kinds else None)
    if a.limit:
        qs = qs[: a.limit]

    def one(q):
        t0 = time.perf_counter()
        try:
            c = count(q["path"], q["kind"], verify=a.mode == "det+vlm")
            if c is None:
                return q, None, 0.0, 0, 0, (time.perf_counter() - t0) * 1000, "no model"
            return q, len(c.counted), c.vlm_cost, len(c.border), len(c.rejected), (time.perf_counter() - t0) * 1000, None
        except Exception as e:  # noqa: BLE001
            return q, None, 0.0, 0, 0, (time.perf_counter() - t0) * 1000, repr(e)[:200]

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, qs))
    out = RUNS / f"det-{a.mode.replace('+', '_')}-{a.split}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    agg = defaultdict(lambda: defaultdict(float))
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for q, pred, cost, nb, nrej, ms, err in res:
            ok = pred is not None and pred == q["answer"]
            for k in (q["kind"], "ALL"):
                c = agg[k]
                c["n"] += 1; c["ok"] += ok; c["cost"] += cost; c["ms"] += ms; c["err"] += err is not None
                c["border"] += nb; c["rej"] += nrej
            f.write(json.dumps({"path": q["path"], "kind": q["kind"], "answer": q["answer"], "pred": pred, "ok": ok,
                                "border": nb, "rejected": nrej, "vlm_cost": cost, "ms": round(ms), "error": err}) + "\n")
    lines = [f"# {out.name} (n={len(res)})", "",
             "| kind | n | accuracy | errors | borderline/q | Nemotron rejected/q | VLM cost/q | ms/q |",
             "|---|---|---|---|---|---|---|---|"]
    for k in [*sorted(x for x in agg if x != "ALL"), "ALL"]:
        c = agg[k]; n = c["n"]
        lines.append(f"| {k} | {int(n)} | **{100 * c['ok'] / n:.1f}%** | {int(c['err'])} | {c['border'] / n:.2f} | "
                     f"{c['rej'] / n:.2f} | ${c['cost'] / n:.6f} | {c['ms'] / n:.0f} |")
    md = "\n".join(lines)
    (out / "summary.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
