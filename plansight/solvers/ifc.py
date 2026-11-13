"""Deterministic solver for IFC building models (ifc_models source). Zero model calls.

Questions come either on the model itself (`<model>.ifc`) or on a floor plan rendered from it
(`<model>_plan-NN-<level>.pdf`). Either way we answer from the IFC:

- counts      = IFC entities by class (incl. subtypes), per model or per storey (spatial containment / aggregation)
- room area   = NetFloorArea from a `BaseQuantities` set if present, else the footprint of the IfcSpace body
                (mesh projected to plan, union of triangles). Revit's own stored areas do NOT match the dataset.
- wall length / side area / volume, slab volume = `BaseQuantities` (ArchiCAD-style, unit-scaled) if present,
                else geometry (mesh volume). Side area and length: any quantity set. (Validated on all 84 files:
                Revit `Qto_*` volumes disagree with the dataset, mesh volumes match exactly. Known miss: Warmond
                side areas, where the dataset used total mesh surface area; 4 questions, left alone.)
- only top-level elements count: a stair whose risers are modelled as child IfcStairs is one stair
- evidence    = the counted elements' outlines on the rendered floor plan. The SVG twin of each plan tags every
                element with its GlobalId; SVG mm map linearly to PDF points.

Facts per model are computed once and cached in cache/ifc/<model>.json (this is the batch job we run on Verda).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from plansight.config import REPO, resolve
from plansight.types import Answer, Evidence

CACHE = REPO / "cache" / "ifc"
CACHE_VERSION = 5
MM_TO_PT = 72 / 25.4

# question noun -> (IFC classes, IFC2X3 FlowTerminal type class used instead)
CLASSES = {
    "doors": (["IfcDoor"], None),
    "windows": (["IfcWindow"], None),
    "rooms": (["IfcSpace"], None),
    "walls": (["IfcWall"], None),
    "beams": (["IfcBeam"], None),
    "columns": (["IfcColumn"], None),
    "stairs": (["IfcStair"], None),
    "slabs": (["IfcSlab"], None),
    "sanitary": (["IfcSanitaryTerminal"], "IfcSanitaryTerminalType"),
    "lights": (["IfcLightFixture"], "IfcLightFixtureType"),
}
NOUNS = {
    "doors": "doors", "windows": "windows", "rooms (spaces)": "rooms", "walls": "walls", "beams": "beams",
    "columns": "columns", "stairs": "stairs", "sanitary fixtures": "sanitary", "light fixtures": "lights",
}


# ----------------------------------------------------------------------------------------------- paths
def model_of(path: str) -> str:
    """'data/ifc_models/<model>_plan-03-grundplan.pdf' or '<model>.ifc' -> '<model>'."""
    return Path(path).stem.split("_plan-")[0]


def ifc_path(model: str) -> Path:
    return resolve(f"data/ifc_models/{model}.ifc")


# ----------------------------------------------------------------------------------------------- facts
def _storey_of(e) -> str | None:
    import ifcopenshell.util.element as ue

    seen = 0
    while e is not None and seen < 20:
        if e.is_a("IfcBuildingStorey"):
            return e.Name
        e = ue.get_aggregate(e) or ue.get_container(e)
        seen += 1
    return None


def _quantities(e, scales: dict[str, float], only: str | None = None) -> dict[str, float]:
    """IfcElementQuantity values on the element, SI-scaled, first occurrence wins (BaseQuantities first).
    `only` restricts to quantity sets with exactly that name."""
    out: dict[str, float] = {}
    rels = getattr(e, "IsDefinedBy", None) or []
    qsets = [r.RelatingPropertyDefinition for r in rels if r.is_a("IfcRelDefinesByProperties")]
    qsets = [q for q in qsets if q.is_a("IfcElementQuantity") and (only is None or q.Name == only)]
    qsets.sort(key=lambda q: 0 if (q.Name or "").startswith(("BaseQuantities", "Qto_")) else 1)
    for qs in qsets:
        for q in qs.Quantities or []:
            if q.Name in out:
                continue
            if q.is_a("IfcQuantityLength"):
                out[q.Name] = q.LengthValue * scales["len"]
            elif q.is_a("IfcQuantityArea"):
                out[q.Name] = q.AreaValue * scales["area"]
            elif q.is_a("IfcQuantityVolume"):
                out[q.Name] = q.VolumeValue * scales["vol"]
    return out


def _scales(f) -> dict[str, float]:
    import ifcopenshell.util.unit as uu

    s = {"len": uu.calculate_unit_scale(f, "LENGTHUNIT")}
    for k, ut in (("area", "AREAUNIT"), ("vol", "VOLUMEUNIT")):
        try:
            s[k] = uu.calculate_unit_scale(f, ut)
        except Exception:
            s[k] = s["len"] ** (2 if k == "area" else 3)
    return s


def _footprints(f, elements) -> dict[int, tuple[float, float]]:
    """id -> (plan footprint m², mesh volume m³, mesh surface area m²) for the elements, via world-coord meshes."""
    import ifcopenshell.geom as G
    import numpy as np
    from shapely import union_all
    from shapely.geometry import Polygon

    st = G.settings()
    st.set("use-world-coords", True)
    out = {}
    for e in elements:
        try:
            sh = G.create_shape(st, e)
        except Exception:
            continue
        v = np.array(sh.geometry.verts).reshape(-1, 3)
        tri = np.array(sh.geometry.faces).reshape(-1, 3)
        if not len(tri):
            continue
        p = v[tri]  # (n,3,3)
        a, b, c = p[:, 0], p[:, 1], p[:, 2]
        area2d = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
        polys = [Polygon(t[:, :2]) for t, ar in zip(p, area2d) if ar > 1e-9]
        fp = union_all(polys).area if polys else 0.0
        vol = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6)
        surf = float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
        out[e.id()] = (fp, vol, surf)
    return out


def _plans(model: str) -> dict[str, dict]:
    """PDF filename -> {pdf, storey, boxes: {element GlobalId: PDF-point bbox}} for every rendered plan.

    A plan SVG also shows elements of neighbouring storeys (section cut), so the plan's own storey is the
    majority storey of its IfcSpace groups (falling back to all groups)."""
    from collections import Counter

    import ifcopenshell.guid

    plans = {}
    for svg in sorted(resolve("data/ifc_models").glob(f"{model}_plan-*.svg")):
        txt = svg.read_text(encoding="utf-8", errors="replace")
        vb = re.search(r'viewBox="([-\d.]+) ([-\d.]+)', txt)
        if not vb:
            continue
        votes = Counter(re.findall(r'id="storey-([0-9a-f-]{36})-product[^"]*" class="IfcSpace"', txt)) or \
            Counter(re.findall(r'id="storey-([0-9a-f-]{36})-product', txt))
        storey = ifcopenshell.guid.compress(votes.most_common(1)[0][0].replace("-", "")) if votes else None
        ox, oy = float(vb.group(1)), float(vb.group(2))

        def pt(x: float, y: float) -> tuple[float, float]:
            return round((x - ox) * MM_TO_PT, 2), round((y - oy) * MM_TO_PT, 2)

        boxes: dict[str, list[float]] = {}
        polys: dict[str, list[tuple[float, float]]] = {}
        heads = list(re.finditer(r'<g [^>]*class="(\w+)"[^>]*data-guid="([^"]+)"[^>]*>', txt))
        for i, h in enumerate(heads):  # an element's content runs until the next element group (catches nested <g>)
            body = txt[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(txt)]
            paths = [_path_points(d) for d in re.findall(r' d="([^"]+)"', body)]
            pts = [p for path in paths for p in path]
            if not pts:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            bb = [*pt(min(xs), min(ys)), *pt(max(xs), max(ys))]
            guid = h.group(2)
            old = boxes.get(guid)
            boxes[guid] = bb if not old else [min(old[0], bb[0]), min(old[1], bb[1]), max(old[2], bb[2]), max(old[3], bb[3])]
            if h.group(1) == "IfcSpace" and guid not in polys:
                polys[guid] = [pt(x, y) for x, y in max(paths, key=len)]
        plans[f"{svg.stem}.pdf"] = {"pdf": f"data/ifc_models/{svg.stem}.pdf", "storey": storey,
                                    "boxes": boxes, "polys": polys}
    return plans


def _path_points(d: str) -> list[tuple[float, float]]:
    """Vertices of an SVG path made of M/L/A/Z commands (what IfcConvert writes). Arc radii/flags are skipped."""
    toks = re.findall(r"[MLAZmlaz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    out, cmd, i = [], "M", 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd, i = t, i + 1
            continue
        if cmd in "MLml":
            out.append((float(toks[i]), float(toks[i + 1])))
            i += 2
        elif cmd in "Aa":  # rx ry rot large sweep x y
            out.append((float(toks[i + 5]), float(toks[i + 6])))
            i += 7
        else:
            i += 1
    return out


def build_facts(model: str) -> dict:
    """Everything the solver needs about one model. Slow (geometry), so cached to disk."""
    import ifcopenshell

    f = ifcopenshell.open(str(ifc_path(model)))
    scales = _scales(f)
    storeys = {s.GlobalId: s.Name for s in f.by_type("IfcBuildingStorey")}
    elems = []

    import ifcopenshell.util.element as ue

    def add(e, kind):
        parent = ue.get_aggregate(e)
        if parent is not None and any(parent.is_a(c) for c in CLASSES[kind][0]):
            return  # part of an element of the same kind (e.g. risers modelled as IfcStair inside a stair)
        elems.append({"id": e.id(), "guid": e.GlobalId, "kind": kind, "cls": e.is_a(), "storey": _storey_of(e),
                      "name": e.Name, "longname": getattr(e, "LongName", None),
                      "q": _quantities(e, scales), "qb": _quantities(e, scales, only="BaseQuantities")})

    for kind, (classes, ftype) in CLASSES.items():
        seen = set()
        for c in classes:
            try:
                for e in f.by_type(c):
                    if e.id() not in seen:
                        seen.add(e.id()); add(e, kind)
            except RuntimeError:  # class not in this schema (e.g. IfcSanitaryTerminal in IFC2X3)
                pass
        if ftype and f.schema == "IFC2X3":
            for e in f.by_type("IfcFlowTerminal"):
                t = ue.get_type(e)
                if t is not None and t.is_a(ftype) and e.id() not in seen:
                    seen.add(e.id()); add(e, kind)

    geo_ids = {x["id"] for x in elems if x["kind"] in ("rooms", "walls", "slabs")}
    geo = _footprints(f, [f.by_id(i) for i in geo_ids])
    for x in elems:
        if x["id"] in geo:
            x["footprint"], x["mesh_volume"], x["mesh_area"] = geo[x["id"]]

    projects = [p.Name or p.LongName for p in f.by_type("IfcProject")]
    return {"v": CACHE_VERSION, "model": model, "schema": f.schema, "projects": projects,
            "storeys": storeys, "elements": elems, "plans": _plans(model)}


@lru_cache(maxsize=16)
def facts(model: str) -> dict:
    p = CACHE / f"{model}.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("v") == CACHE_VERSION:
            return d
    d = build_facts(model)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")
    return d


# ----------------------------------------------------------------------------------------------- answers
def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().casefold()


def room_label(x: dict) -> str:
    ln, n = x.get("longname"), x.get("name")
    return f"{ln} ({n})" if ln and n else (n or ln or "")


def _on_storey(fx: dict, kind: str, storey: str | None) -> list[dict]:
    es = [x for x in fx["elements"] if x["kind"] == kind]
    if storey is None:
        return es
    return [x for x in es if _norm(x["storey"]) == _norm(storey)]


def _evidence(fx: dict, path: str, els: list[dict], storey: str | None, label: str) -> list[Evidence]:
    """Boxes on the plan the question is about (the question's own PDF, else the storey's plan)."""
    plans = fx["plans"]
    if path.endswith(".pdf"):
        cands = [p for p in plans.values() if Path(p["pdf"]).name == Path(path).name]
    else:
        sid = next((g for g, n in fx["storeys"].items() if storey and _norm(n) == _norm(storey)), None)
        cands = [p for p in plans.values() if sid and p["storey"] == sid]
    if not cands:
        return []
    plan = cands[0]
    out = []
    for x in els[:400]:
        bb = plan["boxes"].get(x["guid"])
        if bb:
            out.append(Evidence(file=plan["pdf"], page=0, bbox=tuple(bb), polygon=plan["polys"].get(x["guid"]),
                                label=f"{label}: {room_label(x) or x['cls']}"))
    return out


def _room_area(x: dict) -> tuple[float | None, str]:
    if "NetFloorArea" in x.get("qb", {}):
        return x["qb"]["NetFloorArea"], "BaseQuantities NetFloorArea"
    return x.get("footprint"), "Plan footprint"


def _qsum(els: list[dict], names: tuple[str, ...], geo_key: str | None = None) -> tuple[float, int]:
    """Per element: BaseQuantities value, else geometry (`geo_key`), else any other quantity set.
    geo_key="any" means: any quantity set first (no geometry). Returns (total, n elements with no value)."""
    tot, missing = 0.0, 0
    for x in els:
        if geo_key == "any":
            v = next((x["q"][n] for n in names if n in x["q"]), None)
        else:
            v = next((x["qb"][n] for n in names if n in x.get("qb", {})), None)
            if v is None and geo_key:
                v = x.get(geo_key)
        if v is None:
            v = next((x["q"][n] for n in names if n in x["q"]), None)
        if v is None:
            missing += 1
        else:
            tot += v
    return tot, missing


def solve_template(path: str, template: str, p: dict) -> Answer | None:
    fx = facts(model_of(path))
    storey = p.get("storey")
    expl_scope = f"on '{storey}'" if storey else "in the whole model"

    if template == "count":
        els = _on_storey(fx, p["kind"], storey)
        return Answer(len(els), "count", _evidence(fx, path, els, storey, p["kind"]), "deterministic",
                      explanation=f"{len(els)} {', '.join(CLASSES[p['kind']][0])} entities {expl_scope} (IFC).")

    if template == "room_area":
        rooms = _on_storey(fx, "rooms", storey)
        hit = [x for x in rooms if _norm(room_label(x)) == _norm(p["room"])]
        if not hit:  # tolerate label variants: match on the number in brackets, or the name alone
            m = re.search(r"\(([^()]+)\)\s*$", p["room"])
            key = _norm(m.group(1)) if m else _norm(p["room"])
            hit = [x for x in rooms if key in (_norm(x["name"]), _norm(x["longname"]))]
        if len(hit) != 1:
            return None
        x = hit[0]
        area, how = _room_area(x)
        if area is None:
            return None
        return Answer(round(area, 2), "m2", _evidence(fx, path, [x], storey, "room"), "deterministic",
                      explanation=f"{how} of IfcSpace {room_label(x)} ({x['guid']}).")

    if template == "total_room_area":
        rooms = _on_storey(fx, "rooms", storey)
        tot = sum(_room_area(x)[0] or 0.0 for x in rooms)
        return Answer(round(tot, 2), "m2", _evidence(fx, path, rooms, storey, "room"), "deterministic",
                      explanation=f"Sum of {len(rooms)} IfcSpace footprints {expl_scope}.")

    if template in ("wall_length", "wall_side_area", "wall_volume", "slab_volume"):
        kind = "slabs" if template == "slab_volume" else "walls"
        els = _on_storey(fx, kind, storey)
        names, geo, unit = {
            "wall_length": (("Length",), "any", "m"),
            "wall_side_area": (("NetSideArea",), "any", "m2"),
            "wall_volume": (("NetVolume",), "mesh_volume", "m3"),
            "slab_volume": (("NetVolume",), "mesh_volume", "m3"),
        }[template]
        tot, missing = _qsum(els, names, geo)
        if not els or missing == len(els):
            return None
        return Answer(round(tot, 3), unit, _evidence(fx, path, els, storey, kind), "deterministic",
                      confidence=1.0 if not missing else 0.5,
                      explanation=f"Sum of {'/'.join(names)} over {len(els)} {kind} {expl_scope}"
                                  + (f"; {missing} without quantities" if missing else "") + ".")
    return None


# ----------------------------------------------------------------------------------------------- parsing
_EN = [
    (r"how many (.+?) are there in the model '(.+)'\?", lambda m: ("count", {"kind": NOUNS.get(m[1])})),
    (r"how many (.+?) are shown on the floor plan of '(.+)'\?", lambda m: ("count", {"kind": NOUNS.get(m[1]), "storey": m[2]})),
    (r"what is the net floor area of the room '(.+)' on '(.+?)', in", lambda m: ("room_area", {"room": m[1], "storey": m[2]})),
    (r"what is the total net floor area of all rooms \(spaces\) on '(.+?)', in", lambda m: ("total_room_area", {"storey": m[1]})),
    (r"what is the total length of all walls on '(.+?)', in", lambda m: ("wall_length", {"storey": m[1]})),
    (r"what is the total net side area of all walls on '(.+?)', in", lambda m: ("wall_side_area", {"storey": m[1]})),
    (r"what is the total net volume of all walls on '(.+?)', in", lambda m: ("wall_volume", {"storey": m[1]})),
    (r"what is the total net volume of all slabs on '(.+?)', in", lambda m: ("slab_volume", {"storey": m[1]})),
]


def parse_en(q: str) -> tuple[str, dict] | None:
    for pat, mk in _EN:
        if m := re.match(pat, q.strip(), re.I | re.S):
            t, p = mk(m)
            if t == "count" and not p["kind"]:
                return None
            return t, p
    return None


class IfcSolver:
    """Solver-protocol wrapper (see plansight/solvers/base.py)."""

    name = "ifc"

    def can_handle(self, path: str) -> bool:
        p = path.replace("\\", "/")
        return "ifc_models/" in p and p.endswith((".ifc", ".pdf"))

    def solve(self, path: str, question: str) -> Answer | None:
        parsed = parse_en(question)
        if parsed is None:
            return None
        return solve_template(path, *parsed)
