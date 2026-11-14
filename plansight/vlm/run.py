"""Nemotron version loop on the fixed cubicasa dev set. Each version is a function (path, question, kind) -> int|None.

    python -m plansight.vlm.run --version v0 --split dev --workers 8

Writes runs/vlm-<version>-<ts>/results.jsonl + summary.md; prints accuracy per template, cost/question, latency.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from plansight.config import RUNS, resolve
from plansight.vlm import nemotron
from plansight.vlm.devset import VISUAL, questions


def _int(text: str) -> int | None:
    m = re.findall(r"-?\d+", text or "")
    return int(m[-1]) if m else None


COUNT_SCHEMA = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}


def v0(path: str, question: str, kind: str):
    """Baseline: whole plan image + the question, structured output {"count": int} (no reasoning)."""
    img = nemotron.encode_image(resolve(path))
    r = nemotron.ask(question, [img], json_schema=COUNT_SCHEMA, max_tokens=32)
    return _int(r.text), r


def v0_cot(path: str, question: str, kind: str):
    """Baseline + brief step-by-step reasoning in the answer, final 'ANSWER: n'."""
    img = nemotron.encode_image(resolve(path))
    r = nemotron.ask(f"{question} Think step by step briefly, then end with: ANSWER: <integer>", [img],
                     max_tokens=1200)
    m = re.search(r"ANSWER:\s*(-?\d+)", r.text)
    return (int(m[1]) if m else None), r


def v1(path: str, question: str, kind: str):
    """Whole plan upscaled 2x (thin symbols span more vision patches), structured count."""
    from PIL import Image

    im = Image.open(resolve(path)).convert("RGB")
    im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
    r = nemotron.ask(question, [nemotron.encode_image(im, max_side=2600)], json_schema=COUNT_SCHEMA, max_tokens=32)
    return _int(r.text), r


class _Agg:
    def __init__(self, c):
        self.cost_usd, self.tokens_in, self.tokens_out = c.cost_usd, c.tokens_in, c.tokens_out


def v2(path: str, question: str, kind: str):
    """Upscaled overlapping tiles, one box per object, dedupe across tiles (floors: falls back to v0)."""
    from PIL import Image

    from plansight.vlm.count import count_objects

    if kind == "floor":
        return v0(path, question, kind)
    c = count_objects(Image.open(resolve(path)), kind, question)
    return c.n, _Agg(c)


VERSIONS = {"v0": v0, "v0_cot": v0_cot, "v1": v1, "v2": v2}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m plansight.vlm.run")
    ap.add_argument("--version", default="v0", choices=sorted(VERSIONS))
    ap.add_argument("--split", default="dev")
    ap.add_argument("--kinds", default=",".join(VISUAL))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    qs = questions(a.split, tuple(a.kinds.split(",")))
    if a.limit:
        qs = qs[: a.limit]
    fn = VERSIONS[a.version]

    def one(q):
        t0 = time.perf_counter()
        try:
            pred, r = fn(q["path"], q["question"], q["kind"])
            return q, pred, r.cost_usd, r.tokens_in, r.tokens_out, (time.perf_counter() - t0) * 1000, None
        except Exception as e:  # noqa: BLE001
            return q, None, 0.0, 0, 0, (time.perf_counter() - t0) * 1000, repr(e)[:200]

    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, qs))

    out = RUNS / f"vlm-{a.version}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    agg = defaultdict(lambda: defaultdict(float))
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for q, pred, cost, tin, tout, ms, err in res:
            ok = pred is not None and pred == q["answer"]
            for k in (q["kind"], "ALL"):
                c = agg[k]
                c["n"] += 1; c["ok"] += ok; c["cost"] += cost; c["ms"] += ms; c["err"] += err is not None
                c["abs_err"] += abs(pred - q["answer"]) if pred is not None else 0
                c["tin"] += tin; c["tout"] += tout
            f.write(json.dumps({"path": q["path"], "kind": q["kind"], "answer": q["answer"], "pred": pred, "ok": ok,
                                "cost_usd": cost, "latency_ms": round(ms), "error": err}) + "\n")
    lines = [f"# {out.name} ({a.split}, n={len(res)})", "",
             "| template | n | accuracy | mean abs err | errors | cost/q | tokens in/out per q | latency ms |",
             "|---|---|---|---|---|---|---|---|"]
    for k in [*sorted(x for x in agg if x != "ALL"), "ALL"]:
        c = agg[k]; n = c["n"]
        lines.append(f"| {k} | {int(n)} | **{100 * c['ok'] / n:.1f}%** | {c['abs_err'] / n:.2f} | {int(c['err'])} | "
                     f"${c['cost'] / n:.5f} | {c['tin'] / n:.0f}/{c['tout'] / n:.0f} | {c['ms'] / n:.0f} |")
    md = "\n".join(lines)
    (out / "summary.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
