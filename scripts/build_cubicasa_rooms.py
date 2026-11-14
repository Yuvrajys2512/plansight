"""Room/floor detector dataset (model 2) from CubiCasa5K SVGs (runs on the Verda GPU box).

    python build_cubicasa_rooms.py /data/cubicasa5k /data/out

Classes: bedroom kitchen bathroom wc_room sauna balcony floor. A room box is its polygon's bbox; its classes come from
the annotator's name label (rules.py); a sauna is a "Space Sauna" room or a room containing a sauna stove (a stove
outside any room becomes its own small sauna box). Writes out/yolo_rooms/... and out/room_counts.json
(per plan: count per kind, to check against the Junction gold answers).
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import ROOM_KINDS, room_kinds  # noqa: E402
from svg_labels import parse  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
CLASSES = [*ROOM_KINDS, "floor"]


def _inside(pt, poly, bbox):
    x, y = pt
    if not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
        return False
    if not poly or len(poly) < 3:
        return True
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def one(args):
    folder, split, out = args
    folder = Path(folder)
    name = f"{folder.parent.name}-{folder.name}"
    o = Image.open(folder / "F1_original.png").size
    s = Image.open(folder / "F1_scaled.png").size
    items = parse((folder / "model.svg").read_text(encoding="utf-8"), o[0] / s[0], o[1] / s[1])
    W, H = o
    boxes = []  # (class, bbox)
    rooms = [i for i in items if i.cls.startswith("room:")]
    stoves = [((i.bbox[0] + i.bbox[2]) / 2, (i.bbox[1] + i.bbox[3]) / 2, i.bbox) for i in items if i.cls == "sauna_stove"]
    used = set()
    for r in rooms:
        kinds = room_kinds(r.text)
        has_stove = [j for j, (x, y, _) in enumerate(stoves) if _inside((x, y), r.polygon, r.bbox)]
        if r.svg_class.startswith("Space Sauna") or has_stove:
            kinds.add("sauna"); used.update(has_stove)
        for k in kinds:
            boxes.append((k, r.bbox))
    for j, (x, y, b) in enumerate(stoves):
        if j not in used:
            w, h = (b[2] - b[0]) * 1.5, (b[3] - b[1]) * 1.5
            boxes.append(("sauna", (x - w, y - h, x + w, y + h)))
    boxes += [("floor", i.bbox) for i in items if i.cls == "floor"]
    lines = []
    for c, (x0, y0, x1, y1) in boxes:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 - x0 >= 1 and y1 - y0 >= 1:
            lines.append(f"{CLASSES.index(c)} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
    dst = out / "yolo_rooms" / "images" / split / f"{name}.png"
    if not dst.exists():
        os.symlink(folder / "F1_original.png", dst)
    (out / "yolo_rooms" / "labels" / split / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
    counts = {k: sum(1 for c, _ in boxes if c == k) for k in CLASSES}
    return name, counts


def main(root, out):
    root, out = Path(root), Path(out)
    jobs = []
    for split in ("train", "val", "test"):
        for d in ("images", "labels"):
            (out / "yolo_rooms" / d / split).mkdir(parents=True, exist_ok=True)
        jobs += [(str(root / line.strip("/")), split, out) for line in (root / f"{split}.txt").read_text().split()]
    with ProcessPoolExecutor(12) as ex:
        counts = dict(ex.map(one, jobs, chunksize=16))
    (out / "yolo_rooms" / "data.yaml").write_text(
        f"path: {out / 'yolo_rooms'}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n"
        + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)))
    (out / "room_counts.json").write_text(json.dumps(counts))
    print(len(counts), "plans")


if __name__ == "__main__":
    main(*sys.argv[1:3])
