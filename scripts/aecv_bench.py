"""Zero-shot PlanSight detectors on AECV-Bench object counting (120 plans; github.com/AECFoundry/AECV-Bench).

    python scripts/aecv_bench.py <AECV-Bench repo dir> [--verify]
Compares exact-match accuracy per class with every frontier model's published results in the repo.
"""
import csv, json, sys, glob, os, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("PLANSIGHT_NO_LLM", "1")
from plansight.solvers.cubicasa import count  # noqa: E402

repo = Path(sys.argv[1])
verify = "--verify" in sys.argv
root = repo / "data/Use Case 1 - Object Counting/1 - Full Datasets"
KINDS = {"Door": "door", "Window": "window", "Toilet": "toilet", "Bedroom": "bedroom"}
plans = []
for d in sorted(root.iterdir()):
    img = next(iter(sorted(d.glob("*.png")) + sorted(d.glob("*.jp*g"))), None)
    meta = d / "metadata.json"
    if img and meta.exists():
        plans.append((d.name, str(img.resolve()), json.loads(meta.read_text(encoding="utf-8-sig"))))


def one(p):
    name, img, gold = p
    out = {}
    for k, kind in KINDS.items():
        c = count(img, kind, verify=verify)
        out[k] = None if c is None else len(c.counted)
    return name, gold, out


t0 = time.time()
with ThreadPoolExecutor(3) as ex:
    res = list(ex.map(one, plans))
acc = defaultdict(lambda: [0, 0])
by_src = defaultdict(lambda: defaultdict(lambda: [0, 0]))
out_dir = Path("runs") / f"aecv-{'det_vlm' if verify else 'det'}-{time.strftime('%Y%m%d-%H%M%S')}"
out_dir.mkdir(parents=True, exist_ok=True)
with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
    for name, gold, pred in res:
        f.write(json.dumps({"plan": name, "gold": gold, "pred": pred}) + "\n")
        for k in KINDS:
            if k in gold:
                ok = pred[k] is not None and int(pred[k]) == int(gold[k])
                acc[k][0] += ok; acc[k][1] += 1
                by_src[name[:4]][k][0] += ok; by_src[name[:4]][k][1] += 1

def pct(a): return round(100 * a[0] / max(a[1], 1))
lines = [f"PlanSight ({'det+Nemotron' if verify else 'detector only'}), {len(res)} plans, {time.time()-t0:.0f}s: " +
         "  ".join(f"{k} {pct(acc[k])}%" for k in KINDS)]
for s in sorted(by_src):
    lines.append(f"  source {s}: " + "  ".join(f"{k} {pct(by_src[s][k])}% (n={by_src[s][k][1]})" for k in KINDS))
lines.append("Published frontier results (same 120 plans):")
board = []
for fcsv in sorted((repo / "benchmark_result_object_counting").glob("*.csv")):
    a = defaultdict(lambda: [0, 0])
    for r in csv.DictReader(open(fcsv, encoding="utf-8-sig")):
        g = json.loads(r["original"])
        try:
            p = json.loads(r["extracted"])
        except Exception:
            p = {}
        p = p if isinstance(p, dict) else {}
        for k in KINDS:
            if k in g:
                a[k][1] += 1; a[k][0] += str(p.get(k)) == str(g[k])
    board.append((fcsv.stem, {k: pct(a[k]) for k in KINDS}))
board.sort(key=lambda r: -(r[1]["Door"] + r[1]["Window"]))
for n, a in board[:8]:
    lines.append(f"  {n:30s} " + "  ".join(f"{k} {a[k]}%" for k in KINDS))
(out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines)); print(out_dir)
