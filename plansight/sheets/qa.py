"""Questions about schedule sheets (vector PDFs): Nemotron writes a tiny program over the extracted tables, we run it.

Why a program: counting 256 doors or summing 29 room areas "in the head" is where LLMs slip. The model only decides
*which* rows and columns matter; Python does the arithmetic, and the rows it touched become evidence boxes.

    tables  = plansight.sheets.tables.extract(pdf)        # cells with bboxes
    context = relevant tables (keyword overlap) + other sheet text, compact
    code    = Nemotron 3.5 Super: def answer(T, TEXT) -> {"answer": ..., "rows": [[table_id, row_idx], ...]}
    result  = run code in a restricted namespace (no imports/IO), rows -> Evidence boxes
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass

from plansight.sheets.tables import Table, extract
from plansight.types import Answer, Evidence

MAX_CHARS = 26000  # context budget (~8k tokens): the server runs a 16k window
STOP = {"the", "of", "on", "in", "a", "an", "is", "are", "how", "many", "what", "which", "and", "or", "for", "to",
        "sheet", "drawings", "listed", "schedule", "does", "do", "with", "by", "that", "this", "total", "all"}

SYSTEM = """You answer questions about construction drawing sheets by writing a small Python function.
You get the sheet's tables (already extracted, one row per line: `r<idx> | cell | cell ...`) and other text on the sheet.

Write exactly one function:

def answer(T, TEXT):
    # T: dict table_id -> list of rows; each row is a list of cell strings (header rows included, as shown)
    # TEXT: list of the other text lines on the sheet
    ...
    return {"answer": <number or short string>, "rows": [[table_id, row_index], ...], "note": "<one line>"}

