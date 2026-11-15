"""PlanSight public demo on Modal: FastAPI API + built web UI + fine-tuned ONNX detectors, CPU only.

    .venv\\Scripts\\modal.exe deploy deploy/modal_app.py
Prereqs: `python scripts/build_demo_bundle.py` (demo drawings -> deploy/bundle) and `npm run build` in web/.
Scales to zero when idle. Before peer review set KEEP_WARM=1 (env) and redeploy so the first visitor gets no cold start.
LLM calls are off by default (PLANSIGHT_NO_LLM=1): the demo answers with detectors, parsers and cached Nemotron
replies only, so it costs nothing per visit and needs no LLM keys on Modal. DATABASE_URL (Aiven) and CLOUDINARY_URL
are passed as a secret if set in .env. Warm the Cloudinary map first (uploads each demo sheet once, writes
cache/cloudinary.json, which ships with the image): run the API locally and open /api/drawings.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
IGNORE = ["**/__pycache__/**", "**/*.pyc"]

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libxcb1", "libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender1")
    .pip_install("pymupdf", "ifcopenshell", "ezdxf", "opencv-python-headless", "numpy", "pillow", "fastapi",
                 "python-dotenv", "shapely", "httpx", "onnxruntime", "rapidocr-onnxruntime", "pydantic",
                 "psycopg[binary]", "cloudinary", "trimesh", "mapbox-earcut")
    # rapidocr depends on full opencv-python (needs X11); swap in the headless build that provides the same cv2
    .run_commands("pip uninstall -y opencv-python && pip install --force-reinstall --no-deps opencv-python-headless")
    .env({"PLANSIGHT_DATA": "/root/junction-dataset", "PLANSIGHT_NO_LLM": "1", "PLANSIGHT_GEMMA_ROUTER": "1", "GEMMA_RETRIES": "2", "GEMMA_TIMEOUT_S": "25", "PYTHONPATH": "/root"})
    .add_local_dir(ROOT / "deploy" / "bundle" / "junction-dataset", "/root/junction-dataset")
    .add_local_dir(ROOT / "models", "/root/models")
    .add_local_dir(ROOT / "cache", "/root/cache", ignore=IGNORE)
    .add_local_dir(ROOT / "web" / "dist", "/root/web/dist")
    .add_local_dir(ROOT / "plansight", "/root/plansight", ignore=IGNORE)
)

app = modal.App("plansight", image=image)
# Only the two add-on keys travel to Modal (read from the local .env at deploy time; never the LLM keys).
# Without them the app still runs: Aiven/Cloudinary calls become no-ops.
from dotenv import dotenv_values  # noqa: E402

_env = {**dotenv_values(ROOT / ".env"), **os.environ}
addon_keys = modal.Secret.from_dict({k: _env[k] for k in ("DATABASE_URL", "CLOUDINARY_URL", "ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "GEMINI_API_KEY") if _env.get(k)})
# runs/ (feedback.jsonl from the click-to-reject UI) survives container restarts:
#   python -m modal volume get plansight-runs feedback.jsonl .
runs = modal.Volume.from_name("plansight-runs", create_if_missing=True)


@app.function(cpu=2.0, memory=4096, timeout=300, min_containers=1 if os.getenv("KEEP_WARM") == "1" else 0,
              scaledown_window=600, max_containers=1, volumes={"/root/runs": runs}, secrets=[addon_keys])
@modal.concurrent(max_inputs=16)
@modal.asgi_app(label="plansight")
def web():
    from plansight.api.app import app as fastapi_app

    @fastapi_app.middleware("http")
    async def commit_runs(request, call_next):  # persist each feedback write to the volume
        resp = await call_next(request)
        if request.url.path == "/api/feedback":
            runs.commit()
        return resp

    return fastapi_app
