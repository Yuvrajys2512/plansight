"""Cached, deterministic 3D scene extraction for demo drawings."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from plansight.config import REPO, resolve

CACHE = REPO / "cache" / "scene3d"


def cache_paths(path: str) -> tuple[Path, Path]:
    key = hashlib.sha1(path.encode("utf-8")).hexdigest()
    return CACHE / f"{key}.json", CACHE / f"{key}.glb"


def _area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly))) / 2) if len(poly) >= 3 else 0


def _clean(points):
    out = []
    for x, y in points:
        p = [float(x), float(y)]
        if not out or math.dist(p, out[-1]) > 1e-7:
            out.append(p)
    if len(out) > 2 and math.dist(out[0], out[-1]) < 1e-7:
        out.pop()
    return out if len(out) >= 3 and _area(out) > 1e-9 else None


def _polyline(e):
    return _clean([(p[0], p[1]) for p in e.get_points("xy")])


def _inside(x, y, poly):
    hit = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi:
            hit = not hit
        j = i
    return hit


def _text_info(texts, x, y, height):
    import re
    number = next((t for t in texts if re.fullmatch(r"[A-Z]{0,2}\d+(?:\.\d+)*", t.dxf.text.strip())), None)
    name = area = None
    for t in texts:
        val = t.dxf.text.strip()
        if t is number:
            continue
        if re.fullmatch(r"[\d.]+\s*m(?:²|Â²)", val, re.I):
            try: area = float(re.search(r"[\d.]+", val).group())
            except ValueError: pass
        elif not re.fullmatch(r"[A-Z]{0,2}\d+(?:\.\d+)*", val):
            name = val
    return (name, number.dxf.text.strip() if number else None, area)


def swiss_scene(path: Path) -> dict:
    import ezdxf
    dxf_path = path.with_suffix(".dxf")
    if not dxf_path.is_file():
        raise FileNotFoundError(f"Sibling DXF not found for {path.name}")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    units_code = doc.header.get("$INSUNITS", 0)
    # DXF INSUNITS: 4=mm, 5=cm, 6=m. Unitless Swiss plans are conventionally millimetres.
    factor = {4: .001, 5: .01, 6: 1.0, 0: .001}.get(units_code, .001)
    groups = {layer: [] for layer in ("WALL", "ROOM_OUTLINE", "DOOR", "WINDOW", "FIXTURE", "UNIT_OUTLINE")}
    for e in msp.query("LWPOLYLINE"):
        layer = e.dxf.layer.upper()
        if layer in groups:
            p = _polyline(e)
            if p: groups[layer].append(p)
    # Closed hatch boundaries are the preferred wall geometry.
    hatches = []
    for hatch in msp.query('HATCH[layer=="WALL"]'):
        for boundary in hatch.paths:
            verts = getattr(boundary, "vertices", None)
            if verts:
                p = _clean([(v[0], v[1]) for v in verts])
                if p: hatches.append(p)
    walls = hatches or groups["WALL"]
    # Keep useful wall polygons when the DXF contains open centerlines on that layer.
    arcs = []
    for e in msp.query('ARC[layer=="DOOR"]'):
        c = e.dxf.center
        start, end = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
        while end < start: end += math.tau
        steps = max(4, min(32, math.ceil((end-start) / (math.pi/24))))
        arc = [(c.x + e.dxf.radius * math.cos(start + (end-start)*i/steps),
                c.y + e.dxf.radius * math.sin(start + (end-start)*i/steps)) for i in range(steps+1)]
        p = _clean([(c.x,c.y), *arc])
        if p: arcs.append(p)
    rooms = []
    text_entities = list(msp.query('TEXT[layer=="ROOM_TEXT"]'))
    import re
    for label in text_entities:
        if not re.fullmatch(r"[A-Z]{0,2}\d+(?:\.\d+)*", label.dxf.text.strip()): continue
        x, y, height = label.dxf.insert.x, label.dxf.insert.y, label.dxf.height
        containing = [poly for poly in groups["ROOM_OUTLINE"] if _inside(x, y, poly)]
        if not containing: continue
        poly = min(containing, key=_area)
        stack = [o for o in text_entities if abs(o.dxf.insert.x-x) < 1e-3 and abs(o.dxf.insert.y-y) < 2.5*height]
        name, number, area = _text_info(stack, x, y, height)
        rooms.append({"id": f"r{len(rooms)}", "polygon": poly, "name": name, "number": number, "area_m2": area})
    all_polys = walls + groups["ROOM_OUTLINE"] + groups["DOOR"] + arcs + groups["WINDOW"] + groups["FIXTURE"] + groups["UNIT_OUTLINE"]
    xs = [p[0] for poly in all_polys for p in poly]; ys = [p[1] for poly in all_polys for p in poly]
    if not xs: raise ValueError("DXF has no closed scene polygons")
    # Magnitude fallback handles drawings whose $INSUNITS is incorrectly set to metres.
    extent = max(max(xs)-min(xs), max(ys)-min(ys))
    if units_code == 6 and extent > 1000: factor = .001
    elif units_code in (0, 4, 5) and extent < 100: factor = 1.0
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    convert = lambda poly: [[round((x-cx)*factor, 5), round((y-cy)*factor, 5)] for x,y in poly]
    def entries(polys, prefix, height=None):
        return [{"id": f"{prefix}{i}", "polygon": convert(p), **({"height": height} if height else {})} for i,p in enumerate(polys)]
    return {"kind":"plan", "units":"m", "bounds":[round((min(xs)-cx)*factor,5),round((min(ys)-cy)*factor,5),round((max(xs)-cx)*factor,5),round((max(ys)-cy)*factor,5)],
            "walls":entries(walls,"w",2.7), "rooms":[{**r,"polygon":convert(r["polygon"])} for r in rooms],
            "doors":entries(groups["DOOR"]+arcs,"d"), "windows":entries(groups["WINDOW"],"n"),
            "fixtures":entries(groups["FIXTURE"],"f"), "unit_outlines":entries(groups["UNIT_OUTLINE"],"u"),
            "sheet_transform":{"scale":factor,"translate":[round(-cx*factor,5),round(-cy*factor,5)],"source_units":units_code or "unitless-mm","reliable":False}}


def raster_scene(path: Path) -> dict:
    """Walls from a raster plan: dark thick strokes survive a morphological opening; text and thin lines don't."""
    import cv2
    import numpy as np
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError("unreadable image")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thr = min(110, int(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0] * 0.8))
    mask = (gray < thr).astype(np.uint8) * 255
    k = max(3, round(max(h, w) / 330))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        raise ValueError("no walls found")
    hier = hier[0]
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("no walls found")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    m_per_px = 15.0 / max(x1 - x0, y1 - y0, 1)       # assume the plan spans ~15 m (typical apartment)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    conv = lambda c: [[round((float(x) - cx) * m_per_px, 4), round(-(float(y) - cy) * m_per_px, 4)] for x, y in c.reshape(-1, 2)]
    walls = []
    for i, c in enumerate(contours):
        if hier[i][3] != -1 or cv2.contourArea(c) < k * k * 6:
            continue
        outer = cv2.approxPolyDP(c, 1.5, True)
        if len(outer) < 3:
            continue
        holes, j = [], hier[i][2]
        while j != -1:
            if cv2.contourArea(contours[j]) > k * k * 4:
                hole = cv2.approxPolyDP(contours[j], 1.5, True)
                if len(hole) >= 3:
                    holes.append(conv(hole))
            j = hier[j][0]
        walls.append({"id": f"w{len(walls)}", "polygon": conv(outer), "holes": holes, "height": 2.7})
    half_w, half_h = (x1 - x0) / 2 * m_per_px, (y1 - y0) / 2 * m_per_px
    return {"kind": "plan", "units": "m", "bounds": [-half_w, -half_h, half_w, half_h], "walls": walls,
            "rooms": [], "doors": [], "windows": [], "fixtures": [], "unit_outlines": [],
            "raster": {"m_per_px": m_per_px, "cx": float(cx), "cy": float(cy), "width": w, "height": h}}


