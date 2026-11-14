"""Template bank: per-language question patterns mined from the dataset, and the $0 deterministic matcher.

Mining relies on the dataset's structure: every non-English question directly follows its English sibling
(same drawing, same answer). We parse the English one, find its slot values verbatim in the translation,
and turn the translation into a regex with named groups. `python -m plansight.router.bank` rebuilds
plansight/router/bank.json from questions.jsonl.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from plansight.router.english import SLOT_KEYS, domain_of, parse_en
from plansight.router.lang import detect

BANK_PATH = Path(__file__).with_name("bank.json")
SEP = "␟"  # placeholder delimiter used while mining (never appears in questions)
WILD = "_"  # placeholder name for a quoted hint that isn't a solver param
_QUOTED = re.compile(
    r"«[^»]+»|„[^“”]+[“”]|“[^”]+”|\"[^\"]+\"|(?<=[\s(])'[^']+'(?=[\s),?.:;]|$)"
)


def norm(q: str) -> str:
    """Whitespace-normalise (incl. no-break spaces) so typed questions match mined ones."""
    return re.sub(r"[\s  ]+", " ", q).strip()


def pairs(rows: list[dict]):
    """Yield (domain, english_row, route, translated_row) for every translation in dataset order."""
    last = None
    for r in rows:
        dom = domain_of(r["path"])
        if dom is None:
            continue
        route = parse_en(dom, r["question"])
        if route is not None:
            last = (dom, r, route)
            continue
        if last and last[1]["path"] == r["path"] and last[1]["answer"] == r["answer"]:
            yield last[0], last[1], last[2], r


def _ph(name: str) -> str:
    return f"{SEP}{name}{SEP}"


def _templatize(text: str, slots: dict[str, str]) -> str | None:
    """Replace each slot value by a placeholder (longest value first). None if a value isn't in the text."""
    for key, val in sorted(slots.items(), key=lambda kv: -len(kv[1])):
        if len(val) <= 2:  # short values (apartment letters): whole-word occurrence only
            m = list(re.finditer(rf"(?<!\w){re.escape(val)}(?!\w)", text))
        else:
            m = list(re.finditer(re.escape(val), text))
        if not m:
            return None
        text = text[: m[0].start()] + _ph(key) + text[m[0].end():]
    # remaining quoted values are hints that aren't solver params (e.g. the room name in "room 7.01 ('Balkon')"):
    # wildcard them so the pattern generalises to unseen names
    return _QUOTED.sub(lambda m: m[0] if SEP in m[0] else _ph(WILD), text)


def _to_regex(t: str) -> str:
    parts = t.split(SEP)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(re.escape(p))
        else:
            out.append("(?:.+?)" if p == WILD else f"(?P<{p}>.+?)")
    return "^" + "".join(out) + "$"


def _literal_len(rx: str) -> int:
    return len(re.sub(r"\(\?(?:P<\w+>|:)\.\+\?\)", "", rx))


def mine(rows: list[dict], keep=lambda path: True) -> tuple[list[dict], Counter]:
    """Bank entries from (EN, translation) pairs whose path passes `keep`. Returns (entries, misses)."""
    counts: Counter = Counter()
    meta: dict[tuple, dict] = {}
    misses: Counter = Counter()
    for dom, en, (template, params), tr in pairs(rows):
        if not keep(tr["path"]):
            continue
        slots = {k: v for k, v in params.items() if k in SLOT_KEYS and v is not None}
        fixed = {k: v for k, v in params.items() if k not in slots}
        t = _templatize(norm(tr["question"]), {k: norm(v) for k, v in slots.items()})
        if t is None:
            misses[(dom, template)] += 1
            continue
        key = (dom, _to_regex(t), template, json.dumps(fixed, sort_keys=True))
        counts[key] += 1
        meta.setdefault(key, {"example": tr["question"], "lang": detect(tr["question"])})
    entries = [{"domain": d, "regex": rx, "template": t, "fixed": json.loads(f), "n": n, **meta[(d, rx, t, f)]}
               for (d, rx, t, f), n in counts.items()]
    # most specific first (more literal text), then most frequent
    entries.sort(key=lambda e: (-_literal_len(e["regex"]), -e["n"]))
    return entries, misses


@dataclass
class Match:
    template: str
    params: dict
    lang: str


class Bank:
    def __init__(self, entries: list[dict]):
        self.by_domain: dict[str, list[tuple[re.Pattern, dict]]] = defaultdict(list)
        for e in entries:
            self.by_domain[e["domain"]].append((re.compile(e["regex"], re.I | re.S), e))

    def match(self, domain: str, question: str) -> Match | None:
        q = norm(question)
        for rx, e in self.by_domain.get(domain, []):
            if m := rx.match(q):
                return Match(e["template"], {**e["fixed"], **m.groupdict()}, e["lang"])
        return None

    @property
    def size(self) -> int:
        return sum(map(len, self.by_domain.values()))


@lru_cache(maxsize=1)
def default_bank() -> Bank:
    return Bank(json.loads(BANK_PATH.read_text(encoding="utf-8")) if BANK_PATH.exists() else [])


def load_rows() -> list[dict]:
    from plansight.config import QUESTIONS

    with QUESTIONS.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    entries, misses = mine(load_rows())
    BANK_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    by = Counter((e["domain"], e["lang"]) for e in entries)
    print(f"{len(entries)} patterns -> {BANK_PATH}")
    for (d, lang), n in sorted(by.items()):
        print(f"  {d:9s} {lang:6s} {n}")
    print("slot values not found verbatim in the translation:", dict(misses) or "none")
