"""Gemma 4 31B fallback (Google AI Studio) for questions the template bank doesn't match.

Strict contract: Gemma returns JSON {template, params}; we accept it only if the template and enum values
exist in the catalogue and every slot value occurs verbatim in the question (no hallucinated room names).
Responses are cached on disk, so repeat questions cost $0.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time

import httpx

from plansight.config import REPO
from plansight.router.english import CATALOG, SLOT_KEYS

MODEL = os.getenv("GEMMA_ROUTER_MODEL", "models/gemma-4-31b-it")
URL = "https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
CACHE = REPO / "cache" / "router" / "gemma.jsonl"
# AI Studio serves Gemma free; we book cost at typical hosted open-weight rates so the cost meter is honest.
PRICE_IN = float(os.getenv("GEMMA_PRICE_IN_PER_M", "0.10"))
PRICE_OUT = float(os.getenv("GEMMA_PRICE_OUT_PER_M", "0.30"))

_cache: dict[str, dict] | None = None
_lock = threading.Lock()

# one English example per template so the model sees the exact param shapes
_EXAMPLES = {
    "swiss": [
        ("How many doors (interior doors and entrance doors together) are drawn on this floor plan?",
         {"template": "count", "params": {"kind": "doors"}}),
        ("How many rooms labelled 'Schlafzimmer' are there on this floor?",
         {"template": "count_rooms_named", "params": {"name": "Schlafzimmer"}}),
        ("What is the net floor area of room 7.01 ('Balkon') in m²?",
         {"template": "room_area", "params": {"number": "7.01"}}),
        ("What is the net floor area of apartment B in m², summing all its rooms except balconies?",
         {"template": "apartment_area", "params": {"letter": "B"}}),
        ("What is the total net area in m² of all rooms labelled 'Bad' on this floor?",
         {"template": "total_area_named", "params": {"name": "Bad"}}),
        ("What is the total net floor area in m² of all numbered indoor rooms on this floor?",
         {"template": "total_indoor_area", "params": {}}),
    ],
    "ifc": [
        ("How many doors are there in the model 'FZK-Haus'?",
         {"template": "count", "params": {"kind": "doors", "model": "FZK-Haus"}}),
        ("How many light fixtures are shown on the floor plan of 'Erdgeschoss'?",
         {"template": "count", "params": {"kind": "lights", "storey": "Erdgeschoss"}}),
        ("What is the net floor area of the room 'Küche (6)' on 'Erdgeschoss', in m²?",
         {"template": "room_area", "params": {"room": "Küche (6)", "storey": "Erdgeschoss"}}),
        ("What is the total net floor area of all rooms (spaces) on '1.korrus', in m²?",
         {"template": "total_room_area", "params": {"storey": "1.korrus"}}),
        ("What is the total length of all walls on 'Level 1', in m?",
         {"template": "wall_length", "params": {"storey": "Level 1"}}),
        ("What is the total net volume of all slabs on 'P0', in m³?",
         {"template": "slab_volume", "params": {"storey": "P0"}}),
    ],
    "cubicasa": [
        ("How many separate WC rooms (toilet rooms marked WC) are on this floor plan?",
         {"template": "count", "params": {"kind": "wc_room"}}),
        ("How many toilet bowls (WC seats) are drawn on this floor plan?",
         {"template": "count", "params": {"kind": "toilet"}}),
    ],
}

_NOTES = {
    "swiss": "Swiss apartment floor plan. Counts are of drawn objects; areas are net floor areas from room labels.",
    "ifc": ("IFC building model or a floor plan rendered from it. Use `model` when the question is about the whole "
            "model, `storey` when it is about one floor/level/plan. kind 'sanitary' = sanitary fixtures/terminals, "
            "'lights' = light fixtures, 'rooms' = rooms/spaces, 'columns' = columns/pillars/posts, "
            "'slabs' are floors/decks/slabs (template slab_volume)."),
    "cubicasa": ("Finnish apartment floor plan. kinds: window, floor (storeys shown), toilet (WC seat/bowl), "
                 "sink (sinks + wash basins), shower_bath (showers + bathtubs), door, sauna, kitchen, bedroom, "
                 "bathroom (washrooms, not separate WCs), wc_room (separate WC rooms), balcony."),
}


def build_prompt(domain: str, question: str) -> str:
    cat = json.dumps(CATALOG[domain], ensure_ascii=False, indent=1)
    shots = "\n".join(f"Q: {q}\nA: {json.dumps(a, ensure_ascii=False)}" for q, a in _EXAMPLES[domain])
    return (
        "You route questions about construction drawings to a fixed set of templates. The question may be in any "
        "language. Reply with ONE JSON object {\"template\": ..., \"params\": {...}} and nothing else.\n"
        "Rules: use only the templates and enum values below; copy names, numbers and letters EXACTLY as they "
        "appear in the question (same spelling, case and punctuation, do not translate them, omit surrounding "
        "quote marks); if no template fits, reply {\"template\": null, \"params\": {}}.\n\n"
        f"Context: {_NOTES[domain]}\n\nTemplates (param -> allowed values or description):\n{cat}\n\n"
        f"Examples:\n{shots}\n\nQ: {question}\nA:"
    )


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is None:
        _cache = {}
        if CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = json.loads(line)
                    _cache[d["key"]] = d
    return _cache


def _call(prompt: str, retries: int = int(os.getenv("GEMMA_RETRIES", "6"))) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 256,
                                 "thinkingConfig": {"thinkingLevel": "minimal"}}}
    delay = 2.0
    for attempt in range(retries):
        try:
            r = httpx.post(URL.format(model=MODEL), headers={"x-goog-api-key": key}, json=body, timeout=float(os.getenv("GEMMA_TIMEOUT_S", "180")))
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Gemma HTTP {r.status_code}: {r.text[:200]}")
        except httpx.TransportError:
            pass
        if attempt == retries - 1:
            break
        time.sleep(delay + random.random())
        delay = min(delay * 2, 60)
    raise RuntimeError("Gemma: retries exhausted")


def ask(domain: str, question: str) -> dict:
    """Raw cached call: {'key', 'text', 'tokens_in', 'tokens_out', 'cost_usd', 'cached'}."""
    prompt = build_prompt(domain, question)
    k = hashlib.sha1(f"{MODEL}\n{prompt}".encode()).hexdigest()
    cache = _load_cache()
    if k in cache:
        return {**cache[k], "cached": True, "cost_usd": 0.0}
    resp = _call(prompt)
    parts = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = resp.get("usageMetadata", {})
    tin, tout = u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
    d = {"key": k, "domain": domain, "question": question, "text": text, "tokens_in": tin, "tokens_out": tout,
         "cost_usd": (tin * PRICE_IN + tout * PRICE_OUT) / 1e6}
    cache[k] = d
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    return {**d, "cached": False}


def _verbatim(val: str, question: str) -> str | None:
    """The question's own spelling of `val` (case/whitespace-insensitive), or None if it isn't there."""
    v = re.sub(r"\s+", " ", str(val)).strip().strip("'\"«»„“”‘’ ")
    if not v:
        return None
    m = re.search(r"\s+".join(map(re.escape, v.split(" "))), question, re.I)
    return m[0] if m else None


def validate(domain: str, question: str, text: str) -> tuple[str, dict] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m[0])
    except json.JSONDecodeError:
        return None
    t, params = d.get("template"), d.get("params") or {}
    spec = CATALOG[domain].get(t) if isinstance(t, str) else None
    if spec is None or not isinstance(params, dict):
        return None
    out = {}
    for k, v in params.items():
        if k not in spec or v in (None, ""):
            continue
        if isinstance(spec[k], list):
            if v not in spec[k]:
                return None
            out[k] = v
        elif k in SLOT_KEYS:
            vv = _verbatim(v, question)
            if vv is None:
                return None
            out[k] = vv
    required = {k for k in spec if k in ("kind", "name", "number", "letter", "room")}
    if domain == "ifc" and t != "count":
        required.add("storey")
    if not required <= out.keys():
        return None
    return t, out


def route(domain: str, question: str) -> tuple[tuple[str, dict] | None, float, bool]:
    """(route or None, cost_usd, cached)."""
    r = ask(domain, question)
    return validate(domain, question, r["text"]), r["cost_usd"], r["cached"]
