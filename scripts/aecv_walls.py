"""Window-on-wall feature for cached AECV detections: does each window box sit in a wall?

    python scripts/aecv_walls.py <det cache name>    ->  runs/detcache/<name>.walls.json

Wall mask = the raster_scene recipe (dark strokes that survive a morphological opening). For every window/door box
(conf >= 0.1) we look just past both ends of its long axis: a window drawn in a wall has wall pixels on BOTH sides.
support = min(wall fraction beyond end 1, wall fraction beyond end 2), in [0, 1].
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402


def wall_mask(gray):
    h, w = gray.shape
    thr = min(110, int(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0] * 0.8))
    mask = (gray < thr).astype(np.uint8)
    k = max(3, round(max(h, w) / 330))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    return mask


def support(mask, b):
    H, W = mask.shape
    x0, y0, x1, y1 = b
    bw, bh = x1 - x0, y1 - y0
    L = max(bw, bh)
    e = max(3.0, 0.25 * L)
    if bw >= bh:  # horizontal opening: look left and right
        cy0, cy1 = y0, y1
        regs = [(x0 - e, cy0, x0, cy1), (x1, cy0, x1 + e, cy1)]
    else:
        regs = [(x0, y0 - e, x1, y0), (x0, y1, x1, y1 + e)]
    fr = []
    for a0, b0, a1, b1 in regs:
        a0, b0, a1, b1 = int(max(0, a0)), int(max(0, b0)), int(min(W, a1)), int(min(H, b1))
        fr.append(float(mask[b0:b1, a0:a1].mean()) if a1 > a0 and b1 > b0 else 0.0)
    return round(min(fr), 3)


def main():
    name = sys.argv[1]
    src = RUNS / "detcache" / name
    out = {}
    for line in src.open(encoding="utf-8"):
        r = json.loads(line)
        gray = cv2.imread(r["path"], cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        m = wall_mask(gray)
        out[r["plan"]] = {",".join(map(str, d[2:])): support(m, d[2:]) for d in r["dets"]
                          if d[0] in ("window", "door") and d[1] >= 0.1}
        del gray, m
    (RUNS / "detcache" / f"{name}.walls.json").write_text(json.dumps(out))
    print("plans", len(out))


if __name__ == "__main__":
    main()
