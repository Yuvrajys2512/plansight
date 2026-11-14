"""Router accuracy: does a question in any language map to the same (template, params) as its English sibling?

    python -m plansight.router.eval --n 1000 --seed 0            # held-out: bank mined on the other half of buildings
    python -m plansight.router.eval --n 1000 --bank full          # with the shipped bank (in-sample)
    python -m plansight.router.eval --n 200 --gemma-only          # skip the bank: measure Gemma alone

Ground truth comes from the dataset structure (every translation follows its English sibling, same path and
answer). Writes runs/router-<ts>/results.jsonl + summary.md and prints a table by domain x language.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from plansight.config import RUNS
from plansight.router import Route
from plansight.router.bank import Bank, default_bank, load_rows, mine, norm, pairs
from plansight.router.english import SLOT_KEYS, domain_of, parse_en
from plansight.router.lang import detect


def building(path: str) -> str:
    """Split unit: IFC model / Swiss building / cubicasa plan, so held-out questions are about unseen buildings."""
    return Path(path).stem.split("_plan-")[0].split("_floor")[0]


def in_train(path: str) -> bool:
    return int(hashlib.md5(building(path).encode()).hexdigest(), 16) % 2 == 0


def _canon(template: str | None, params: dict) -> tuple:
    return template, tuple(sorted((k, norm(str(v)) if k in SLOT_KEYS else v) for k, v in params.items()
                                  if v is not None))


def items(rows: list[dict]) -> list[dict]:
    """Every routable question with its ground truth: English rows (own parse) and translations (sibling's)."""
    out = []
    for r in rows:
        dom = domain_of(r["path"])
        if dom and (p := parse_en(dom, r["question"])):
            out.append({"path": r["path"], "domain": dom, "question": r["question"], "truth": p, "lang": "en"})
    for dom, en, p, tr in pairs(rows):
        out.append({"path": tr["path"], "domain": dom, "question": tr["question"], "truth": p,
                    "lang": detect(tr["question"])})
    return out


def sample(its: list[dict], n: int, seed: int) -> list[dict]:
    """n questions spread evenly over domains, uniform within a domain (so rare IFC languages still show up)."""
    rng = random.Random(seed)
    by = defaultdict(list)
    for it in its:
        by[it["domain"]].append(it)
    out = []
    doms = sorted(by)
    for i, d in enumerate(doms):
        k = n // len(doms) + (1 if i < n % len(doms) else 0)
        out += rng.sample(by[d], min(k, len(by[d])))
    rng.shuffle(out)
    return out


def run(args) -> Path:
    rows = load_rows()
    its = items(rows)
    if args.bank == "heldout":
        entries, _ = mine(rows, keep=in_train)
        bank = Bank(entries)
        its = [it for it in its if not in_train(it["path"])]
    else:
        bank = default_bank()
    if args.domains:
        its = [it for it in its if it["domain"] in args.domains.split(",")]
    todo = sample(its, args.n, args.seed)
    if args.gemma_only:
        todo = [it for it in todo if it["lang"] != "en"]

    # pass 1: $0 routes (English parser, then bank)
    results: list[tuple[dict, Route]] = []
    misses = []
    for it in todo:
        t0 = time.perf_counter()
        if not args.gemma_only and (p := parse_en(it["domain"], it["question"])):
            results.append((it, Route(*p, method="en", latency_ms=(time.perf_counter() - t0) * 1000)))
        elif not args.gemma_only and (m := bank.match(it["domain"], it["question"])):
            results.append((it, Route(m.template, m.params, method="bank", lang=m.lang,
                                      latency_ms=(time.perf_counter() - t0) * 1000)))
        else:
            misses.append(it)

    # pass 2: Gemma on what's left, in parallel
    def ask(it):
        from plansight.router import gemma

        t0 = time.perf_counter()
        try:
            p, cost, cached = gemma.route(it["domain"], it["question"])
        except Exception as e:  # noqa: BLE001
            print("gemma error:", e)
            p, cost = None, 0.0
        ms = (time.perf_counter() - t0) * 1000
        return it, Route(*(p or (None, {})), method="gemma" if p else "none", cost_usd=cost, latency_ms=ms)

    if misses and not args.no_llm:
        print(f"{len(misses)} questions -> Gemma ({args.workers} workers)...")
        with ThreadPoolExecutor(args.workers) as ex:
            results += list(ex.map(ask, misses))
    else:
        results += [(it, Route(None, method="none")) for it in misses]

    # score
    out_dir = RUNS / f"router-{datetime.now():%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cells = defaultdict(lambda: defaultdict(float))
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for it, r in results:
            ok = _canon(r.template, r.params) == _canon(*it["truth"])
            for key in [(it["domain"], it["lang"]), (it["domain"], "ALL"), ("ALL", "ALL")]:
                c = cells[key]
                c["n"] += 1
                c["ok"] += ok
                c[r.method] += 1
                c[f"ok_{r.method}"] += ok
                c["cost"] += r.cost_usd
            f.write(json.dumps({"path": it["path"], "domain": it["domain"], "lang": it["lang"],
                                "question": it["question"], "truth": it["truth"], "method": r.method,
                                "template": r.template, "params": r.params, "ok": ok, "cost_usd": r.cost_usd,
                                "latency_ms": round(r.latency_ms, 1)}, ensure_ascii=False) + "\n")

    def pct(a, b):
        return f"{100 * a / b:.1f}%" if b else "-"

    hdr = "| domain | lang | n | accuracy | en | bank | gemma | none | gemma acc | cost total |"
    lines = [f"# Router eval {out_dir.name}", "",
             f"bank: {args.bank} ({bank.size} patterns), n={len(results)}, seed={args.seed}, "
             f"gemma_only={args.gemma_only}, no_llm={args.no_llm}", "", hdr, "|" + "---|" * 10]
    for key in sorted(cells, key=lambda k: (k[0] == "ALL", k[0], k[1] == "ALL", k[1])):
        c = cells[key]
        lines.append(f"| {key[0]} | {key[1]} | {int(c['n'])} | **{pct(c['ok'], c['n'])}** | {int(c['en'])} | "
                     f"{int(c['bank'])} | {int(c['gemma'])} | {int(c['none'])} | "
                     f"{pct(c['ok_gemma'], c['gemma'])} | ${c['cost']:.5f} |")
    wrong = [(it, r) for it, r in results if _canon(r.template, r.params) != _canon(*it["truth"])]
    lines += ["", f"## Misses ({len(wrong)})", ""]
    lines += [f"- [{it['domain']}/{it['lang']}/{r.method}] {it['question']}  \n  truth {it['truth']} got "
              f"{r.template} {r.params}" for it, r in wrong[:60]]
    md = "\n".join(lines)
    (out_dir / "summary.md").write_text(md, encoding="utf-8")
    print(md)
    return out_dir


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m plansight.router.eval")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--bank", choices=["heldout", "full"], default="heldout")
    ap.add_argument("--domains", default="")
    ap.add_argument("--gemma-only", action="store_true", help="skip English parser + bank; non-English only")
    ap.add_argument("--no-llm", action="store_true", help="never call Gemma")
    ap.add_argument("--workers", type=int, default=8)
    run(ap.parse_args(argv))


if __name__ == "__main__":
    main()
