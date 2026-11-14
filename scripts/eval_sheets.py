"""Run the sheet QA solver on every opening_design question; print pred vs gold and a numeric auto-score.

    python scripts/eval_sheets.py [--limit N]
Writes runs/sheets-<ts>/results.jsonl. Text answers are marked for manual/LLM judging.
"""
import argparse, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import QUESTIONS, RUNS, resolve
from plansight.sheets.qa import ask

def num(x):
    m = re.findall(r"-?\d[\d,]*\.?\d*", str(x)); return float(m[0].replace(",", "")) if m else None

ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--workers", type=int, default=4)
a = ap.parse_args()
qs = [json.loads(l) for l in QUESTIONS.open(encoding="utf-8") if "/opening_design/" in l]
qs = [q for q in qs if q["path"].lower().endswith(".pdf")][: a.limit or None]

def one(q):
    t0 = time.time()
    try:
        r = ask(str(resolve(q["path"])), q["question"]); return q, r.answer, len(r.rows), r.cost_usd, time.time() - t0, None
    except Exception as e:
        return q, None, 0, 0.0, time.time() - t0, repr(e)[:200]

with ThreadPoolExecutor(a.workers) as ex: res = list(ex.map(one, qs))
out = RUNS / f"sheets-{datetime.now():%Y%m%d-%H%M%S}"; out.mkdir(parents=True, exist_ok=True)
ok_num = n_num = 0; cost = 0
with (out / "results.jsonl").open("w", encoding="utf-8") as f:
    for q, pred, nrows, c, s, err in res:
        cost += c
        numeric = q.get("unit") in ("count", "ft2") or isinstance(q["answer"], (int, float))
        ok = None
        if numeric:
            n_num += 1; ok = num(pred) is not None and abs(num(pred) - float(q["answer"])) < 0.5; ok_num += bool(ok)
        f.write(json.dumps({"q": q["question"], "gold": q["answer"], "pred": pred, "ok": ok, "rows": nrows, "err": err}, ensure_ascii=False) + "\n")
        mark = "OK " if ok else ("?? " if ok is None else "XX ")
        print(f"{mark}{str(q['answer'])[:28]:28s} <- {str(pred)[:40]:40s} rows={nrows:3d} {s:4.1f}s {q['question'][q['question'].find(',')+2:][:70]}" + (f" ERR {err[:60]}" if err else ""))
print(f"\nnumeric: {ok_num}/{n_num}; total cost ${cost:.4f}; {out}")
