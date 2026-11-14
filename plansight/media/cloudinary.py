"""Cloudinary: sheet hosting + on-the-fly evidence media via URL transformations.

Each sheet is uploaded once as the exact PNG that /api/render serves, so evidence boxes map 1:1 onto it
(PDF boxes are in points and get scaled by RENDER_SCALE). Public IDs are remembered in cache/cloudinary.json,
so answering a question never uploads anything. Per answer we then build, with zero server-side image work:
  - a zoomed crop of every evidence region (c_crop + upscale), shown as thumbnails under the answer;
  - one shareable "evidence sheet" URL with every region highlighted, to send to a colleague on site.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

from plansight.config import REPO

RENDER_SCALE = 1.5  # must match /api/render for PDFs
_MAP_PATH = REPO / "cache" / "cloudinary.json"
_LOCK = threading.Lock()
_MAP: dict[str, dict] | None = None
MAX_HIGHLIGHTS = 30


def _config():
    value = os.getenv("CLOUDINARY_URL", "")
    if not value:
        return None
    parsed = urlparse(value)
    return parsed.hostname, parsed.username, parsed.password


def enabled() -> bool:
    return _config() is not None


def _map() -> dict[str, dict]:
    global _MAP
    if _MAP is None:
        try:
            _MAP = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _MAP = {}
    return _MAP


def lookup(key: str) -> dict | None:
    """{public_id, width, height} for an uploaded sheet, or None."""
    return _map().get(key) if enabled() else None


def upload_png(key: str, png: bytes, public_id: str, width: int, height: int) -> dict | None:
    """Upload a rendered sheet once; later calls return the remembered entry."""
    cfg = _config()
    if not cfg:
        return None
    with _LOCK:
        if key in _map():
            return _map()[key]
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(cloud_name=cfg[0], api_key=cfg[1], api_secret=cfg[2], secure=True)
        result = cloudinary.uploader.upload(png, public_id=public_id, resource_type="image", overwrite=True,
                                            tags=["plansight"])
        entry = {"public_id": result["public_id"], "width": width, "height": height}
        _map()[key] = entry
        try:
            _MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
            _MAP_PATH.write_text(json.dumps(_map(), indent=1), encoding="utf-8")
        except OSError:
            pass  # read-only filesystem (deployed): keep it in memory
        return entry


def transformed_url(public_id: str, transformation: str = "", fmt: str = "jpg") -> str | None:
    cfg = _config()
    if not cfg:
        return None
    transform = f"{transformation}/" if transformation else ""
    return f"https://res.cloudinary.com/{cfg[0]}/image/upload/{transform}{public_id}.{fmt}"


def _px(entry: dict, bbox, scale: float) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (float(v) * scale for v in bbox)
    w, h = entry["width"], entry["height"]
    x0, x1 = sorted((max(0, min(w, x0)), max(0, min(w, x1))))
    y0, y1 = sorted((max(0, min(h, y0)), max(0, min(h, y1))))
    return round(x0), round(y0), max(round(x1), round(x0) + 1), max(round(y1), round(y0) + 1)


def evidence_crop_url(entry: dict, bbox, *, scale: float = 1.0, padding: int = 40) -> str | None:
    """Zoomed crop around one evidence region, padded for context and upscaled to a readable thumbnail."""
    x0, y0, x1, y1 = _px(entry, bbox, scale)
    x, y = max(0, x0 - padding), max(0, y0 - padding)
    w = min(entry["width"] - x, x1 - x0 + 2 * padding)
    h = min(entry["height"] - y, y1 - y0 + 2 * padding)
    return transformed_url(entry["public_id"], f"c_crop,x_{x},y_{y},w_{w},h_{h}/c_fit,w_320,h_240/f_auto,q_auto")


def _marker() -> str | None:
    """A tiny translucent red PNG, uploaded once; each evidence box is this marker scaled to the box + a red border."""
    entry = _map().get("__marker__")
    if entry:
        return entry["public_id"]
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 59, 48, 40)).save(buf, "PNG")
    entry = upload_png("__marker__", buf.getvalue(), "plansight/marker", 8, 8)
    return entry["public_id"] if entry else None


def highlight_url(entry: dict, boxes, *, scale: float = 1.0, border: int = 5) -> str | None:
    """The whole sheet with every evidence region outlined in red: one shareable image URL, rendered by Cloudinary."""
    marker = _marker()
    if not marker:
        return None
    layer_id = marker.replace("/", ":")
    layers = []
    for bbox in list(boxes)[:MAX_HIGHLIGHTS]:
        x0, y0, x1, y1 = _px(entry, bbox, scale)
        layers.append(f"l_{layer_id}/c_scale,w_{x1 - x0},h_{y1 - y0}/bo_{border}px_solid_rgb:FF3B30/"
                      f"fl_layer_apply,g_north_west,x_{max(0, x0 - border)},y_{max(0, y0 - border)}")
    if not layers:
        return None
    return transformed_url(entry["public_id"], "/".join(layers) + "/c_limit,w_2000/f_auto,q_auto")
