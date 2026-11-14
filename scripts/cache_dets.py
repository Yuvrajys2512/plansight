"""Cache raw object detections (conf >= 0.05) for a CubiCasa split, plain and tiled, to tune counting offline.

    python scripts/cache_dets.py --split val --variants plain,tiled2
Writes runs/detcache/<split>-<variant>.jsonl: {"path", "size": [W, H], "dets": [[cls, conf, x0, y0, x1, y1], ...]}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS, resolve  # noqa: E402
from plansight.detect.evaluate import plans  # noqa: E402
from plansight.detect.onnx_yolo import load, tiled  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="val")
    ap.add_argument("--model", default="cubicasa_objects")
    ap.add_argument("--variants", default="plain,tiled2")
    a = ap.parse_args()
    det = load(a.model)
    out = RUNS / "detcache"
    out.mkdir(parents=True, exist_ok=True)
    ps = sorted(p for p in plans(a.split) if resolve(p).exists())
    for v in a.variants.split(","):
        f = out / f"{a.split}-{a.model}-{v}.jsonl"
        done = {json.loads(l)["path"] for l in f.open(encoding="utf-8")} if f.exists() else set()
        t0 = time.time()
        with f.open("a", encoding="utf-8") as fh:
            for i, p in enumerate(ps):
                if p in done:
                    continue
                im = Image.open(resolve(p)).convert("RGB")
                ds = det(im, conf=0.05) if v == "plain" else tiled(det, im, scale=float(v[5:] or 2), conf=0.05)
                fh.write(json.dumps({"path": p, "size": im.size,
                                     "dets": [[d.cls, round(float(d.conf), 4), *(round(float(x), 1) for x in d.bbox)] for d in ds]}) + "\n")
                if i % 50 == 0:
                    print(v, i, len(ps), f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
