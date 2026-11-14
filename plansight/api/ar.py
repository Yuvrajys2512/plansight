"""Tabletop AR models: the 3D scene of a drawing with the answer's evidence baked in as lime, scaled to ~45 cm.

Served as GLB for <model-viewer> (WebXR on Android, Quick Look on iOS, which converts the GLB to USDZ in the browser).
"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path

from plansight.config import REPO

AR_CACHE = REPO / "cache" / "ar"
TABLE_SIZE_M = 0.45          # longest side of the model on the table

LIME, LIME_GLOW = [200, 255, 61, 255], [0.55, 0.75, 0.1]
WALL, FLOOR, GHOST, MUTED, GLASS = [228, 234, 240, 255], [30, 42, 56, 255], [150, 180, 210, 70], [100, 116, 134, 255], [61, 224, 255, 150]


def _material(rgba, emissive=None):
    from trimesh.visual.material import PBRMaterial
    return PBRMaterial(baseColorFactor=rgba, emissiveFactor=emissive or [0, 0, 0], metallicFactor=0.0,
                       roughnessFactor=0.7, alphaMode="BLEND" if rgba[3] < 255 else "OPAQUE", doubleSided=True)


def _paint(mesh, rgba, emissive=None):
    import trimesh
    mesh.visual = trimesh.visual.TextureVisuals(material=_material(rgba, emissive))
    return mesh


def _prism(poly, height, z0=0.0, holes=()):
    from shapely.geometry import Polygon
    from trimesh.creation import extrude_polygon
    shape = Polygon(poly, [h for h in holes if len(h) >= 3]).buffer(0)
    if shape.is_empty or shape.area < 1e-6:
        return None
    parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    import trimesh
    meshes = [extrude_polygon(p, height) for p in parts if p.area > 1e-6]
    if not meshes:
        return None
    m = trimesh.util.concatenate(meshes)
    m.apply_translation([0, 0, z0])
    return m


def _centroid(poly):
    return sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)


def _plan_targets(scene: dict, answer: dict | None) -> tuple[list, str]:
    """Polygons to light up: detector boxes for raster plans, the matching CAD layer for Swiss plans."""
    if not answer or answer.get("abstained"):
        return [], ""
    kind = answer.get("scene_kind") or ""
    if scene.get("raster") and answer.get("evidence"):
        r = scene["raster"]; m = r["m_per_px"]
        to = lambda x, y: ((x - r["cx"]) * m, -(y - r["cy"]) * m)
        return [[to(x0, y0), to(x1, y0), to(x1, y1), to(x0, y1)] for x0, y0, x1, y1 in (e["bbox"] for e in answer["evidence"])], kind or "doors"
    layer = {"doors": "doors", "windows": "windows", "fixtures": "fixtures", "units": "unit_outlines"}.get(kind)
    if layer:
        return [e["polygon"] for e in scene.get(layer, [])], kind
    if kind == "rooms":
        names = [n.lower() for n in answer.get("scene_room_names") or []]
        rooms = [r for r in scene.get("rooms", []) if r.get("name") and (not names or any(n in r["name"].lower() for n in names))]
        return [r["polygon"] for r in rooms], kind
    return [], kind


def plan_glb(scene: dict, answer: dict | None) -> bytes:
    import trimesh
    targets, kind = _plan_targets(scene, answer)
    meshes = []
    b = scene["bounds"]
    slab = _prism([(b[0] - .3, b[1] - .3), (b[2] + .3, b[1] - .3), (b[2] + .3, b[3] + .3), (b[0] - .3, b[3] + .3)], .08, -.08)
    if slab is not None: meshes.append(_paint(slab, FLOOR))
    for r in scene.get("rooms", []):
        m = _prism(r["polygon"], .02)
        if m is not None: meshes.append(_paint(m, [44, 60, 78, 255]))
    for w in scene.get("walls", []):
        m = _prism(w["polygon"], w.get("height", 2.7), holes=w.get("holes") or ())
        if m is not None: meshes.append(_paint(m, WALL if not targets else [210, 220, 230, 255]))
    lit = {id(p) for p in targets}
    if not scene.get("raster"):
        for d in scene.get("doors", []):
            if id(d["polygon"]) in lit: continue
            m = _prism(d["polygon"], .05)
            if m is not None: meshes.append(_paint(m, MUTED))
        for w in scene.get("windows", []):
            if id(w["polygon"]) in lit: continue
            m = _prism(w["polygon"], 1.3, .9)
            if m is not None: meshes.append(_paint(m, GLASS))
    h, z0 = {"windows": (1.3, .9), "doors": (2.1, 0), "rooms": (.25, 0), "units": (.2, 0)}.get(kind, (1.0, 0))
    for poly in targets:
        m = _prism(poly, h, z0)
        if m is not None: meshes.append(_paint(m, LIME, LIME_GLOW))
    scene_tm = trimesh.Scene(meshes)
    return _finish(scene_tm, z_up=True)


def ifc_glb(glb_path: Path, ifc_class: str | None) -> bytes:
    import trimesh
    src = trimesh.load(str(glb_path), force="scene")
    out = trimesh.Scene()
    for name, geom in src.geometry.items():
        cls = name.split("_", 1)[0]
        if cls == "IfcSpace" and cls != ifc_class:
            continue
        g = geom.copy()
        if ifc_class and cls == ifc_class:
            _paint(g, LIME, LIME_GLOW)
        else:
            _paint(g, GHOST if ifc_class else WALL)
        out.add_geometry(g, geom_name=name)
    return _finish(out, z_up=True)


def _finish(scene, z_up: bool) -> bytes:
    import numpy as np
    import trimesh
    mesh_scene = scene
    if z_up:   # glTF is Y-up
        mesh_scene.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
    lo, hi = mesh_scene.bounds
    size = max(hi[0] - lo[0], hi[2] - lo[2], 1e-6)
    s = TABLE_SIZE_M / size
    T = np.eye(4); T[:3, :3] *= s
    T[1, 1] *= 1.8   # exaggerate height so walls read on a tabletop model
    T[:3, 3] = [-(lo[0] + hi[0]) / 2 * s, -lo[1] * s, -(lo[2] + hi[2]) / 2 * s]
    mesh_scene.apply_transform(T)
    buf = io.BytesIO(); buf.write(mesh_scene.export(file_type="glb"))
    return buf.getvalue()


def ar_model(rel: str, local: Path, scene: dict, answer: dict | None, ifc_glb_path: Path | None) -> Path:
    key = hashlib.sha1(f"{rel}|{(answer or {}).get('value')}|{(answer or {}).get('scene_kind')}|{(answer or {}).get('explanation')}".encode()).hexdigest()
    out = AR_CACHE / f"{key}.glb"
    if out.is_file():
        return out
    AR_CACHE.mkdir(parents=True, exist_ok=True)
    if scene.get("kind") == "ifc":
        import re
        m = re.search(r"Ifc[A-Z][A-Za-z]+", (answer or {}).get("explanation") or "")
        data = ifc_glb(ifc_glb_path, m.group(0) if m else None)
    else:
        data = plan_glb(scene, answer)
    out.write_bytes(data)
    return out
