"""Deterministic solver for Swiss Dwellings floor plans (PDF + DXF pairs).

Zero model calls. Rules were derived from the drawing conventions and validated on the preview set:

- doors      = DOOR layer polylines with 5 vertices (one outline per door; leaves/arcs are extra)
- windows    = WINDOW layer polylines / 3 (each window is drawn as 3 lines)
- apartments = distinct unit labels ("Whg. A", "App. B", ...)
- toilets    = FIXTURE 48-vertex ellipses WITHOUT a drain circle inside
- washbasins = FIXTURE 48-vertex ellipses WITH a drain circle inside
- bathtubs   = FIXTURE 69-vertex polylines
- showers    = FIXTURE 5-vertex polylines
- rooms/areas come from the ROOM_TEXT stacks: name / number / "12.34 m²"

Every answer returns PDF-space evidence boxes so the UI can highlight exactly what was counted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import ezdxf
import numpy as np
import pymupdf
from shapely.geometry import Point, Polygon

from plansight.types import Answer, Evidence

OUTDOOR = {"balkon", "balcon", "balcone", "loggia", "terrasse", "terrazza", "sitzplatz", "veranda"}
UNIT_RE = re.compile(r"^(Whg\.|App\.|Wohnung|Appartement|Appartamento)\s*([A-Z]{1,2})$")
NUM_RE = re.compile(r"^[A-Z]{0,2}\d+(\.\d+)*$")
AREA_RE = re.compile(r"^([\d.]+)\s*m²$")


@dataclass
class Room:
    number: str
    name: str | None
    area: float | None
    xy: tuple[float, float]  # DXF coords of the number label
    texts: list  # DXF TEXT entities forming the label stack
    outline: Polygon | None = None  # ROOM_OUTLINE polygon containing the number label
    area_source: str = "label"  # label | geometry


@dataclass
class Floor:
    pdf: str
    dxf: str
    rooms: list[Room]
    units: dict[str, tuple[Polygon | None, tuple[float, float]]]  # letter -> (outline, label xy)
    doors: list[Polygon]
    windows: list  # list of (bounds) groups
    toilets: list[Polygon]
    basins: list[Polygon]
    baths: list[Polygon]
    showers: list[Polygon]
    to_pdf: np.ndarray  # 2x3 affine DXF -> PDF points


# ---------------------------------------------------------------- loading

def _poly(e) -> Polygon | None:
    pts = [tuple(p) for p in e.get_points("xy")]
    if len(pts) < 3:
        return None
    return Polygon(pts)


def _fit_affine(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> np.ndarray:
    """Least-squares x' = a*x + b, y' = c*y + d (axis-aligned scale + flip + offset)."""
    s, d = np.array(src), np.array(dst)
    ax, bx = np.polyfit(s[:, 0], d[:, 0], 1)
    ay, by = np.polyfit(s[:, 1], d[:, 1], 1)
    return np.array([[ax, 0, bx], [0, ay, by]])


@lru_cache(maxsize=256)
def load_floor(base: str) -> Floor:
    """base = path without extension, e.g. data/swiss_dwellings/site1000_bldg2082_floor9385"""
    dxf_path, pdf_path = base + ".dxf", base + ".pdf"
    msp = ezdxf.readfile(dxf_path).modelspace()

    # --- room text stacks
    texts = list(msp.query('TEXT[layer=="ROOM_TEXT"]'))
    rooms: list[Room] = []
    unit_labels: dict[str, tuple[float, float]] = {}
    for t in texts:
        s = t.dxf.text.strip()
        m = UNIT_RE.match(s)
        if m:
            unit_labels[m.group(2)] = (t.dxf.insert.x, t.dxf.insert.y)
    for t in texts:
        s = t.dxf.text.strip()
        if not NUM_RE.match(s):
            continue
        x, y, h = t.dxf.insert.x, t.dxf.insert.y, t.dxf.height
        name = area = None
        stack = [t]
        for o in texts:
            if o is t or abs(o.dxf.insert.x - x) > 1e-3:
                continue
            dy = o.dxf.insert.y - y
            os_ = o.dxf.text.strip()
            if 0 < dy < 2.5 * h and not NUM_RE.match(os_) and not AREA_RE.match(os_) and not UNIT_RE.match(os_):
                name = os_
                stack.append(o)
            elif -2.5 * h < dy < 0 and AREA_RE.match(os_):
                area = float(AREA_RE.match(os_).group(1))
                stack.append(o)
        rooms.append(Room(number=s, name=name, area=area, xy=(x, y), texts=stack))

    # --- room outlines: smallest outline containing the number label. Some floors print no area
    # labels at all, so the outline's geometric area is the fallback (validated 130/130 within 2%).
    room_polys = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="ROOM_OUTLINE"]')) if p]
    for r in rooms:
        pt = Point(r.xy)
        cand = [p for p in room_polys if p.buffer(1e-6).contains(pt)]
        if cand:
            r.outline = min(cand, key=lambda p: p.area)
        if r.area is None and r.outline is not None:
            r.area = round(r.outline.area, 2)
            r.area_source = "geometry"

    # --- units: outline polygon containing the unit label
    outlines = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="UNIT_OUTLINE"]')) if p]
    units = {}
    for letter, xy in unit_labels.items():
        pt = Point(xy)
        poly = next((o for o in outlines if o.buffer(0.05).contains(pt)), None)
        units[letter] = (poly, xy)

    # --- doors / windows
    doors = [p for p in (_poly(e) for e in msp.query('LWPOLYLINE[layer=="DOOR"]') if len(e) == 5) if p]
    win_lines = list(msp.query('LWPOLYLINE[layer=="WINDOW"]'))
    windows = [win_lines[i:i + 3] for i in range(0, len(win_lines), 3)]

    # --- fixtures
    circles = [Point(c.dxf.center.x, c.dxf.center.y) for c in msp.query('CIRCLE[layer=="FIXTURE"]')]
    toilets, basins, baths, showers = [], [], [], []
    for e in msp.query('LWPOLYLINE[layer=="FIXTURE"]'):
        n = len(e)
        p = _poly(e)
        if p is None:
            continue
        if n == 48:
            (basins if any(p.contains(c) for c in circles) else toilets).append(p)
        elif n == 69:
            baths.append(p)
        elif n == 5:
            showers.append(p)

    # --- DXF -> PDF transform, fitted on room-number labels that appear in the PDF text
    page = pymupdf.open(pdf_path)[0]
    words = page.get_text("words")
    by_text: dict[str, list] = {}
    for w in words:
        by_text.setdefault(w[4], []).append(w)
    src, dst = [], []
    for r in rooms:
        ws = by_text.get(r.number, [])
        if len(ws) == 1:
            w = ws[0]
            src.append(r.xy)
            dst.append(((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
    to_pdf = _fit_affine(src, dst) if len(src) >= 3 else np.array([[1, 0, 0], [0, -1, 0]])

    return Floor(pdf_path, dxf_path, rooms, units, doors, windows, toilets, basins, baths, showers, to_pdf)


# ---------------------------------------------------------------- evidence helpers

def _bbox_pdf(fl: Floor, bounds: tuple[float, float, float, float], pad: float = 1.5):
    x0, y0, x1, y1 = bounds
    A = fl.to_pdf
    xs = [A[0, 0] * x + A[0, 2] for x in (x0, x1)]
    ys = [A[1, 1] * y + A[1, 2] for y in (y0, y1)]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _ev_geom(fl: Floor, geoms, label: str) -> list[Evidence]:
    out = []
    for i, g in enumerate(geoms, 1):
        b = g.bounds if hasattr(g, "bounds") else g
        out.append(Evidence(fl.pdf, 0, _bbox_pdf(fl, b), f"{label} {i}"))
    return out


def _ev_room(fl: Floor, r: Room) -> Evidence:
    if r.area_source == "geometry" and r.outline is not None:
        lab = f"{r.name or ''} {r.number} = {r.area} m² (from outline geometry)"
        return Evidence(fl.pdf, 0, _bbox_pdf(fl, r.outline.bounds, pad=0.5), lab.strip())
    h = max(t.dxf.height for t in r.texts)
    xs = [t.dxf.insert.x for t in r.texts]
    ys = [t.dxf.insert.y for t in r.texts]
    w = 0.35 * h * max(len(t.dxf.text) for t in r.texts)  # rough text width
    b = (min(xs) - w, min(ys) - h, max(xs) + w, max(ys) + h)
    lab = f"{r.name or ''} {r.number}" + (f" = {r.area} m²" if r.area is not None else "")
    return Evidence(fl.pdf, 0, _bbox_pdf(fl, b, pad=0.5), lab.strip())


def _window_bounds(group) -> tuple[float, float, float, float]:
    pts = [p for e in group for p in e.get_points("xy")]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _is_outdoor(r: Room) -> bool:
    return (r.name or "").strip().lower() in OUTDOOR


def _is_indoor_room(r: Room) -> bool:
    """Numbered, non-outdoor room. Unnamed numbered rooms DO count (small rooms whose name didn't fit);
    verified against ground truth: the gaps matched their outline areas exactly."""
    return not _is_outdoor(r)


# ---------------------------------------------------------------- query API

COUNT_KINDS = ("doors", "windows", "apartments", "toilets", "washbasins", "bathtubs", "showers")


def count(base: str, kind: str) -> Answer:
    fl = load_floor(base)
    if kind == "doors":
        ev = _ev_geom(fl, fl.doors, "door")
    elif kind == "windows":
        ev = _ev_geom(fl, [_window_bounds(g) for g in fl.windows], "window")
    elif kind == "apartments":
        ev = []
        for letter, (poly, xy) in sorted(fl.units.items()):
            b = poly.bounds if poly is not None else (xy[0] - 1, xy[1] - 1, xy[0] + 1, xy[1] + 1)
            ev.append(Evidence(fl.pdf, 0, _bbox_pdf(fl, b), f"apartment {letter}"))
    else:
        geoms = {"toilets": fl.toilets, "washbasins": fl.basins, "bathtubs": fl.baths, "showers": fl.showers}[kind]
        ev = _ev_geom(fl, geoms, kind.rstrip("s"))
    return Answer(len(ev), "count", ev, explanation=f"Counted {len(ev)} {kind} from the DXF {kind} geometry.")


def count_rooms_named(base: str, name: str) -> Answer:
    fl = load_floor(base)
    hits = [r for r in fl.rooms if (r.name or "").strip().lower() == name.strip().lower()]
    return Answer(len(hits), "count", [_ev_room(fl, r) for r in hits],
                  explanation=f"Found {len(hits)} room labels reading '{name}'.")


def room_area(base: str, number: str) -> Answer:
    fl = load_floor(base)
    r = next((r for r in fl.rooms if r.number == number), None)
    if r is None or r.area is None:
        return Answer(None, "m2", [], confidence=0.0, explanation=f"No area label found for room {number}.")
    return Answer(r.area, "m2", [_ev_room(fl, r)], explanation=f"Room {number} label reads {r.area} m².")


def _sum(fl: Floor, rooms: list[Room], what: str) -> Answer:
    rs = [r for r in rooms if r.area is not None]
    total = round(sum(r.area for r in rs), 2)
    expr = " + ".join(f"{r.area:g}" for r in rs)
    return Answer(total, "m2", [_ev_room(fl, r) for r in rs], explanation=f"{what}: {expr} = {total} m²")


def total_area_named(base: str, name: str) -> Answer:
    fl = load_floor(base)
    return _sum(fl, [r for r in fl.rooms if (r.name or "").lower() == name.lower()], f"Rooms labelled '{name}'")


def total_indoor_area(base: str) -> Answer:
    fl = load_floor(base)
    return _sum(fl, [r for r in fl.rooms if _is_indoor_room(r)], "All numbered indoor rooms")


def apartment_area(base: str, letter: str) -> Answer:
    fl = load_floor(base)
    if letter not in fl.units or fl.units[letter][0] is None:
        return Answer(None, "m2", [], confidence=0.0, explanation=f"Apartment {letter} outline not found.")
    poly = fl.units[letter][0].buffer(0.05)
    inside = [r for r in fl.rooms if poly.contains(Point(r.xy)) and _is_indoor_room(r)]
    ans = _sum(fl, inside, f"Apartment {letter} (excl. outdoor)")
    ans.evidence.insert(0, Evidence(fl.pdf, 0, _bbox_pdf(fl, fl.units[letter][0].bounds), f"apartment {letter}"))
    return ans


# ---------------------------------------------------------------- English question parser (router stand-in)

_COUNT_PATTERNS = [
    (r"how many apartments", "apartments"),
    (r"how many doors", "doors"),
    (r"how many windows", "windows"),
    (r"how many toilets", "toilets"),
    (r"how many washbasins", "washbasins"),
    (r"how many bathtubs", "bathtubs"),
    (r"how many showers", "showers"),
]


def parse_en(q: str) -> tuple[str, dict] | None:
    """Map an English Swiss-dataset question to (template, params). Other languages go through plansight.router."""
    ql = q.lower()
    for pat, kind in _COUNT_PATTERNS:
        if ql.startswith(pat):
            return "count", {"kind": kind}
    if m := re.match(r"how many rooms labelled '(.+)' are there", q, re.I):
        return "count_rooms_named", {"name": m.group(1)}
    if m := re.match(r"what is the net floor area of room (\S+) \(", q, re.I):
        return "room_area", {"number": m.group(1)}
    if m := re.match(r"what is the net floor area of apartment (\w+) in", q, re.I):
        return "apartment_area", {"letter": m.group(1)}
    if m := re.match(r"what is the total net area in m² of all rooms labelled '(.+)' on", q, re.I):
        return "total_area_named", {"name": m.group(1)}
    if ql.startswith("what is the total net floor area in m² of all numbered indoor rooms"):
        return "total_indoor_area", {}
    return None


DISPATCH = {
    "count": count,
    "count_rooms_named": count_rooms_named,
    "room_area": room_area,
    "apartment_area": apartment_area,
    "total_area_named": total_area_named,
    "total_indoor_area": total_indoor_area,
}


def answer(path: str, template: str, params: dict) -> Answer:
    base = str(Path(path).with_suffix("")).replace("\\", "/")
    return DISPATCH[template](base, **params)


class SwissSolver:
    """Solver-protocol wrapper (see plansight/solvers/base.py)."""

    name = "swiss"

    def can_handle(self, path: str) -> bool:
        return "swiss_dwellings/" in path.replace("\\", "/")

    def solve(self, path: str, question: str) -> Answer | None:
        from plansight.config import resolve

        from plansight.router import parse

        r = parse(path, question)  # any language: English parser -> template bank -> Gemma
        if not r.ok:
            return None
        ans = answer(str(resolve(path)), r.template, r.params)
        ans.cost_usd += r.cost_usd
        if r.method != "en":
            ans.explanation = f"{ans.explanation} [{r.describe()}]"
        return ans
