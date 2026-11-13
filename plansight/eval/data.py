"""Question loading, language tagging, and deterministic stratified sampling."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from plansight.config import QUESTIONS, source_of

_LANG_CUES = {
    "fi": ("kuinka monta", "montako", "pohjapiir", "huoneessa", "kerroksessa", "pinta-ala", "mikä on"),
    "de": ("wie viele", "anzahl der", "grundriss", "geschoss", "zimmer", "fläche", "wie groß"),
    "fr": ("combien de", "plan d'étage", "surface", "quelle est", "pièces"),
    "it": ("quanti", "quante", "planimetria", "superficie", "appartamento"),
    "da": ("hvor mange", "plantegning", "etage", "værelser", "areal", "hvad er"),
    "et": ("mitu", "korruse", "ruumide", "pindala", "milline on", "korter"),
}


def detect_language(question: str) -> str:
    q = question.casefold()
    scores = {lang: sum(cue in q for cue in cues) for lang, cues in _LANG_CUES.items()}
    lang, hits = max(scores.items(), key=lambda pair: pair[1])
    if hits:
        return lang
    if q.startswith(("what ", "how ", "which ", "could you ", "can you ", "provide ", "list ", "describe ")):
        return "en"
    if any(cue in q for cue in ("how many", "what is", "which", "show", "are there", "floor plan")):
        return "en"
    return "other"


def load_questions(path: Path | None = None) -> list[dict]:
    """Load questions from plansight.config.QUESTIONS and add source/lang tags."""
    rows = []
    with (path or QUESTIONS).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                row["source"] = source_of(row["path"])
                row["lang"] = detect_language(row.get("question", ""))
                rows.append(row)
    return rows


def _allocate(groups: dict[tuple, list[dict]], quota: int) -> dict[tuple, int]:
    total = sum(map(len, groups.values()))
    target = min(quota, total)
    exact = {key: target * len(rows) / total for key, rows in groups.items()}
    allocation = {key: int(value) for key, value in exact.items()}
    remaining = target - sum(allocation.values())
    order = sorted(groups, key=lambda key: (-(exact[key] % 1), repr(key)))
    for key in order:
        if remaining and allocation[key] < len(groups[key]):
            allocation[key] += 1
            remaining -= 1
    while remaining:
        for key in order:
            if allocation[key] < len(groups[key]):
                allocation[key] += 1
                remaining -= 1
                if not remaining:
                    break
    return allocation


def sample_questions(rows: Iterable[dict], *, per_source: int | None = None, seed: int = 0,
                     sources: set[str] | None = None, langs: set[str] | None = None,
                     types: set[str] | None = None) -> list[dict]:
    """Cap each source while allocating samples proportionally across type/lang strata."""
    filtered = [r for r in rows if (not sources or r["source"] in sources)
                and (not langs or r["lang"] in langs)
                and (not types or r.get("type", "other") in types)]
    by_source: dict[str, list[dict]] = defaultdict(list)
    for row in filtered:
        by_source[row["source"]].append(row)
    rng = random.Random(seed)
    result = []
    for source in sorted(by_source):
        strata: dict[tuple, list[dict]] = defaultdict(list)
        for row in by_source[source]:
            strata[(row.get("type", "other"), row["lang"])].append(row)
        for values in strata.values():
            rng.shuffle(values)
        if per_source is None or len(by_source[source]) <= per_source:
            result.extend(row for key in sorted(strata) for row in strata[key])
        else:
            counts = _allocate(strata, per_source)
            result.extend(row for key in sorted(strata) for row in strata[key][:counts[key]])
    rng.shuffle(result)
    return result
