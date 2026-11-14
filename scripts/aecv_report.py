"""AECV-Bench scoreboard: frontier models (published per-plan answers) vs PlanSight variants, per split, with cost.

    python scripts/aecv_report.py <AECV-Bench repo>
Writes runs/aecv-report/report.md (tables) and runs/aecv-report/plans.json (per-plan gold, frontier answers,
PlanSight answers + evidence boxes) for the "Frontier vs PlanSight" UI panel.
Split A (even-indexed plans) was used to tune counting rules; split B (odd) was never tuned on.
"""
from __future__ import annotations

import csv
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402
from plansight.solvers.room_labels import find_labels  # noqa: E402
from plansight.vlm.openings import merge_adjacent  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402
from scripts.aecv_tune import load  # noqa: E402

KINDS = ("Door", "Window", "Toilet", "Bedroom")
SHOW = ["gemini_35_flash", "gemini_3_pro_preview", "claude_fable_5", "claude_opus_48", "openai_gpt_55",
        "qwen_37_plus", "gemma_4_31b_it", "nvidia_nemotron_3_nano_omni_30b"]
CPU_USD_PER_S = 0.10 / 3600
TD, TW, GAP = 0.35, 0.30, 6  # tuned on split A (scripts/aecv_rules.py)


def _eq(a, b) -> bool:
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


def frontier(repo: Path):
    out, cost = {}, {}
    for f in sorted((repo / "benchmark_result_object_counting").glob("*.csv")):
        m = f.stem
        ans = {}
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            try:
                a = json.loads(r["extracted"])
                if isinstance(a, str):
                    a = json.loads(a)
                ans[r["name"]] = a if isinstance(a, dict) else {}
            except (ValueError, TypeError):
                ans[r["name"]] = {}
        out[m] = ans
        s = f.with_name(f"{m}_summary.json")
        if s.exists():
            d = json.loads(s.read_text(encoding="utf-8"))
            cost[m] = d["total_cost_usd"] / max(d["folders_succeeded"], 1)
    return out, cost


def plansight(name, det, ocr, nemo, rooms):
    """Final PlanSight answer for one plan: {kind: [evidence]}, notes, cost. Rules chosen on split A only.

    Doors: fine-tuned detector (score >= 0.35). Windows: detector (>= 0.30) + AECV's rule "adjacent windows with no
    gap are one window" (touching boxes merged). Bedrooms: three readers (OCR label lexicon, rooms detector, Nemotron
    reading the whole plan) rarely invent rooms but each misses some -> max. Toilets: same three readers -> median.
    (A v1 where Nemotron reclassified every door/window crop helped split A but hurt split B: dropped, see report.)
    """
    res, notes, trace = {}, {}, {}
    d, o, rm, nm = det.get(name) or {}, ocr.get(name) or {}, rooms.get(name) or {}, nemo.get(name) or {}
    dets = d.get("dets", [])
    res["Door"] = [{"bbox": x[2:], "label": f"door {x[1]:.2f}"} for x in dets if x[0] == "door" and x[1] >= TD]
    wins = [x[2:] for x in dets if x[0] == "window" and x[1] >= TW]
    res["Window"] = [{"bbox": list(b), "label": "window"} for b in merge_adjacent(wins, GAP)]
    n_doors = sum(1 for x in dets if x[0] == "door" and x[1] >= TD)
    trace["Door"] = {"rule": "detector", "voters": {"detector": n_doors, "nemotron": nm.get("pred", {}).get("Door")},
                     "used": "detector"}
    trace["Window"] = {"rule": "detector + merge touching", "voters": {
        "detector": len(wins), "nemotron": nm.get("pred", {}).get("Window")}, "used": "detector",
        "after_merge": len(res["Window"])}
    toks = [(t, c, b) for t, c, *b in o.get("tokens", [])]
    n_pred = nm.get("pred", {})
    bed = {"labels": [{"bbox": list(b), "label": t} for t, b in find_labels(toks, "bedroom")],
           "rooms model": [{"bbox": x[2:], "label": "bedroom (rooms model)"} for x in rm.get("dets", [])
                           if x[0] == "bedroom" and x[1] >= .5]}
    nb = n_pred.get("Bedroom") or 0
    best = max(bed, key=lambda k: len(bed[k]))
    res["Bedroom"] = bed[best]
    trace["Bedroom"] = {"rule": "max of 3 readers", "voters": {"OCR labels": len(bed["labels"]),
                        "rooms model": len(bed["rooms model"]), "nemotron": nb},
                        "used": {"labels": "OCR labels"}.get(best, best)}
    if nb > len(bed[best]):
        trace["Bedroom"]["used"] = "nemotron"
        notes["Bedroom"] = f"Nemotron read {nb} bedrooms on the plan; {len(bed[best])} located"
        res["Bedroom"] = bed[best] + [{"bbox": None, "label": "Nemotron (unlocated)"}] * (nb - len(bed[best]))
    wc = {"labels": [{"bbox": list(b), "label": t} for t, b in find_labels(toks, "toilet")],
          "symbols": [{"bbox": x[2:], "label": "toilet symbol"} for x in dets if x[0] == "toilet" and x[1] >= .35]}
    nt = n_pred.get("Toilet") or 0
    med = sorted([len(wc["labels"]), len(wc["symbols"]), nt])[1]
    pick = min(wc.values(), key=lambda v: (abs(len(v) - med), -len(v)))
    trace["Toilet"] = {"rule": "median of 3 readers", "voters": {"OCR labels": len(wc["labels"]),
                       "symbol detector": len(wc["symbols"]), "nemotron": nt},
                       "used": [k for k, v in {"OCR labels": len(wc["labels"]), "symbol detector": len(wc["symbols"]),
                                               "nemotron": nt}.items() if v == med]}
    res["Toilet"] = (pick + [{"bbox": None, "label": "Nemotron (unlocated)"}] * med)[:med]
    cost = (8 + 3) * CPU_USD_PER_S + (nm.get("cost_usd") or 0.0)  # CPU OCR + 2 detector passes + one Nemotron read
    return res, notes, cost, trace


