"""CubiCasa5K model.svg -> labelled boxes in F1_original.png pixel space (training data for the detector).

The SVG is drawn in F1_scaled.png space; F1_original.png (= our dataset PNG, byte-identical) is a uniform resize of it,
so boxes are mapped with per-axis factors original/scaled. Nested `transform`s (matrix/translate/scale/rotate) are
composed down the tree, which matters for furniture icons (drawn in local coords under a matrix).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

# detector class name -> predicate on the SVG class attribute
OBJECT_CLASSES = {
    "window": lambda c: c.startswith("Window"),
    "door": lambda c: c.startswith("Door ") and not c.startswith("Door None"),
    "opening": lambda c: c.startswith("Door None"),  # doorway without a leaf (not counted as a door)
    "toilet": lambda c: c == "FixedFurniture Toilet",
    "sink": lambda c: c.startswith("FixedFurniture") and "Sink" in c and "Double" not in c,  # Sink/Round/Corner/Side
    "double_sink": lambda c: c.startswith("FixedFurniture DoubleSink"),
    "shower": lambda c: c in ("FixedFurniture Shower", "FixedFurniture ShowerCab", "FixedFurniture ShowerPlatform"),
    "bathtub": lambda c: c.startswith("FixedFurniture Bathtub"),
    "sauna_stove": lambda c: c.startswith("FixedFurniture ElectricalAppliance SaunaStove"),
}
ROOM_PREFIX = "Space "


@dataclass
class Item:
    cls: str          # detector class, or "room:<Space ...>" for spaces, "floor" for Floorplan groups
    svg_class: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in output pixel space
    polygon: list[tuple[float, float]] | None = None
    text: str = ""    # rooms: the annotator's name label (e.g. "MH", "KH", "S")


def _name_text(el: ET.Element) -> str:
    for ch in el.iter():
        if "NameLabel" in (ch.get("class") or ""):
            ts = ["".join(t.itertext()).strip() for t in ch.iter() if t.tag.split("}")[-1] == "text"]
            return " ".join(t for t in ts if t)
    return ""


def _parse_transform(s: str | None) -> np.ndarray:
    m = np.eye(3)
    if not s:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        a = [float(x) for x in re.split(r"[ ,]+", args.strip()) if x]
        t = np.eye(3)
        if name == "matrix" and len(a) == 6:
            t = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate":
            t[0, 2] = a[0]; t[1, 2] = a[1] if len(a) > 1 else 0.0
        elif name == "scale":
            t[0, 0] = a[0]; t[1, 1] = a[1] if len(a) > 1 else a[0]
        elif name == "rotate":
            r = math.radians(a[0]); c, s_ = math.cos(r), math.sin(r)
            rot = np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])
            if len(a) == 3:
                tr = np.array([[1, 0, a[1]], [0, 1, a[2]], [0, 0, 1]]); itr = np.array([[1, 0, -a[1]], [0, 1, -a[2]], [0, 0, 1]])
                rot = tr @ rot @ itr
            t = rot
        m = m @ t
    return m


def _local_points(el: ET.Element) -> list[tuple[float, float]]:
    tag = el.tag.split("}")[-1]
    if tag in ("polygon", "polyline"):
        nums = [float(x) for x in re.split(r"[ ,]+", (el.get("points") or "").strip()) if x]
        return list(zip(nums[0::2], nums[1::2]))
    if tag == "rect":
        x, y, w, h = (float(el.get(k, 0)) for k in ("x", "y", "width", "height"))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if tag == "line":
        return [(float(el.get("x1", 0)), float(el.get("y1", 0))), (float(el.get("x2", 0)), float(el.get("y2", 0)))]
    if tag in ("circle", "ellipse"):
        cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
        rx = float(el.get("r", el.get("rx", 0))); ry = float(el.get("r", el.get("ry", 0)))
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    return []


def _apply(m: np.ndarray, pts):
    return [(m[0, 0] * x + m[0, 1] * y + m[0, 2], m[1, 0] * x + m[1, 1] * y + m[1, 2]) for x, y in pts]


def _geometry(el: ET.Element, m: np.ndarray, prefer: str | None = None) -> list[tuple[float, float]]:
    """Points of an element: its first direct polygon (or the BoundaryPolygon for icons), else all descendants."""
    if prefer:
        for ch in el.iter():
            if (ch.get("class") or "") == prefer:
                return _collect(ch, m)  # m is the element's own transform; BoundaryPolygon sits under it
    for ch in el:
        if ch.tag.split("}")[-1] == "polygon":
            return _apply(m @ _parse_transform(ch.get("transform")), _local_points(ch))
    return _collect(el, m, skip_self=True)


def _collect(el, m, skip_self=False):
    pts = []
    mm = m if skip_self else m @ _parse_transform(el.get("transform")) if el.get("transform") else m

    def rec(e, mat):
        mat = mat @ _parse_transform(e.get("transform"))
        pts.extend(_apply(mat, _local_points(e)))
        for c in e:
            rec(c, mat)

    if skip_self:
        for c in el:
            rec(c, m)
    else:
        pts.extend(_apply(mm, _local_points(el)))
        for c in el:
            rec(c, mm)
    return pts


def parse(svg_text: str, sx: float = 1.0, sy: float = 1.0) -> list[Item]:
    """All labelled items; coordinates multiplied by (sx, sy) to land in the target image space."""
    root = ET.fromstring(svg_text)
    out: list[Item] = []

    def rec(el: ET.Element, parent: np.ndarray):
        m = parent @ _parse_transform(el.get("transform"))
        c = (el.get("class") or "").strip()
        hit = None
        if c.startswith("Floorplan"):
            hit = ("floor", None)
        elif c.startswith(ROOM_PREFIX):
            hit = ("room:" + c, None)
        else:
            for name, pred in OBJECT_CLASSES.items():
                if pred(c):
                    hit = (name, "BoundaryPolygon" if c.startswith("FixedFurniture") else None)
                    break
        if hit:
            pts = _geometry(el, m, hit[1])
            if pts:
                xs = [p[0] * sx for p in pts]; ys = [p[1] * sy for p in pts]
                poly = [(x * sx, y * sy) for x, y in pts] if hit[0].startswith("room:") else None
                txt = _name_text(el) if hit[0].startswith("room:") else ""
                out.append(Item(hit[0], c, (min(xs), min(ys), max(xs), max(ys)), poly, txt))
            if not hit[0] == "floor":
                return  # don't descend into a labelled object (avoids Panel/Glass sub-parts)
        for ch in el:
            rec(ch, m)

    rec(root, np.eye(3))
    return out
