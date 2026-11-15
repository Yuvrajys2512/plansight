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


def objects_model() -> str:
    """Object detector to use: env PLANSIGHT_OBJECTS_MODEL (e.g. cubicasa_objects_v2), else the default."""
    return os.getenv("PLANSIGHT_OBJECTS_MODEL", "cubicasa_objects")


def detector_for(kind: str):
    if kind in OBJECT_KINDS:
        return objects_model(), OBJECT_KINDS[kind]
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
    if os.getenv("PLANSIGHT_VERIFY", "1") in ("0", "false") or os.getenv("PLANSIGHT_NO_LLM", "") in ("1", "true"):
        return False
    try:
        from plansight.vlm.nemotron import backend

        backend()
        return True
    except Exception:  # noqa: BLE001
        return False


def dedupe(dets, ios: float = 0.5):
    """One fixture, one count: drop a box mostly inside a more confident box of the same kind (intersection over the
    smaller box > ios). Catches nested duplicates that IoU-based NMS keeps, and a shower + bathtub (or sink + double
    sink) fired on the same fixture. Tuned on the CubiCasa val split: doors +1.9, windows +2.7, showers/baths +2.2 pts."""
    keep = []
    for d in sorted(dets, key=lambda d: -d.conf):
        a = d.bbox
        sa = (a[2] - a[0]) * (a[3] - a[1])
        dup = False
        for k in keep:
            b = k.bbox
            ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
            iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            if ix * iy / max(min(sa, (b[2] - b[0]) * (b[3] - b[1])), 1e-6) > ios:
                dup = True
                break
        if not dup:
            keep.append(d)
    return keep


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
    dets, ms = _detect(name, path)
    thr = det.thresholds.get(kind, 0.4)
    mine = [d for d in dets if d.cls in classes]
    if kind in OBJECT_KINDS:
        mine = dedupe(mine)
    border = [d for d in mine if abs(d.conf - thr) < BORDER]
    sure = [d for d in mine if d.conf >= thr + BORDER]
    if verify is None:
        verify = verify_enabled()
    if not border or not verify or kind not in OBJECT_KINDS:
        return Count(sure + [d for d in border if d.conf >= thr], border, [], thr, name, ms)
    from plansight.vlm.verify import adjudicate

    image = Image.open(resolve(path)).convert("RGB")  # fully decoded: crops run in parallel threads
    votes, cost = adjudicate(image, border)
    return Count(sure + [d for d, ok in votes if ok], border, [d for d, ok in votes if not ok], thr, name, ms,
                 cost, True)


def _review(res: Count, ev: list, kind: str) -> dict | None:
    """What a reviewer should look at: counted items that only just passed the threshold ("likely"), and near-miss
    candidates that just failed it ("possible", not counted). The count is between len(sure) and counted + possible."""
    counted = sorted(res.counted, key=lambda d: (d.bbox[1], d.bbox[0]))
    likely = [i for i, d in enumerate(counted) if d.conf < res.thr + BORDER]
    ids = {id(d) for d in res.counted}
    possible = [[round(v, 1) for v in d.bbox] + [round(float(d.conf), 2)]
                for d in res.border if id(d) not in ids and id(d) not in {id(r) for r in res.rejected}]
    if not likely and not possible:
        return None
    unit = UNITS.get(kind, kind)
    parts = []
    if likely:
        parts.append(f"{len(likely)} counted {'item only just passes' if len(likely) == 1 else 'items only just pass'} "
                     f"the detector's {res.thr:.2f} cut-off (outlined dashed)")
    if possible:
        parts.append(f"{len(possible)} more {'candidate' if len(possible) == 1 else 'candidates'} just below it {'is' if len(possible) == 1 else 'are'} "
                     f"not counted (amber); tap one to add it")
    return {"low": len(counted) - len(likely), "high": len(counted) + len(possible), "likely": likely,
            "possible": possible, "reason": "; ".join(parts).capitalize() + "."}


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
        review = _review(res, ev, kind)
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
                      confidence=conf, explanation=expl, review=review)
