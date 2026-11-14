"""Cache raw detections (conf >= 0.05) and OCR tokens for the 120 AECV-Bench plans, so counting rules can be tuned
offline in seconds instead of re-running the detector.

    python scripts/aecv_cache.py <AECV-Bench repo> --what objects:plain,objects:tiled2,rooms:plain,ocr
Writes runs/detcache/aecv-<model>-<variant>.jsonl ({"plan", "path", "size", "dets": [[cls, conf, x0, y0, x1, y1]]})
and runs/detcache/aecv-ocr.jsonl ({"plan", "tokens": [[text, conf, x0, y0, x1, y1]]}). Resumable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
MODELS = {"objects": "cubicasa_objects", "objects_v2": "cubicasa_objects_v2", "rooms": "cubicasa_rooms"}


def aecv_plans(repo: Path):
    root = repo / "data/Use Case 1 - Object Counting/1 - Full Datasets"
    out = []
    for d in sorted(root.iterdir()):
        img = next(iter(sorted(d.glob("*.png")) + sorted(d.glob("*.jp*g"))), None)
        meta = d / "metadata.json"
        if img and meta.exists():
            out.append((d.name, str(img.resolve()), json.loads(meta.read_text(encoding="utf-8-sig"))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--what", default="objects:plain,objects:tiled2,rooms:plain,ocr")
    a = ap.parse_args()
    plans = aecv_plans(Path(a.repo))
    out = RUNS / "detcache"
    out.mkdir(parents=True, exist_ok=True)
    for what in a.what.split(","):
        f = out / ("aecv-ocr.jsonl" if what == "ocr" else f"aecv-{MODELS[what.split(':')[0]]}-{what.split(':')[1]}.jsonl")
        done = {json.loads(l)["plan"] for l in f.open(encoding="utf-8")} if f.exists() else set()
        t0 = time.time()
        with f.open("a", encoding="utf-8") as fh:
            for i, (name, path, _) in enumerate(plans):
                if name in done:
                    continue
                if what == "ocr":
                    from plansight.ocr import read_text

                    toks = read_text(Path(path))
                    rec = {"plan": name, "tokens": [[t.text, round(t.confidence, 3), *(round(v, 1) for v in t.bbox)]
                                                    for t in toks]}
                else:
                    from plansight.detect.onnx_yolo import load, sahi, tiled

                    model, variant = what.split(":")
                    det = load(MODELS[model])
                    im = Image.open(path).convert("RGB")
                    if variant == "plain":
                        ds = det(im, conf=0.05)
                    elif variant == "sahi":
                        ds = sahi(det, im, conf=0.05)
                    else:
                        ds = tiled(det, im, scale=float(variant[5:] or 2), conf=0.05)
                    rec = {"plan": name, "path": path, "size": im.size,
                           "dets": [[d.cls, round(float(d.conf), 4), *(round(float(x), 1) for x in d.bbox)]
                                    for d in ds]}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                if i % 20 == 0:
                    print(what, i, len(plans), f"{time.time() - t0:.0f}s", flush=True)
        print(what, "done", f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