Rules:
- Use Python for every count/sum/lookup; never hard-code the answer.
- Skip header/title rows; data rows are the ones whose key column (e.g. a door/room number) is filled.
- Match codes with care: strip spaces, compare case-insensitively; a cell may hold several values ("F2 & F3").
- Parse numbers from cells like "29690 SF", "3' - 0\\"" yourself (regex is available as `re`).
- "rows" must list exactly the data rows the answer depends on (they are highlighted for the human checker).
- Answer with the unit/format the question implies (e.g. 5'-10 3/8"); for "what kind" questions combine the code
  with its meaning from a legend/notes table or TEXT.
Return only the code in one ```python block."""


@dataclass
class SheetResult:
    answer: object
    rows: list
    note: str
    code: str
    cost_usd: float
    tables_used: list


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9][a-z0-9.\-/]*", s.lower()) if t not in STOP and len(t) > 1}


def _render(t: Table, limit: int = 60) -> str:
    lines = [f"## {t.id}: {t.title!r} ({len(t.rows)} rows)"]
    for i, r in enumerate(t.rows):
        lines.append(f"r{i} | " + " | ".join(c.text[:limit] for c in r))
    return "\n".join(lines)


def context(tables: tuple[Table, ...], other: list[str], question: str) -> tuple[str, list[str]]:
    q = _tokens(question)
    scored = []
    for t in tables:
        if len(t.rows) < 2:
            continue
        body = _tokens(t.title + " " + " ".join(c.text for r in t.rows for c in r))
        scored.append((len(q & body) + 3 * len(q & _tokens(t.title)), len(t.rows), t))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    parts, used, size = [], [], 0
    for score, _, t in scored:
        txt = _render(t)
        if score == 0 and used:
            break
        if size + len(txt) > MAX_CHARS and used:
            continue
        parts.append(txt); used.append(t.id); size += len(txt)
    rest = MAX_CHARS - size
    other_txt = "\n".join(other)[: max(0, min(rest, 6000))]
    return "\n\n".join(parts) + "\n\n## TEXT (other text on the sheet)\n" + other_txt, used


def _other_text(path: str, tables) -> list[str]:
    import pymupdf

    doc = pymupdf.open(path); page = doc[0]; page.remove_rotation()
    inside = lambda b: any(t.bbox[0] <= (b[0] + b[2]) / 2 <= t.bbox[2] and t.bbox[1] <= (b[1] + b[3]) / 2 <= t.bbox[3]
                           for t in tables)
    lines = []
    for b in page.get_text("blocks"):
        if b[6] == 0 and not inside(b) and (s := " ".join(b[4].split())):
            lines.append(s)
    doc.close()
    return lines


SAFE = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
        for k in ("len", "sum", "int", "float", "str", "sorted", "set", "list", "dict", "tuple", "min", "max", "any",
                  "all", "enumerate", "range", "round", "zip", "abs", "isinstance", "bool", "print", "map", "filter",
                  "reversed", "ValueError", "Exception", "KeyError", "IndexError", "TypeError")}


def _safe_import(name, *args, **kwargs):
    if name in ("re", "math"):
        return __import__(name)
    raise ImportError(f"import of {name!r} is not allowed")


def run_code(code: str, T: dict, TEXT: list[str], timeout: float = 5.0) -> dict:
    """Execute the model's `answer` in a namespace without IO or other imports (only re, math); bounded time."""
    bad = re.search(r"\b(open|exec|eval|globals|locals|compile|getattr|setattr|delattr|vars|input)\s*\(|__\w+__", code)
    if bad:
        raise ValueError(f"disallowed construct in generated code: {bad.group(0)}")
    ns: dict = {"__builtins__": {**SAFE, "__import__": _safe_import}, "re": re, "math": __import__("math")}
    exec(code, ns)  # noqa: S102 - restricted namespace, no IO builtins
    out: dict = {}

    def target():
        out["r"] = ns["answer"](T, TEXT)

    th = threading.Thread(target=target, daemon=True); th.start(); th.join(timeout)
    if "r" not in out:
        raise TimeoutError("generated code timed out")
    return out["r"]


def ask(path: str, question: str, retries: int = 2) -> SheetResult:
    from plansight.vlm import nemotron

    tables = extract(path)
    other = _other_text(path, tables)
    ctx, used = context(tables, other, question)
    T = {t.id: [[c.text for c in r] for r in t.rows] for t in tables}
    prompt = f"{ctx}\n\nQuestion: {question}"
    cost, err = 0.0, ""
    for attempt in range(retries + 1):
        p = prompt if not err else f"{prompt}\n\nYour previous code failed with: {err}\nFix it."
        r = nemotron.ask(p, system=SYSTEM, think=True, max_tokens=4000, temperature=0.0 if attempt == 0 else 0.3)
        cost += r.cost_usd
        m = re.search(r"```(?:python)?\n(.*?)```", r.text, re.S)
        code = m.group(1) if m else r.text
        try:
            res = run_code(code, T, other)
            rows = [[str(a), int(b)] for a, b in res.get("rows", []) if str(a) in T and 0 <= int(b) < len(T[str(a)])]
            return SheetResult(res.get("answer"), rows, str(res.get("note", "")), code, cost, used)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
    raise RuntimeError(f"sheet QA failed: {err}")


def evidence(path: str, rel_path: str, rows: list) -> list[Evidence]:
    tables = {t.id: t for t in extract(path)}
    ev = []
    for tid, i in rows[:200]:
        cells = tables[tid].rows[i]
        xs0 = [c.bbox[0] for c in cells]; ys0 = [c.bbox[1] for c in cells]
        xs1 = [c.bbox[2] for c in cells]; ys1 = [c.bbox[3] for c in cells]
        txt = " | ".join(c.text for c in cells if c.text)[:60]
        ev.append(Evidence(file=rel_path, page=0, bbox=(min(xs0), min(ys0), max(xs1), max(ys1)), label=f"{tid} r{i}: {txt}"))
    return ev


class SheetSolver:
    """Vector PDF sheets with schedules (opening_design and any similar sheet)."""
    name = "sheets"

    def can_handle(self, path: str) -> bool:
        return path.lower().endswith(".pdf") and "/opening_design/" in path.replace("\\", "/")

    def solve(self, path: str, question: str) -> Answer | None:
        from plansight.config import resolve

        full = str(resolve(path))
        try:
            res = ask(full, question)
        except Exception:  # noqa: BLE001
            return None
        if res.answer in (None, ""):
            return None
        ev = evidence(full, path, res.rows)
        val = res.answer
        return Answer(value=val, unit=None, evidence=ev, method="llm+code", cost_usd=res.cost_usd,
                      confidence=0.85 if ev else 0.5,
                      explanation=(f"Nemotron 3.5 Super wrote a program over the sheet's extracted schedules "
                                   f"({', '.join(res.tables_used)}); it used {len(res.rows)} row(s). {res.note}").strip())
