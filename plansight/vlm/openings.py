"""Detector proposes, Nemotron classifies: every door/window/opening candidate becomes a zoomed crop that Nemotron 3.5
Super VL labels under explicit counting rules (swing door with N leaves, window, French door, sliding closet, ...).

Why: the detector finds symbols well but cannot apply semantic counting rules ("a French door counts as a window",
"a double-leaf door is 2 doors", "sliding closet doors don't count"). A VLM applies rules well but cannot count
40 tiny symbols on a whole sheet. Each does the half it is good at, and every counted item keeps its box.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

from plansight.vlm import nemotron
from plansight.vlm.verify import crop

TYPES = ["swing_door", "double_swing_door", "sliding_glass_door", "french_door", "window", "sliding_closet_door",
         "garage_door", "opening_no_door", "not_an_opening"]
SCHEMA = {"type": "object", "properties": {"type": {"type": "string", "enum": TYPES}}, "required": ["type"]}
# v1. A v2 with an exterior-wall field and a "casement_window" label over-steered Nemotron (split A door 42% -> 18%).
PROMPT = (
    "This is a zoomed crop of an architectural floor plan. Classify the wall element inside the red box.\n"
    "- swing_door: one door leaf drawn with a swing arc\n"
    "- double_swing_door: two door leaves (two arcs) in one opening\n"
    "- sliding_glass_door: a sliding glazed panel in an exterior wall\n"
    "- french_door: a large glazed door / patio door in an exterior wall (thin glazing lines, often two leaves)\n"
    "- window: a window (thin parallel lines set into an exterior wall)\n"
    "- sliding_closet_door: sliding panels on a closet or wardrobe\n"
    "- garage_door: a garage entrance\n"
    "- opening_no_door: an opening or passage without any door leaf\n"
    "- not_an_opening: anything else (furniture, text, wall, stairs)\n"
    'Answer with JSON {"type": "<one of the labels>"}.'
)
# AECV-Bench counting rules applied to the label: (doors, windows) contributed by one element
RULES = {"swing_door": (1, 0), "double_swing_door": (2, 0), "sliding_glass_door": (0, 1), "french_door": (0, 1),
         "window": (0, 1), "sliding_closet_door": (0, 0), "garage_door": (0, 0), "opening_no_door": (0, 0),
         "not_an_opening": (0, 0)}


@dataclass
class Vote:
    bbox: tuple
    det_cls: str
    det_conf: float
    type: str
    cost_usd: float
    wall: str = "unsure"


def classify(image: Image.Image, bbox, think: bool = False) -> tuple[str, str, float]:
    r = nemotron.ask(PROMPT, [nemotron.encode_image(crop(image, bbox), max_side=448)], json_schema=SCHEMA,
                     max_tokens=24, think=think)
    try:
        d = json.loads(r.text)
        t, wall = d["type"], d.get("wall", "unsure")  # wall: only in prompt variants that ask for it
    except Exception:  # noqa: BLE001
        t, wall = next((x for x in TYPES if x in r.text), "not_an_opening"), "unsure"
    return (t if t in RULES else "not_an_opening"), wall, r.cost_usd


def classify_all(image: Image.Image, cands, workers: int = 8) -> list[Vote]:
    """cands: [(cls, conf, bbox)] -> one Vote each."""
    image = image.convert("RGB")
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda c: classify(image, c[2]), cands))
    return [Vote(tuple(b), c, s, t, cost, wall) for (c, s, b), (t, wall, cost) in zip(cands, res)]


def merge_adjacent(boxes, gap: float = 6.0):
    """AECV: adjacent windows with no gap between them are one window group. Union-find on touching boxes."""
    boxes = [tuple(b) for b in boxes]
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1]):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    return [(min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g))
            for g in groups.values()]


def nms_any(cands, iou: float = 0.4):
    """Class-agnostic NMS over [(cls, conf, bbox)]: a door and a window box on the same symbol -> one candidate."""
    def _iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
        return ix * iy / u if u > 0 else 0.0

    keep = []
    for c in sorted(cands, key=lambda c: -c[1]):
        if all(_iou(c[2], k[2]) < iou for k in keep):
            keep.append(c)
    return keep
