"""Build the CubiCasa5K detector dataset from the public SVG annotations (runs on the Verda GPU box).

    python build_cubicasa_yolo.py /data/cubicasa5k /data/out

Writes:
  out/labels/<sub>-<num>.json   every labelled item (objects, rooms with name text, floors) in F1_original pixels
  out/yolo/{images,labels}/{train,val,test}/<sub>-<num>.(png|txt)   YOLO dataset, CubiCasa's official splits
  out/yolo/data.yaml
  out/stats.json                class histogram, scale sanity check

Images are F1_original.png, which is byte-identical to the Junction dataset PNG, so inference coordinates match.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from svg_labels import parse  # noqa: E402  (copied next to this script on the box)

DET_CLASSES = ["window", "door", "opening", "toilet", "sink", "double_sink", "shower", "shower_cab", "bathtub"]


def det_class(item) -> str | None:
    if item.cls == "shower" and item.svg_class == "FixedFurniture ShowerCab":
        return "shower_cab"
    return item.cls if item.cls in DET_CLASSES else None


def one(args):
    folder, split, out = args
    folder = Path(folder)
    sub, num = folder.parent.name, folder.name
    name = f"{sub}-{num}"
    try:
        o = Image.open(folder / "F1_original.png").size
        s = Image.open(folder / "F1_scaled.png").size
        sx, sy = o[0] / s[0], o[1] / s[1]
        items = parse((folder / "model.svg").read_text(encoding="utf-8"), sx, sy)
    except Exception as e:  # noqa: BLE001
        return name, split, None, repr(e)[:200]
    W, H = o
    (out / "labels" / f"{name}.json").write_text(json.dumps({
        "name": name, "split": split, "size": [W, H], "scale": [sx, sy],
        "items": [{"cls": i.cls, "svg_class": i.svg_class, "bbox": [round(v, 1) for v in i.bbox],
                   "text": i.text, "polygon": [[round(x, 1), round(y, 1)] for x, y in i.polygon] if i.polygon else None}
                  for i in items]}, ensure_ascii=False), encoding="utf-8")
    lines = []
    for i in items:
        c = det_class(i)
        if c is None:
            continue
        x0, y0, x1, y1 = max(0, i.bbox[0]), max(0, i.bbox[1]), min(W, i.bbox[2]), min(H, i.bbox[3])
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        lines.append(f"{DET_CLASSES.index(c)} {(x0 + x1) / 2 / W:.6f} {(y0 + y1) / 2 / H:.6f} {(x1 - x0) / W:.6f} {(y1 - y0) / H:.6f}")
    img_dst = out / "yolo" / "images" / split / f"{name}.png"
    if not img_dst.exists():
        os.symlink(folder / "F1_original.png", img_dst)
    (out / "yolo" / "labels" / split / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
    return name, split, Counter(det_class(i) or i.cls.split(":")[0] for i in items), abs(sx / sy - 1)


def main(root: str, out: str):
    root, out = Path(root), Path(out)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    jobs = []
    for split in ("train", "val", "test"):
        for d in ("images", "labels"):
            (out / "yolo" / d / split).mkdir(parents=True, exist_ok=True)
        for line in (root / f"{split}.txt").read_text().split():
            jobs.append((str(root / line.strip("/")), split, out))
    hist, bad, aniso = Counter(), [], []
    per_split = Counter()
    with ProcessPoolExecutor(28) as ex:
        for name, split, c, extra in ex.map(one, jobs, chunksize=16):
            if c is None:
                bad.append((name, extra)); continue
            hist.update(c); per_split[split] += 1
            if extra > 0.01:
                aniso.append((name, round(extra, 4)))
    (out / "yolo" / "data.yaml").write_text(
        f"path: {out / 'yolo'}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        f"names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(DET_CLASSES)))
    stats = {"plans": per_split, "classes": hist, "failed": bad[:50], "n_failed": len(bad),
             "anisotropic_scale": aniso[:50], "n_aniso": len(aniso)}
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=dict))
    print(json.dumps(stats, indent=1, default=dict)[:3000])


if __name__ == "__main__":
    main(*sys.argv[1:3])
