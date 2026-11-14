"""Object counting on raster floor plans with Nemotron: upscaled overlapping tiles, one box per object, dedupe.

Boxes come back normalised 0-1000 within each tile and are mapped to original-image pixels, so every counted
object doubles as an Evidence box the UI can draw.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PIL import Image

from plansight.vlm import nemotron

ITEMS_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"box": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}},
        "required": ["box"]}}},
    "required": ["items"],
}

# what to look for, phrased for a single tile (the question's own wording is appended)
OBJECTS = {
    "window": "windows (wall openings drawn as thin parallel lines inside an exterior wall)",
    "door": "doors (door leaves, usually drawn with a swing arc); open doorways without a door leaf do not count",
    "toilet": "toilet bowls / WC seats",
    "sink": "sinks and wash basins (kitchen and bathroom; a double-bowl sink counts as one)",
    "shower_bath": "showers and bathtubs",
}


@dataclass
class Count:
    n: int
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0


def tiles(w: int, h: int, tile: int, overlap: int) -> list[tuple[int, int, int, int]]:
    def starts(L):
        if L <= tile:
            return [0]
        n = -(-(L - overlap) // (tile - overlap))
        step = (L - tile) / (n - 1)
        return [round(i * step) for i in range(n)]
    return [(x, y, min(x + tile, w), min(y + tile, h)) for y in starts(h) for x in starts(w)]


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _contained(a, b, frac=0.7) -> bool:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    sa = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    sb = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / min(sa, sb) >= frac


def dedupe(boxes: list[tuple], iou: float = 0.3) -> list[tuple]:
    keep: list[tuple] = []
    for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        if not any(_iou(b, k) >= iou or _contained(b, k) for k in keep):
            keep.append(b)
    return keep


def count_objects(img: Image.Image, kind: str, question: str = "", *, tile: int = 400, overlap: int = 80,
                  scale: float = 2.5, workers: int = 4) -> Count:
    img = img.convert("RGB")
    W, H = img.size
    what = OBJECTS[kind]
    prompt = (f"This is one tile of an architectural floor plan. Find every {what} visible in this tile. "
              "Return one item per object with its bounding box [x0, y0, x1, y1] in coordinates normalised to "
              "0-1000 of this tile. Include objects cut by the tile edge. Return an empty list if there are none."
              + (f"\nContext (the user's question about the whole plan): {question}" if question else ""))

    def one(t):
        crop = img.crop(t)
        cw, ch = crop.size
        up = crop.resize((round(cw * scale), round(ch * scale)), Image.LANCZOS)
        r = nemotron.ask(prompt, [nemotron.encode_image(up, max_side=2048)], json_schema=ITEMS_SCHEMA, max_tokens=800)
        import json
        try:
            items = json.loads(r.text).get("items", [])
        except Exception:
            items = []
        out = []
        for it in items:
            b = it.get("box") or []
            if len(b) != 4:
                continue
            x0, y0, x1, y1 = sorted(b[0::2]) + sorted(b[1::2]) if False else (min(b[0], b[2]), min(b[1], b[3]),
                                                                              max(b[0], b[2]), max(b[1], b[3]))
            out.append((t[0] + x0 / 1000 * cw, t[1] + y0 / 1000 * ch, t[0] + x1 / 1000 * cw, t[1] + y1 / 1000 * ch))
        return out, r

    ts = tiles(W, H, tile, overlap)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, ts))
    boxes = dedupe([b for bs, _ in res for b in bs])
    return Count(len(boxes), boxes, sum(r.cost_usd for _, r in res), sum(r.tokens_in for _, r in res),
                 sum(r.tokens_out for _, r in res), len(ts))
