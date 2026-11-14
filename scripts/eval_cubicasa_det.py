"""Count accuracy of the CubiCasa detectors against the Junction gold answers (runs on the GPU box).

    python eval_cubicasa_det.py objects /data/runs/cubicasa_m1280/weights/best.pt /data/out/yolo gold.json
    python eval_cubicasa_det.py rooms   /data/runs/rooms/weights/best.pt          /data/out/yolo_rooms gold.json

Tunes one confidence threshold per question kind on the CubiCasa *val* split, then reports accuracy on the *test*
split (plans never seen in training), so the headline number is honest. Writes thresholds.json next to the weights.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import OBJECT_KINDS, ROOM_KINDS  # noqa: E402

GRID = [round(0.05 * i, 2) for i in range(2, 19)]


def predict(model, img_dir: Path, imgsz: int):
    out = {}
    paths = sorted(img_dir.glob("*.png"))
    for i in range(0, len(paths), 16):
        for p, r in zip(paths[i:i + 16], model.predict([str(x) for x in paths[i:i + 16]], imgsz=imgsz, conf=0.05,
                                                       iou=0.5, max_det=600, verbose=False)):
            names = r.names
            out[p.stem] = [(names[int(c)], float(s)) for c, s in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist())]
    return out


def main(which, weights, data, gold_path, imgsz=1280):
    kinds = OBJECT_KINDS if which == "objects" else {k: (k,) for k in (*ROOM_KINDS, "floor")}
    gold = json.loads(Path(gold_path).read_text())
    model = YOLO(weights)
    preds = {s: predict(model, Path(data) / "images" / s, int(imgsz)) for s in ("val", "test")}

    def acc(split, kind, t):
        ok = n = 0
        for name, dets in preds[split].items():
            g = gold.get(name, {}).get(kind)
            if g is None:
                continue
            v = sum(1 for c, s in dets if c in kinds[kind] and s >= t)
            n += 1; ok += v == g
        return ok, n

    thr, rows = {}, []
    for kind in kinds:
        best = max(GRID, key=lambda t: acc("val", kind, t)[0])
        thr[kind] = best
        vo, vn = acc("val", kind, best); to, tn = acc("test", kind, best)
        rows.append((kind, best, vo / max(vn, 1), to, tn))
    tot_ok = sum(r[3] for r in rows); tot_n = sum(r[4] for r in rows)
    print(f"| kind | thr | val acc | TEST acc | n |\n|---|---|---|---|---|")
    for k, t, va, to, tn in rows:
        print(f"| {k} | {t} | {100 * va:.1f}% | **{100 * to / max(tn, 1):.1f}%** | {tn} |")
    print(f"| ALL | | | **{100 * tot_ok / tot_n:.1f}%** | {tot_n} |")
    Path(weights).with_name("thresholds.json").write_text(json.dumps(thr, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
