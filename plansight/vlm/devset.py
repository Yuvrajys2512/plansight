"""Fixed cubicasa plan sets for the Nemotron loop: `dev` (40 plans, iterate on these) and `heldout` (100 plans,
touched only for final numbers). `python -m plansight.vlm.devset` rebuilds devset.json (seeded, deterministic)."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from plansight.router.english import parse_cubicasa_en

PATH = Path(__file__).with_name("devset.json")
VISUAL = ("window", "floor", "toilet", "sink", "shower_bath", "door")


def load() -> dict[str, list[str]]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def questions(split: str = "dev", kinds=VISUAL) -> list[dict]:
    """English rows (path, question, answer, kind) for the plans in `split`."""
    from plansight.router.bank import load_rows

    plans = set(load()[split])
    out = []
    for r in load_rows():
        if r["path"] in plans and (p := parse_cubicasa_en(r["question"])) and p[1]["kind"] in kinds:
            out.append({**r, "kind": p[1]["kind"]})
    return out


if __name__ == "__main__":
    from plansight.router.bank import load_rows

    kinds_by_plan = defaultdict(set)
    for r in load_rows():
        if "/cubicasa5k/" in r["path"] and (p := parse_cubicasa_en(r["question"])):
            kinds_by_plan[r["path"]].add(p[1]["kind"])
    full = sorted(p for p, ks in kinds_by_plan.items() if set(VISUAL) <= ks)  # plans asked all 6 visual templates
    rng = random.Random(2026)
    rng.shuffle(full)
    PATH.write_text(json.dumps({"dev": sorted(full[:40]), "heldout": sorted(full[40:140])}, indent=1), encoding="utf-8")
    print(f"{len(full)} plans have all 6 visual templates -> dev 40, heldout 100 -> {PATH}")
