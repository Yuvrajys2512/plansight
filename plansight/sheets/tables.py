"""Ruled tables (schedules) from vector PDF sheets: grid lines -> cells -> words, every cell with its bbox.

Works in the *displayed* page orientation (page rotation removed), so bboxes line up with the rendered sheet.
Robust to the common CAD export quirks: grids drawn as hundreds of short stroked segments, merged header cells,
text that spills a little over a line.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import pymupdf

TOL = 1.5        # pt: coordinates closer than this are the same line
MIN_SIDE = 40    # pt: smallest table side we keep


@dataclass
class Cell:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass
class Table:
    id: str
    bbox: tuple[float, float, float, float]
    title: str
    rows: list[list[Cell]] = field(default_factory=list)  # rows[r][c] (ruled tables: same length per row)

    def grid(self) -> list[list[str]]:
        return [[c.text for c in r] for r in self.rows]


def _segments(page):
    hs, vs = [], []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                (x0, y0), (x1, y1) = (it[1].x, it[1].y), (it[2].x, it[2].y)
            elif it[0] == "re":
                r = it[1]
                if r.width < 2.5:
                    x0 = x1 = (r.x0 + r.x1) / 2; y0, y1 = r.y0, r.y1
                elif r.height < 2.5:
                    y0 = y1 = (r.y0 + r.y1) / 2; x0, x1 = r.x0, r.x1
                else:  # a real rectangle: its four sides
                    hs += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]; vs += [(r.y0, r.y1, r.x0), (r.y0, r.y1, r.x1)]
                    continue
            else:
                continue
            if abs(y0 - y1) < 0.5 and abs(x1 - x0) > 3:
                hs.append((min(x0, x1), max(x0, x1), y0))
            elif abs(x0 - x1) < 0.5 and abs(y1 - y0) > 3:
                vs.append((min(y0, y1), max(y0, y1), x0))
    return hs, vs


def _components(hs, vs):
    """Group touching horizontal/vertical segments into grids (union-find over intersections)."""
    n_h = len(hs)
    parent = list(range(n_h + len(vs)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    vs_sorted = sorted(range(len(vs)), key=lambda j: vs[j][2])
    xs = [vs[j][2] for j in vs_sorted]
    import bisect

    for i, (x0, x1, y) in enumerate(hs):
        lo, hi = bisect.bisect_left(xs, x0 - TOL), bisect.bisect_right(xs, x1 + TOL)
        for k in range(lo, hi):
            j = vs_sorted[k]
            y0, y1, _ = vs[j]
            if y0 - TOL <= y <= y1 + TOL:
                union(i, n_h + j)
    groups: dict[int, tuple[list, list]] = {}
    for i in range(n_h):
        groups.setdefault(find(i), ([], []))[0].append(hs[i])
    for j in range(len(vs)):
        groups.setdefault(find(n_h + j), ([], []))[1].append(vs[j])
    return [g for g in groups.values() if len(g[0]) >= 3 and len(g[1]) >= 3]


def _cluster(vals, tol=TOL):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _words_in(words, x0, y0, x1, y1):
    ws = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    ws.sort(key=lambda w: (round(w[1] / 3), w[0]))
    return " ".join(w[4] for w in ws)


def _page(path: str, page_no: int = 0):
    doc = pymupdf.open(path)
    page = doc[page_no]
    page.remove_rotation()
    return doc, page


def _merge(segs):
    """Merge collinear, touching segments (a, b, c) = (start, end, fixed coordinate) into long lines."""
    out = []
    for a, b, c in sorted(segs, key=lambda t: (round(t[2] / TOL), t[0])):
        if out and abs(out[-1][2] - c) <= TOL and a <= out[-1][1] + TOL:
            out[-1] = (out[-1][0], max(out[-1][1], b), out[-1][2])
        else:
            out.append((a, b, c))
    return out


def _text_lines(words, X0, Y0, X1, Y1):
    ws, seen = [], set()
    for w in words:  # drop duplicate overlapping text objects (common in CAD exports)
        if X0 <= (w[0] + w[2]) / 2 <= X1 and Y0 <= (w[1] + w[3]) / 2 <= Y1:
            key = (w[4], round(w[0]), round(w[1]))
            if key not in seen:
                seen.add(key); ws.append(w)
    ws.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        cy, h = (w[1] + w[3]) / 2, w[3] - w[1]
        if lines and abs(lines[-1]["cy"] - cy) <= 0.45 * h:
            L = lines[-1]; L["w"].append(w); L["cy"] = (L["cy"] * (len(L["w"]) - 1) + cy) / len(L["w"])
        else:
            lines.append({"cy": cy, "w": [w]})
    for L in lines:
        L["w"].sort(key=lambda w: w[0])
        L["y0"] = min(w[1] for w in L["w"]); L["y1"] = max(w[3] for w in L["w"])
    return lines


def _gap_cells(ws, X0, X1):
    """Split one text line into cells at gaps wider than ~1.2 character heights."""
    cells, cur = [], [ws[0]]
    for a, b in zip(ws, ws[1:]):
        if b[0] - a[2] > 1.2 * (a[3] - a[1]):
            cells.append(cur); cur = []
        cur.append(b)
    cells.append(cur)
    return [Cell(" ".join(w[4] for w in c), (c[0][0], min(w[1] for w in c), c[-1][2], max(w[3] for w in c)))
            for c in cells]


@lru_cache(maxsize=32)
def extract(path: str, page_no: int = 0) -> tuple[Table, ...]:
    doc, page = _page(path, page_no)
    words = page.get_text("words")
    hs, vs = _segments(page)
    hs, vs = _merge(hs), _merge(vs)
    tables = []
    for gh, gv in _components(hs, vs):
        X0 = min(min(h[0] for h in gh), min(v[2] for v in gv)); X1 = max(max(h[1] for h in gh), max(v[2] for v in gv))
        Y0 = min(min(v[0] for v in gv), min(h[2] for h in gh)); Y1 = max(max(v[1] for v in gv), max(h[2] for h in gh))
        if X1 - X0 < MIN_SIDE or Y1 - Y0 < MIN_SIDE:
            continue
        lines = _text_lines(words, X0, Y0, X1, Y1)
        if len(lines) < 2:
            continue
        # grid rows: merge text lines that sit between the same pair of horizontal rules (multi-line cells)
        rules = _cluster([h[2] for h in gh if h[1] - h[0] > 0.5 * (X1 - X0)] + [Y0, Y1])
        bands = [next((i for i, (a, b) in enumerate(zip(rules, rules[1:])) if a - 1 <= L["cy"] <= b + 1), None)
                 for L in lines]
        from collections import Counter

        per_band = Counter(b for b in bands if b is not None)
        multi = sum(1 for n in per_band.values() if n > 1) / max(1, len(per_band))
        merge = len(rules) > 0.5 * len(lines) and multi > 0.25  # real multi-line cells, not a few missing rules
        groups = []
        for L, band in zip(lines, bands):
            if merge and groups and band is not None and groups[-1]["band"] == band:
                groups[-1]["w"] += L["w"]; groups[-1]["y1"] = L["y1"]
            else:
                groups.append({"band": band, "w": list(L["w"]), "y0": L["y0"], "y1": L["y1"]})
        # columns: vertical rules that span most of the table body, else gaps in the text
        cols = _cluster([v[2] for v in gv if v[1] - v[0] > 0.4 * (Y1 - Y0)] + [X0, X1])
        rows = []
        for g in groups:
            if len(cols) >= 4:
                cells = []
                for c0, c1 in zip(cols, cols[1:]):
                    ws = sorted([w for w in g["w"] if c0 <= (w[0] + w[2]) / 2 <= c1], key=lambda w: (round(w[1] / 3), w[0]))
                    cells.append(Cell(" ".join(w[4] for w in ws), (c0, g["y0"], c1, g["y1"])))
            else:
                cells = _gap_cells(sorted(g["w"], key=lambda w: w[0]), X0, X1)
            rows.append(cells)
        title = _words_in(words, X0, Y0 - 18, X1, Y0 + 1).strip() or " ".join(c.text for c in rows[0] if c.text)
        tables.append(Table("", (X0, Y0, X1, Y1), title[:80], rows))
    tables.sort(key=lambda t: (round(t.bbox[1] / 200), t.bbox[0]))
    for i, t in enumerate(tables):
        t.id = f"T{i + 1}"
    doc.close()
    return tuple(tables)


def page_size(path: str, page_no: int = 0) -> tuple[float, float]:
    doc, page = _page(path, page_no)
    r = page.rect
    doc.close()
    return r.width, r.height