def main():
    repo = Path(sys.argv[1])
    plans = aecv_plans(repo)
    split = {p[0]: "AB"[i % 2] for i, p in enumerate(plans)}
    gold = {p[0]: p[2] for p in plans}
    fr, fcost = frontier(repo)
    det, ocr = load("aecv-cubicasa_objects-plain.jsonl"), load("aecv-ocr.jsonl")
    rooms = load("aecv-cubicasa_rooms-plain.jsonl")
    nemo = {}
    for tag in ("v0-1536",):  # thinking mode: most replies were not parseable JSON (2% exact): left out
        fs = sorted(glob.glob(str(RUNS / f"aecv-nemotron-{tag}-*" / "results.jsonl")))
        if fs:
            nemo[tag] = {json.loads(l)["plan"]: json.loads(l) for l in open(fs[-1], encoding="utf-8")}

    systems = {}
    for m in SHOW:
        if m in fr:
            systems[m] = ({n: fr[m].get(n, {}) for n in gold}, fcost.get(m))
    for tag, rows in nemo.items():
        systems[f"nemotron_3.5_super_vl ({tag}, self-hosted)"] = (
            {n: (rows[n]["pred"] if n in rows else {}) for n in gold},
            sum(r["cost_usd"] for r in rows.values()) / max(len(rows), 1))
    det_only = {}
    for n in gold:
        d = det.get(n)
        det_only[n] = {k: sum(1 for x in d["dets"] if x[0] == k.lower() and x[1] >= t)
                       for k, t in (("Door", .35), ("Window", .45), ("Toilet", .35))} if d else {}
    systems["PlanSight detector only (zero-shot)"] = (det_only, 2 * CPU_USD_PER_S)
    ours, our_cost = {}, {}
    for n in gold:
        res, _, c, _t = plansight(n, det, ocr, nemo.get("v0-1536", {}), rooms)
        ours[n] = {k: len(v) for k, v in res.items()}
        our_cost[n] = c
    systems["**PlanSight hybrid**"] = (ours, sum(our_cost.values()) / len(our_cost))

    lines = ["# AECV-Bench object counting: frontier models vs PlanSight", "",
             "Exact-match accuracy. Split A (60 plans) tuned PlanSight's counting rules; **split B (60 plans) was "
             "never tuned on**. Frontier answers and costs are the published AECV-Bench results.", ""]
    for sp in ("B", "A", "all"):
        names = [n for n in gold if sp == "all" or split[n] == sp]
        lines += [f"## Split {sp} ({len(names)} plans)", "",
                  "| System | " + " | ".join(KINDS) + " | Mean | $/plan |", "|---" * (len(KINDS) + 3) + "|"]
        for sysname, (ans, cost) in systems.items():
            accs = []
            for k in KINDS:
                have = [n for n in names if k in ans.get(n, {}) and ans[n][k] is not None]
                ok = sum(_eq(ans[n][k], gold[n][k]) for n in have if k in gold[n])
                accs.append(100 * ok / len(names) if have else None)
            mean = sum(a for a in accs if a is not None) / max(1, sum(a is not None for a in accs))
            cell = lambda a: "n/a" if a is None else f"{a:.0f}%"  # noqa: E731
            lines.append(f"| {sysname} | " + " | ".join(cell(a) for a in accs) +
                         f" | {mean:.0f}% | {'n/a' if cost is None else f'${cost:.5f}'} |")
        lines.append("")
    out = RUNS / "aecv-report"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    ui = {}
    nm_rows = nemo.get("v0-1536", {})
    for n, img, g in plans:
        res, notes, c, trace = plansight(n, det, ocr, nemo.get("v0-1536", {}), rooms)
        ui[n] = {"image": f"img/{n}.jpg", "split": split[n], "gold": {k: g.get(k) for k in KINDS},
                 "frontier": {m: {k: fr[m].get(n, {}).get(k) for k in KINDS} for m in SHOW if m in fr},
                 "frontier_cost_usd": {m: fcost.get(m) for m in SHOW if m in fr},
                 "plansight": {k: {"count": len(v), "evidence": [e for e in v if e["bbox"]], "note": notes.get(k)}
                               for k, v in res.items()},
                 "plansight_cost_usd": c,
                 "nemotron": ({"counts": {k: nm_rows[n]["pred"].get(k) for k in KINDS},
                              "cost_usd": nm_rows[n].get("cost_usd"), "latency_ms": nm_rows[n].get("latency_ms"),
                              "model": "Nemotron 3.5 Super VL (NVFP4, self-hosted on Verda)"} if n in nm_rows else None),
                 "trace": trace}
    (out / "plans.json").write_text(json.dumps(ui), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
