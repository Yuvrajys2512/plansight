"""Check every sponsor API/credential in .env. Prints status only, never secrets.

Run:  .venv/Scripts/python.exe scripts/check_access.py
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import httpx2 as httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
T = 20


def env(k: str) -> str:
    return (os.getenv(k) or "").strip()


def show(name: str, ok: bool | None, msg: str = "") -> None:
    icon = {True: "OK  ", False: "FAIL", None: "--  "}[ok]
    print(f"[{icon}] {name:22} {msg}")


def nvidia():
    k = env("NVIDIA_API_KEY")
    if not k:
        return show("NVIDIA Build", None, "NVIDIA_API_KEY not set")
    r = httpx.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {k}"}, timeout=T)
    if r.status_code != 200:
        return show("NVIDIA Build", False, f"HTTP {r.status_code} {r.text[:120]}")
    ids = [m["id"] for m in r.json().get("data", [])]
    nem = [i for i in ids if "nemotron" in i.lower()]
    vl = [i for i in nem if re.search(r"vl|vision|omni", i, re.I)]
    show("NVIDIA Build", True, f"{len(ids)} models, {len(nem)} nemotron")
    model = env("NEMOTRON_MODEL")
    if model not in ids:
        show("  Nemotron model", False, f"NEMOTRON_MODEL '{model}' not in catalogue; VL options:")
        for i in (vl or nem)[:12]:
            print(f"         - {i}")
        return
    # Real multimodal call: a 1x1 red PNG. Proves key + vision input + model ID all work.
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")
    h = {"Authorization": f"Bearer {k}"}
    body = {"model": model, "max_tokens": 20, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What colour is this image? One word."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}}]}]}
    r = httpx.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=h, json=body, timeout=120)
    if r.status_code == 200:
        show("  Nemotron VL call", True, f"{model.split('/')[-1]} -> {r.json()['choices'][0]['message']['content']!r:.40}")
    else:
        show("  Nemotron VL call", False, f"HTTP {r.status_code} {r.text[:120]}")
    g = env("GEMMA_MODEL")
    if g in ids:
        r = httpx.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=h, timeout=60, json={
            "model": g, "max_tokens": 5, "messages": [{"role": "user", "content": "Say OK"}]})
        show("  Gemma via NVIDIA", r.status_code == 200, g if r.status_code == 200 else f"HTTP {r.status_code}")


def verda_cloud():
    cid, sec = env("VERDA_CLIENT_ID"), env("VERDA_CLIENT_SECRET")
    if not (cid and sec):
        return show("Verda cloud API", None, "client id/secret not set")
    r = httpx.post("https://api.verda.com/v1/oauth2/token",
                   json={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}, timeout=T)
    if r.status_code != 200:
        return show("Verda cloud API", False, f"token HTTP {r.status_code}")
    b = httpx.get("https://api.verda.com/v1/balance",
                  headers={"Authorization": f"Bearer {r.json()['access_token']}"}, timeout=T).json()
    show("Verda cloud API", True, f"balance {b.get('amount')} {b.get('currency')}")


def verda_inference():
    k, url, model = env("VERDA_API_KEY"), env("VERDA_NEMOTRON_BASE_URL"), env("VERDA_NEMOTRON_MODEL")
    if not k:
        return show("Verda Nemotron", None, "VERDA_API_KEY not set")
    if not url:
        return show("Verda Nemotron", None, "key set; waiting for endpoint URL from Verda booth/Discord")
    r = httpx.post(url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {k}"},
                   json={"model": model, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 5}, timeout=60)
    show("Verda Nemotron", r.status_code == 200, f"HTTP {r.status_code} {r.text[:100] if r.status_code != 200 else ''}")


def modal():
    p = Path.home() / ".modal.toml"
    show("Modal", p.exists(), "token in ~/.modal.toml" if p.exists() else "run: modal token new")


def huggingface():
    k = env("HF_TOKEN")
    if not k:
        return show("Hugging Face", None, "HF_TOKEN not set")
    h = {"Authorization": f"Bearer {k}"}
    r = httpx.get("https://huggingface.co/api/whoami-v2", headers=h, timeout=T)
    if r.status_code != 200:
        return show("Hugging Face", False, f"whoami HTTP {r.status_code}")
    show("Hugging Face", True, f"user {r.json().get('name')}")
    models = [env("GEMMA_MODEL")] if env("GEMMA_MODEL") else []
    models += ["google/gemma-3-4b-it", "google/gemma-3-12b-it", "google/gemma-3n-E4B-it"]
    for m in dict.fromkeys(models):
        rr = httpx.head(f"https://huggingface.co/{m}/resolve/main/config.json", headers=h, timeout=T, follow_redirects=True)
        show(f"  Gemma {m.split('/')[-1]}"[:22], rr.status_code == 200,
             "license accepted" if rr.status_code == 200 else f"HTTP {rr.status_code} (accept license on model page)")


def aiven():
    url = env("DATABASE_URL")
    if not url:
        return show("Aiven Postgres", None, "DATABASE_URL not set")
    import psycopg
    try:
        with psycopg.connect(url, connect_timeout=15) as c:
            v = c.execute("select version()").fetchone()[0].split(",")[0]
            c.execute("create extension if not exists vector")
            pv = c.execute("select extversion from pg_extension where extname='vector'").fetchone()
            show("Aiven Postgres", True, f"{v}; pgvector {pv[0] if pv else 'MISSING'}")
    except Exception as e:
        show("Aiven Postgres", False, f"{type(e).__name__}: {str(e)[:120]}")


def cloudinary():
    url = env("CLOUDINARY_URL")
    if not url:
        return show("Cloudinary", None, "CLOUDINARY_URL not set")
    m = re.match(r"cloudinary://(\w+):([^@]+)@([\w-]+)", url)
    if not m:
        return show("Cloudinary", False, "CLOUDINARY_URL should look like cloudinary://KEY:SECRET@CLOUD")
    r = httpx.get(f"https://api.cloudinary.com/v1_1/{m.group(3)}/usage", auth=(m.group(1), m.group(2)), timeout=T)
    show("Cloudinary", r.status_code == 200, f"cloud {m.group(3)}, plan {r.json().get('plan') if r.status_code == 200 else r.status_code}")


def gemini():
    k = env("GEMINI_API_KEY")
    if not k:
        return show("Gemini", None, "GEMINI_API_KEY not set")
    r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": k}, timeout=T)
    n = len(r.json().get("models", [])) if r.status_code == 200 else 0
    show("Gemini", r.status_code == 200, f"{n} models" if n else f"HTTP {r.status_code}")


def elevenlabs():
    k = env("ELEVENLABS_API_KEY")
    if not k:
        return show("ElevenLabs", None, "ELEVENLABS_API_KEY not set")
    r = httpx.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": k}, timeout=T)
    show("ElevenLabs", r.status_code == 200, f"tier {r.json().get('tier')}" if r.status_code == 200 else f"HTTP {r.status_code}")


if __name__ == "__main__":
    for fn in (nvidia, verda_cloud, verda_inference, modal, huggingface, aiven, cloudinary, gemini, elevenlabs):
        try:
            fn()
        except Exception as e:  # keep going; one broken service shouldn't hide the rest
            show(fn.__name__, False, f"{type(e).__name__}: {str(e)[:120]}")
