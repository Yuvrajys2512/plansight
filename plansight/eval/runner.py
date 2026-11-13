"""CLI runner for PlanSight's deterministic and model-backed solvers."""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from plansight.config import RUNS
from plansight.eval.data import load_questions, sample_questions
from plansight.eval.scoring import score
from plansight.solvers import get_solver, route


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate PlanSight solvers on questions.jsonl")
    parser.add_argument("--preset", choices=("phase1", "phase2", "phase3", "final"))
    parser.add_argument("--solvers", default="auto", help="auto or comma-separated registry names")
    parser.add_argument("--sources", help="comma-separated source filter")
    parser.add_argument("--per-source", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--lang", help="comma-separated language codes")
    parser.add_argument("--types", help="comma-separated question types")
    return parser


def _choose_solver(selector: str, solvers: list, path: str):
    if selector == "auto":
        return route(path)
    return next((solver for solver in solvers if solver.can_handle(path)), None)


def _run_row(row: dict, selector: str, solvers: list) -> dict:
    start = time.perf_counter()
    answer = None
    error = None
    solver_name = None
    try:
        solver = _choose_solver(selector, solvers, row["path"])
        if solver is not None:
            solver_name = solver.name
            answer = solver.solve(row["path"], row["question"])
    except Exception as exc:  # errors are data in an evaluation run
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - start) * 1000
    answer_data = answer.to_dict() if answer is not None else None
    if error:
        status, correct = "error", False
    elif answer is None:
        status, correct = "abstain", False
    else:
        result = score(row.get("answer"), answer_data, row.get("type", "other"))
        status, correct = result["status"], result["correct"]
    return {
        "path": row["path"], "question": row["question"], "source": row["source"],
        "type": row.get("type", "other"), "lang": row["lang"], "expected": row.get("answer"),
        "unit": row.get("unit"), "answer": answer_data,
        "evidence_count": len(answer.evidence) if answer is not None else 0,
        "solver": solver_name, "status": status, "correct": correct, "error": error,
        "latency_ms": round(latency_ms, 3),
        "cost_usd": float(answer.cost_usd) if answer is not None else 0.0,
    }


def _groups(results: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in results:
        groups[(row["source"], row["type"], row["lang"])].append(row)
    return groups


def _metrics(rows: list[dict]) -> dict:
    # Abstentions and runtime errors count as wrong; only text answers are unscored.
    scored = [r for r in rows if r["status"] != "unscored"]
    return {
        "accuracy": sum(bool(r["correct"]) for r in scored) / len(scored) if scored else None,
        "abstain": sum(r["status"] == "abstain" for r in rows) / len(rows) if rows else 0,
        "errors": sum(r["status"] == "error" for r in rows),
        "latency": sum(r["latency_ms"] for r in rows) / len(rows) if rows else 0,
        "cost": sum(r["cost_usd"] for r in rows),
        "n": len(rows),
    }


def _render(results: list[dict]) -> str:
    lines = ["| Source | Type | Lang | N | Accuracy | Abstain | Errors | Latency ms | Cost USD |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for (source, qtype, lang), rows in sorted(_groups(results).items()):
        m = _metrics(rows)
        acc = "—" if m["accuracy"] is None else f"{m['accuracy']:.1%}"
        lines.append(f"| {source} | {qtype} | {lang} | {m['n']} | {acc} | {m['abstain']:.1%} | {m['errors']} | {m['latency']:.1f} | ${m['cost']:.6f} |")
    m = _metrics(results)
    acc = "—" if m["accuracy"] is None else f"{m['accuracy']:.1%}"
    lines.extend(["", f"Questions: {m['n']}  ", f"Scored accuracy: {acc}  ",
                  f"Abstain rate: {m['abstain']:.1%}  ", f"Errors: {m['errors']}  ",
                  f"Mean latency: {m['latency']:.1f} ms  ", f"Total cost: ${m['cost']:.6f}"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.preset == "phase1":
        args.solvers = "auto" if args.solvers == "auto" else args.solvers
        args.sources = args.sources or "swiss_dwellings,ifc_models"
        args.per_source = args.per_source or 300
        args.seed = 0 if args.seed is None else args.seed
    selector = args.solvers.strip()
    solvers = [] if selector == "auto" else [get_solver(name.strip()) for name in selector.split(",")]
    rows = load_questions()
    selected = sample_questions(
        rows, per_source=args.per_source, seed=args.seed,
        sources=set(args.sources.split(",")) if args.sources else None,
        langs=set(args.lang.split(",")) if args.lang else None,
        types=set(args.types.split(",")) if args.types else None,
    )
    results = [_run_row(row, selector, solvers) for row in selected]
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    out = Path(RUNS) / timestamp
    out.mkdir(parents=True, exist_ok=False)
    with (out / "results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
    summary = _render(results)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(summary, end="")
    print(f"\nResults: {out}")
    return 0