def ifc_scene(path: Path, glb_path: Path) -> dict:
    import ifcopenshell
    import ifcopenshell.geom as geom
    import numpy as np
    import trimesh
    model = ifcopenshell.open(str(path))
    settings = geom.settings()
    settings.set("use-world-coords", True)
    import ifcopenshell.util.element as uel
    scene = trimesh.Scene()
    elements = []
    storeys = {}
    for st in model.by_type("IfcBuildingStorey"):
        storeys[st.GlobalId] = {"name": st.Name or "", "elevation": float(st.Elevation or 0.0)}
    for element in model.by_type("IfcProduct"):
        if not getattr(element, "Representation", None): continue
        try:
            shape = geom.create_shape(settings, element)
            vertices = np.asarray(shape.geometry.verts, dtype=float).reshape((-1,3))
            faces = np.asarray(shape.geometry.faces, dtype=np.int64).reshape((-1,3))
            if len(faces) == 0: continue
            vertices = np.round(vertices, 3)
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
            mesh.metadata.update({"guid":element.GlobalId,"ifc_class":element.is_a(),"name":element.Name or ""})
            name = f"{element.is_a()}_{element.GlobalId}"
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            st = uel.get_container(element)
            while st is not None and not st.is_a("IfcBuildingStorey"):
                st = uel.get_aggregate(st) if hasattr(uel, "get_aggregate") else None
            elements.append({"guid":element.GlobalId,"ifc_class":element.is_a(),"name":element.Name or "",
                             "storey": st.Name if st is not None else None})
        except Exception:
            continue
    if not elements: raise ValueError("IFC produced no mesh geometry")
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    glb_path.write_bytes(scene.export(file_type="glb"))
    storey_list = sorted(storeys.values(), key=lambda s: s["elevation"])
    return {"kind":"ifc","units":"m","glb":glb_path.name,"elements":elements,"storeys":storey_list}


def build_scene(path: str, local: Path, *, ifc_model: Path | None = None) -> dict:
    json_path, glb_path = cache_paths(path)
    if json_path.is_file():
        cached = json.loads(json_path.read_text(encoding="utf-8"))
        if cached.get("_scene_version") == 3 and (cached.get("kind") != "ifc" or glb_path.is_file()): return cached
    CACHE.mkdir(parents=True, exist_ok=True)
    model_path = ifc_model or (local if local.suffix.lower() == ".ifc" else None)
    if model_path:
        result = ifc_scene(model_path, glb_path)
    elif local.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and not local.with_suffix(".dxf").is_file():
        result = raster_scene(local)
    else:
        result = swiss_scene(local)
    result["_scene_version"] = 3
    if result["kind"] == "ifc": result["glb"] = f"/api/scene3d/glb?path={path}"
    json_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    return result
