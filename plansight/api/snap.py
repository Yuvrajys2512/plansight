"""'Snap a plan': clean up a phone photo (or any uploaded plan image) so the CubiCasa pipeline can read it.

Steps: decode → find the sheet of paper and undo the perspective (like a document scanner) → flatten uneven
lighting → save as a PNG under data/cubicasa5k/snap-<id>.png so the router, detector and solver work unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from plansight.config import DATA_ROOT, RUNS

SNAP_DIR = DATA_ROOT / "data" / "cubicasa5k"
SESSIONS = RUNS / "snaps"


def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_sheet(img: np.ndarray) -> np.ndarray | None:
    """Corners of the largest 4-sided bright region (the paper), or None if the image already is the sheet."""
    import cv2
    h, w = img.shape[:2]
    scale = 900 / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        a = cv2.contourArea(c)
        if a < 0.25 * area or a > 0.97 * area:
            continue
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return _order(approx.reshape(4, 2).astype(np.float32) / scale)
    return None


def clean(img: np.ndarray) -> tuple[np.ndarray, bool]:
    import cv2
    warped = False
    corners = find_sheet(img)
    if corners is not None:
        (tl, tr, br, bl) = corners
        W = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        H = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        M = cv2.getPerspectiveTransform(corners, np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32))
        img = cv2.warpPerspective(img, M, (W, H))
        warped = True
    # Flatten shadows / uneven light: divide each channel by a heavily blurred copy (background estimate).
    k = max(31, (max(img.shape[:2]) // 25) | 1)
    bg = cv2.medianBlur(cv2.resize(img, None, fx=.25, fy=.25), k // 4 | 1)
    bg = cv2.resize(bg, (img.shape[1], img.shape[0])).astype(np.float32) + 1
    flat = np.clip(img.astype(np.float32) / bg * 235, 0, 255).astype(np.uint8)
    # Detectors were trained on ~2000-2700 px sheets.
    h, w = flat.shape[:2]
    s = 2400 / max(h, w)
    if s < 1 or s > 1.6:
        flat = cv2.resize(flat, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    return flat, warped


def save_upload(data_url: str, session: str | None) -> dict:
    import cv2
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    if len(raw) > 15_000_000:
        raise ValueError("Image too large")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Not an image")
    out, warped = clean(img)
    sid = hashlib.sha1(raw).hexdigest()[:12]
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / f"snap-{sid}.png"
    cv2.imwrite(str(path), out)
    info = {"path": f"data/cubicasa5k/snap-{sid}.png", "width": out.shape[1], "height": out.shape[0],
            "warped": warped, "t": time.time()}
    if session:
        SESSIONS.mkdir(parents=True, exist_ok=True)
        (SESSIONS / f"{_safe_session(session)}.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def _safe_session(session: str) -> str:
    return "".join(ch for ch in session if ch.isalnum())[:32] or "x"


def latest(session: str) -> dict | None:
    p = SESSIONS / f"{_safe_session(session)}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
