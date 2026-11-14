"""CubiCasa floor plans: fine-tuned YOLO detectors count objects/rooms, every counted item is an evidence box.

Pipeline per question (all on CPU, no LLM unless needed):
1. router.parse -> ("count", {"kind": ...}) in any language (English parser / template bank / Gemma fallback)
2. objects (windows, doors, toilets, sinks, showers+baths): detector model 1 (`models/cubicasa_objects.onnx`)
   rooms (bedrooms, kitchens, bathrooms, WC rooms, saunas, balconies) + floors: model 2 (`models/cubicasa_rooms.onnx`)
3. count = detections of the kind's classes above a per-kind threshold tuned on the CubiCasa val split
4. borderline detections (score near the threshold) lower the confidence; Nemotron can adjudicate them (verify.py)

Falls back to the OCR label solver (rooms) when a model file is missing, so the app still runs without weights.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

from plansight.config import resolve
from plansight.detect.onnx_yolo import load
from plansight.detect.rules import OBJECT_KINDS, ROOM_KINDS
from plansight.types import Answer, Evidence

CPU_USD_PER_S = 0.10 / 3600  # a 4-vCPU cloud instance at ~$0.10/h; the detector runs ~1 s per plan
BORDER = 0.12

LABELS = {"window": "window", "door": "door", "toilet": "WC seat", "sink": "sink", "double_sink": "double sink",
          "shower": "shower", "bathtub": "bathtub", "bedroom": "bedroom", "kitchen": "kitchen",
          "bathroom": "bathroom", "wc_room": "WC room", "sauna": "sauna", "balcony": "balcony", "floor": "floor"}
UNITS = {"window": "windows", "door": "doors", "toilet": "toilets", "sink": "sinks", "shower_bath": "showers/baths",
         "bedroom": "bedrooms", "kitchen": "kitchens", "bathroom": "bathrooms", "wc_room": "WC rooms",
         "sauna": "saunas", "balcony": "balconies", "floor": "floors"}


def detector_for(kind: str):
    if kind in OBJECT_KINDS:
        return "cubicasa_objects", OBJECT_KINDS[kind]
    if kind in ROOM_KINDS or kind == "floor":
        return "cubicasa_rooms", (kind,)
    return None, ()


@lru_cache(maxsize=256)
def _detect(name: str, path: str):
    """All detections of model `name` on a drawing (cached: one detector pass serves every question about it)."""
    t0 = time.perf_counter()
    dets = load(name)(Image.open(resolve(path)), conf=0.05)
    return dets, (time.perf_counter() - t0) * 1000


def verify_enabled() -> bool:
    if os.getenv("PLANSIGHT_VERIFY", "1") in ("0", "false"):
        return False
    try:
        from plansight.vlm.nemotron import backend

        backend()
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Count:
    counted: list           # detections that count (sure + Nemotron-accepted borderline)
    border: list            # borderline detections (score within BORDER of the threshold)
    rejected: list          # borderline detections Nemotron rejected
    thr: float
    model: str
    det_ms: float
    vlm_cost: float = 0.0
    verified: bool = False


def count(path: str, kind: str, verify: bool | None = None) -> Count | None:
    """Detector count for `kind`; borderline hits go to Nemotron when verify is on. None if no model file."""
    name, classes = detector_for(kind)
    det = load(name) if name else None
    if det is None:
        return None
    image = Image.open(resolve(path))
    dets, ms = _detect(name, path)
    thr = det.thresholds.get(kind, 0.4)
    mine = [d for d in dets if d.cls in classes]
    border = [d for d in mine if abs(d.conf - thr) < BORDER]
    sure = [d for d in mine if d.conf >= thr + BORDER]
    if verify is None:
        verify = verify_enabled()
    if not border or not verify or kind not in OBJECT_KINDS:
        return Count(sure + [d for d in border if d.conf >= thr], border, [], thr, name, ms)
    from plansight.vlm.verify import adjudicate

    votes, cost = adjudicate(image, border)
    return Count(sure + [d for d, ok in votes if ok], border, [d for d, ok in votes if not ok], thr, name, ms,
                 cost, True)


class CubicasaSolver:
    name = "cubicasa"

    def can_handle(self, path: str) -> bool:
        return "/cubicasa5k/" in path.replace("\\", "/")

    def solve(self, path: str, question: str) -> Answer | None:
        from plansight.router import parse

        route = parse(path, question)
        kind = route.params.get("kind") if route.template == "count" else None
        if kind is None:
            return None
        res = count(path, kind)
        if res is None:
            if kind in ROOM_KINDS:
                from plansight.solvers.cubicasa_text import CubicasaTextSolver

                return CubicasaTextSolver().solve(path, question)
            return None
        ev = [Evidence(file=path, page=0, bbox=tuple(round(v, 1) for v in d.bbox),
                      label=f"{LABELS.get(d.cls, d.cls)} {i + 1} ({d.conf:.2f})")
              for i, d in enumerate(sorted(res.counted, key=lambda d: (d.bbox[1], d.bbox[0])))]
        unresolved = 0 if res.verified else len(res.border)
        conf = max(0.3, min(0.99, 0.99 - 0.1 * unresolved - 0.03 * len(res.border) * res.verified))
        cost = res.det_ms / 1000 * CPU_USD_PER_S + res.vlm_cost + route.cost_usd
        expl = (f"{route.describe()}. Fine-tuned detector ({res.model}) found {len(res.counted)} "
                f"{UNITS.get(kind, kind)} (score >= {res.thr:.2f}).")
        if res.verified:
            expl += (f" Nemotron 3.5 Super VL checked {len(res.border)} borderline detection(s) on zoomed crops: "
                     f"kept {len(res.border) - len(res.rejected)}, rejected {len(res.rejected)}.")
        elif res.border:
            expl += f" {len(res.border)} detection(s) are borderline (not verified)."
        return Answer(value=len(res.counted), unit="count", evidence=ev,
                      method="detector+vlm" if res.verified else "detector", cost_usd=cost,
                      confidence=conf, explanation=expl)
