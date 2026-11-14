"""NVIDIA Nemotron 3.5 Super VL client (OpenAI-compatible chat completions with images).

Backends, first configured wins (override with PLANSIGHT_NEMOTRON=self|openrouter|nvidia):
- self:       our own vLLM server on a Verda GPU (NEMOTRON_SELF_BASE_URL / _API_KEY / _MODEL)
- openrouter: nvidia/nemotron-3.5-super-vl:free (OPENROUTER_API_KEY; free tier is capped at 50 requests/day)
- nvidia:     NVIDIA Build (NVIDIA_API_KEY, NEMOTRON_MODEL)

Every call: exponential backoff on 429/5xx/timeouts, disk cache keyed by (backend model, image hash, prompt,
params) so re-running an eval costs $0, and a cost estimate. For the self-hosted server the cost is the GPU
rental time the request occupied, approximated by tokens at the measured throughput (see PRICE_* below).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image

from plansight.config import REPO

CACHE_DIR = REPO / "cache" / "vlm"
_lock = threading.Lock()

# $/1M tokens used for the cost meter. Self-hosted: RTX PRO 6000 at $2.81/h; tune after measuring throughput.
PRICE_IN = float(os.getenv("NEMOTRON_PRICE_IN_PER_M", "0.10"))
PRICE_OUT = float(os.getenv("NEMOTRON_PRICE_OUT_PER_M", "0.40"))


@dataclass
class Backend:
    name: str
    base_url: str
    api_key: str
    model: str


def backend() -> Backend:
    want = os.getenv("PLANSIGHT_NEMOTRON", "")
    opts = []
    if os.getenv("NEMOTRON_SELF_BASE_URL") and os.getenv("NEMOTRON_SELF_API_KEY"):
        opts.append(Backend("self", os.environ["NEMOTRON_SELF_BASE_URL"], os.environ["NEMOTRON_SELF_API_KEY"],
                            os.getenv("NEMOTRON_SELF_MODEL", "nemotron-3.5-super-vl")))
    if os.getenv("OPENROUTER_API_KEY"):
        opts.append(Backend("openrouter", "https://openrouter.ai/api/v1", os.environ["OPENROUTER_API_KEY"],
                            "nvidia/nemotron-3.5-super-vl:free"))
    if os.getenv("NVIDIA_API_KEY"):
        opts.append(Backend("nvidia", "https://integrate.api.nvidia.com/v1", os.environ["NVIDIA_API_KEY"],
                            os.getenv("NEMOTRON_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")))
    if want:
        opts = [b for b in opts if b.name == want]
    if not opts:
        raise RuntimeError("no Nemotron backend configured (NEMOTRON_SELF_*, OPENROUTER_API_KEY or NVIDIA_API_KEY)")
    return opts[0]


def encode_image(img: Image.Image | str | Path, max_side: int = 1536, quality: int = 90) -> str:
    """PIL image or path -> JPEG data URL, longest side capped (keeps tokens and cost down)."""
    im = Image.open(img) if isinstance(img, (str, Path)) else img
    im = im.convert("RGB")
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


@dataclass
class Reply:
    text: str
    reasoning: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    cached: bool
    backend: str


def _post(b: Backend, body: dict, retries: int = 6, timeout: float = 240) -> dict:
    delay = 2.0
    last = ""
    for _ in range(retries):
        try:
            r = httpx.post(f"{b.base_url}/chat/completions", json=body, timeout=timeout,
                           headers={"Authorization": f"Bearer {b.api_key}"})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f"Nemotron {last}")
        except httpx.TransportError as e:
            last = repr(e)
        time.sleep(delay + random.random())
        delay = min(delay * 2, 60)
    raise RuntimeError(f"Nemotron: retries exhausted ({last})")


def ask(prompt: str, images: list[str] | None = None, *, think: bool = False, max_tokens: int = 1024,
        temperature: float = 0.0, json_schema: dict | None = None, system: str | None = None) -> Reply:
    """One chat completion. `images` are data URLs from encode_image(). Cached on disk."""
    b = backend()
    content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": u}} for u in images or []]
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
    body: dict = {"model": b.model, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature}
    if b.name == "self":
        body["chat_template_kwargs"] = {"enable_thinking": think}
    elif b.name == "openrouter":
        body["reasoning"] = {"enabled": think}
    if json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": json_schema}}

    key = hashlib.sha256(json.dumps({"m": b.model, "body": body}, sort_keys=True).encode()).hexdigest()
    path = CACHE_DIR / key[:2] / f"{key}.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        return Reply(**{**d, "cached": True, "cost_usd": 0.0})

    t0 = time.perf_counter()
    resp = _post(b, body)
    ms = (time.perf_counter() - t0) * 1000
    msg = resp["choices"][0]["message"]
    u = resp.get("usage") or {}
    tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    cost = 0.0 if b.name == "openrouter" else (tin * PRICE_IN + tout * PRICE_OUT) / 1e6
    d = {"text": msg.get("content") or "", "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
         "tokens_in": tin, "tokens_out": tout, "cost_usd": cost, "latency_ms": ms, "cached": False, "backend": b.name}
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return Reply(**d)
