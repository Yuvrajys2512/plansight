"""Nemotron adjudicates borderline detector hits: zoomed crop, candidate marked in red, strict yes/no JSON.

The detector is certain about most symbols; only detections whose score is near the counting threshold come here, so
Nemotron sees a few small crops per question instead of the whole sheet (cheap, and the crop is itself evidence).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

from plansight.vlm import nemotron

WHAT = {
    "window": "a window (in floor plans: a thin rectangle with parallel lines set into an exterior wall)",
    "door": "a door with a door leaf (a swing arc or sliding leaf in a wall opening); an empty opening is NOT a door",
    "toilet": "a toilet bowl (WC seat) symbol",
    "sink": "a sink or wash basin symbol",
    "double_sink": "a double-bowl sink symbol",
    "shower": "a shower symbol (shower tray / drain / shower head), not a shower cabin screen",
    "bathtub": "a bathtub symbol",
}
SCHEMA = {"type": "object", "properties": {"is_match": {"type": "boolean"}}, "required": ["is_match"]}


def crop(image: Image.Image, bbox, pad: float = 1.5, min_side: int = 160, out_side: int = 448) -> Image.Image:
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    side = max(min_side, max(w, h) * (1 + 2 * pad))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    box = (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))
    c = image.convert("RGB").crop(box)
    s = out_side / side
    c = c.resize((out_side, out_side), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    d.rectangle([(x0 - box[0]) * s - 3, (y0 - box[1]) * s - 3, (x1 - box[0]) * s + 3, (y1 - box[1]) * s + 3],
                outline=(230, 0, 0), width=3)
    return c


def is_match(image: Image.Image, det) -> tuple[bool, float]:
    what = WHAT.get(det.cls, det.cls)
    prompt = (f"This is a zoomed crop of an architectural floor plan. Is the symbol inside the red box {what}? "
              f'Answer with JSON {{"is_match": true|false}}.')
    r = nemotron.ask(prompt, [nemotron.encode_image(crop(image, det.bbox), max_side=448)], json_schema=SCHEMA,
                     max_tokens=16)
    try:
        ok = bool(json.loads(r.text)["is_match"])
    except Exception:  # noqa: BLE001
        ok = "true" in r.text.lower()
    return ok, r.cost_usd


def adjudicate(image: Image.Image, dets, workers: int = 8):
    """[(det, accepted)] and total cost."""
    if not dets:
        return [], 0.0
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda d: is_match(image, d), dets))
    return [(d, ok) for d, (ok, _) in zip(dets, res)], sum(c for _, c in res)
