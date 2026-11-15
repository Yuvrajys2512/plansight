"""Cheap first, escalate when unsure.

PlanSight answers every floor plan itself (detectors + OCR + Nemotron voters, ~$0.0005). Only when PlanSight is unsure
does the plan go to a frontier model (Gemini 3.5 Flash), and only the unsure kinds take its answer. Doors and windows
keep PlanSight's evidence boxes either way, so a human can still see what was found and what the frontier model added.

Rule (tuned on AECV-Bench split A only, scripts/aecv_escalate.py; held-out split B: doors 50%, windows 42%, beating
every published frontier model on both, 70% of plans escalated, $0.022/plan vs $0.031 for Gemini alone):
  gate    a plan escalates only if big (long side >= 1200 px) or in an unfamiliar style (style_conf < 0.70)
  door    unsure if >= 1 door detection scores in [0.20, 0.55)      (borderline symbols)
  window  unsure if >= 3 window detections score in [0.15, 0.50)
  bedroom unsure if the three room readers disagree by >= 2
  toilet  never escalated (PlanSight's three readers were better than the frontier model on the tuning split)

The prompt is AECV-Bench's counting prompt (AEC Foundry, arXiv 2601.04819), so a live call matches what the benchmark
measured.
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import re
import time

import httpx
from PIL import Image

MODEL = os.getenv("PLANSIGHT_ESCALATE_MODEL", "models/gemini-3.5-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
USD_PER_CALL = 0.0314  # AECV-Bench's measured mean cost per plan for Gemini 3.5 Flash

RULE = {"door": (0.20, 0.55, 1), "window": (0.15, 0.50, 3)}
BEDROOM_SPREAD = 2
GATE_SIDE, GATE_STYLE = 1200, 0.70  # door/window escalation only on big plans or unfamiliar drawing styles

PROMPT = """You are an expert floor-plan analyst trained to interpret architectural and engineering drawings in any language.

Your task is to fully understand the drawing first, then count the elements exactly according to the rules below, and then return ONLY the JSON: {"Door": int, "Window": int, "Space": int, "Bedroom": int, "Toilet": int}

1. Counting Rules and Interpretation Guidelines

You must follow these rules precisely—these match the logic used in preparing the ground-truth dataset. All counts MUST be based on the entire floor-plan image.

1.1 General
- Always consider the entire drawing before counting anything.
- Understand the entire drawing as a architectural and/or engineering drawing before counting anything.
Drawings may use different languages, symbols, and conventions; interpret them consistently.

1.2 Doors
- Count only openable doors (swing doors drawn with an arc).
- Do NOT count sliding closet doors, pantry sliders, or furniture-like wooden sliders on internal walls.
- Each leaf counts separately, i.e, a double-leaf door = 2 doors and a triple-leaf door = 3 doors, etc. and so on.
- Garage entrances are NOT doors.

1.3 Windows
- All sliding openings are counted as windows.
- French doors or large glazed openings are counted as windows, NOT doors.
- Multiple adjacent windows (or sliding units) without a gap between them count as ONE single window group.
- Tiny toilet windows must be counted even if very small.
- Garage entrances are NOT windows.

1.4 Spaces / Rooms
- Count all enclosed spaces, even if unlabeled.
- Partnerships of adjacent but separated spaces (e.g., WC next to Bath) are counted individually.

1.5 Bedrooms
A space labeled "Bedroom,","Chambre," "Zimmer," "Camera," etc., or equivalent should be counted as a bedroom.

1.6 Toilets
- The following labels all count as toilet units, each counted individually:
WC, W.C., Bath, Bain, Douche, Shower, SDB, Bathroom, Toilet, etc.
- Lavatory are not counted as toilets.

Make sure your counts follow all the rules above."""


def style_conf(dets) -> float:
    """Mean of the 10 most confident door/window scores: low = a drawing style the detector hasn't seen."""
    top = sorted((s for c, s in dets if c in ("door", "window")), reverse=True)[:10]
    return sum(top) / len(top) if top else 0.0


def unsure_kinds(dets, room_voters: dict | None = None, long_side: int | None = None) -> list[str]:
    """dets: [(cls, conf), ...] at conf >= 0.05. room_voters: {"bedroom": [counts of the 3 readers]}.
    long_side: plan's long side in px; with it, a plan escalates only if it is big or in an unfamiliar style."""
    out = []
    gated = long_side is None or long_side >= GATE_SIDE or style_conf(dets) < GATE_STYLE
    for kind, (lo, hi, n) in RULE.items():
        if gated and sum(1 for c, s in dets if c == kind and lo <= s < hi) >= n:
            out.append(kind)
    v = [x for x in (room_voters or {}).get("bedroom", []) if isinstance(x, int)]
    if gated and v and max(v) - min(v) >= BEDROOM_SPREAD:
        out.append("bedroom")
    return out


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY")) and os.getenv("PLANSIGHT_ESCALATE", "1") not in ("0", "false") \
        and os.getenv("PLANSIGHT_NO_LLM", "") not in ("1", "true")


def frontier_counts(image: Image.Image | str, retries: int = 4) -> dict:
    """One Gemini 3.5 Flash read of the whole plan -> {"Door", "Window", "Space", "Bedroom", "Toilet", "_ms", "_usd"}."""
    # Send the original file at full resolution, as AECV-Bench did: downscaling to JPEG cost most door arcs in a
    # 22-plan live check (doors right 2/22 vs 10/22 for the benchmark's own run of the same model).
    if isinstance(image, str):
        raw = open(image, "rb").read()
        mime = "image/png" if image.lower().endswith(".png") else "image/jpeg"
    else:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "PNG")
        raw, mime = buf.getvalue(), "image/png"
    schema = {"type": "OBJECT", "properties": {k: {"type": "INTEGER"} for k in ("Door", "Window", "Space", "Bedroom", "Toilet")},
              "required": ["Door", "Window", "Space", "Bedroom", "Toilet"]}
    body = {"contents": [{"role": "user", "parts": [
        {"text": PROMPT}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema}}
    t0, delay = time.perf_counter(), 2.0
    for _ in range(retries):
        try:
            r = httpx.post(URL.format(model=MODEL), headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=body,
                           timeout=120)
            if r.status_code == 200:
                text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
                m = re.search(r"\{.*\}", text, re.S)
                d = json.loads(m.group(0)) if m else {}
                out = {k: int(d[k]) for k in ("Door", "Window", "Space", "Bedroom", "Toilet") if
                       isinstance(d.get(k), (int, float))}
                out["_ms"] = round((time.perf_counter() - t0) * 1000)
                out["_usd"] = USD_PER_CALL
                return out
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        except httpx.TransportError:
            pass
        time.sleep(delay + random.random())
        delay *= 2
    raise RuntimeError("Gemini: retries exhausted")
