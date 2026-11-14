"""v2 detector dataset (runs on the Verda box): slicing-aided fine-tuning + style augmentation.

    python build_tiles_v2.py /data/out/yolo /data/out/yolo_v2

train = every full CubiCasa train image (symlink) + native-resolution tiles (1024-1280 px, 25% overlap; tiles with
>=1 door/window, plus ~10% of empty tiles) + an offline style-augmented copy of ~30% of the tiles (grayscale, line
thinning/thickening, blur, JPEG, gamma/contrast, noise/hatching) + style-augmented copies of ~15% of full images.
val/test = unchanged CubiCasa splits.
"""
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

SRC, DST = Path(sys.argv[1]), Path(sys.argv[2])
DOORWIN = {0, 1}  # window, door


def read_labels(p):
    out = []
    if p.exists():
        for line in p.read_text().split("\n"):
            if line.strip():
                c, *v = line.split()
                out.append((int(c), *map(float, v)))
    return out


def style_aug(im, rng):
    if rng.random() < 0.5:
        im = cv2.cvtColor(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    r = rng.random()
    k = np.ones((int(rng.choice([2, 3])),) * 2, np.uint8)
    if r < 0.3:
        im = cv2.erode(im, k)  # dark lines thicker
    elif r < 0.55:
        im = cv2.dilate(im, k)  # dark lines thinner
    if rng.random() < 0.4:
        im = cv2.GaussianBlur(im, (0, 0), rng.uniform(0.5, 1.5))
    if rng.random() < 0.6:
        gamma = rng.uniform(0.6, 1.6)
        lut = np.clip(((np.arange(256) / 255.0) ** gamma) * 255 * rng.uniform(0.8, 1.1) + rng.uniform(-15, 25), 0, 255)
        im = cv2.LUT(im, lut.astype(np.uint8))
    if rng.random() < 0.3:
        n = rng.normal(0, rng.uniform(4, 14), im.shape[:2])[..., None]
        im = np.clip(im.astype(np.float32) + n, 0, 255).astype(np.uint8)
    if rng.random() < 0.2:  # light diagonal hatching over a random region
        h, w = im.shape[:2]
        x0, y0 = int(rng.integers(0, w // 2)), int(rng.integers(0, h // 2))
        x1, y1 = x0 + int(rng.integers(w // 6, w // 2)), y0 + int(rng.integers(h // 6, h // 2))
        ov = im.copy()
        s = int(rng.integers(8, 20))
        for t in range(-(y1 - y0), x1 - x0, s):
            cv2.line(ov, (x0 + t, y0), (x0 + t + (y1 - y0), y1), (150, 150, 150), 1)
        mask = np.zeros(im.shape[:2], bool)
        mask[y0:y1, x0:x1] = True
        im = np.where(mask[..., None], np.minimum(ov, im), im)
    q = int(rng.integers(30, 91))
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def tiles_for(W, H, t):
    step = int(t * 0.75)
    xs = list(range(0, max(W - t, 0) + 1, step)) or [0]
    ys = list(range(0, max(H - t, 0) + 1, step)) or [0]
    if xs[-1] + t < W:
        xs.append(W - t)
    if ys[-1] + t < H:
        ys.append(H - t)
    return [(x, y) for y in ys for x in xs]


def one(name):
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    labs = read_labels(SRC / "labels/train" / f"{name}.txt")
    im = cv2.imread(str(SRC / "images/train" / f"{name}.png"), cv2.IMREAD_COLOR)
    if im is None:
        return 0, 0, 0
    H, W = im.shape[:2]
    n = na = nf = 0
    if rng.random() < 0.15 and max(W, H) <= 2500:  # style-augmented full image (small plans never get tiled)
        cv2.imwrite(str(DST / "images/train" / f"{name}_aug.jpg"), style_aug(im, rng), [cv2.IMWRITE_JPEG_QUALITY, 95])
        (DST / "labels/train" / f"{name}_aug.txt").write_text((SRC / "labels/train" / f"{name}.txt").read_text())
        nf = 1
    t = int(rng.integers(1024, 1281))
    if max(W, H) <= t * 1.25:
        return n, na, nf
    boxes = [(c, (cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H) for c, cx, cy, w, h in labs]
    for (x, y) in tiles_for(W, H, t):
        tw, th = min(t, W - x), min(t, H - y)
        lines, has_dw = [], False
        for c, a0, b0, a1, b1 in boxes:
            ix0, iy0, ix1, iy1 = max(a0, x), max(b0, y), min(a1, x + tw), min(b1, y + th)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            if (ix1 - ix0) * (iy1 - iy0) < 0.5 * (a1 - a0) * (b1 - b0):
                continue
            has_dw |= c in DOORWIN
            lines.append(f"{c} {((ix0 + ix1) / 2 - x) / tw:.6f} {((iy0 + iy1) / 2 - y) / th:.6f} "
                         f"{(ix1 - ix0) / tw:.6f} {(iy1 - iy0) / th:.6f}")
        if not has_dw and rng.random() > 0.10:
            continue
        crop = im[y:y + th, x:x + tw]
        base = f"{name}_t{x}_{y}"
        cv2.imwrite(str(DST / "images/train" / f"{base}.png"), crop)
        (DST / "labels/train" / f"{base}.txt").write_text("\n".join(lines))
        n += 1
        if rng.random() < 0.30:
            cv2.imwrite(str(DST / "images/train" / f"{base}_aug.jpg"), style_aug(crop, rng),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            (DST / "labels/train" / f"{base}_aug.txt").write_text("\n".join(lines))
            na += 1
    return n, na, nf


def main():
    for s in ("train", "val", "test"):
        for d in ("images", "labels"):
            (DST / d / s).mkdir(parents=True, exist_ok=True)
    for s in ("train", "val", "test"):  # full images: symlink to the same originals
        for p in (SRC / "images" / s).iterdir():
            q = DST / "images" / s / p.name
            if not q.exists():
                os.symlink(os.path.realpath(p), q)
            lp, lq = SRC / "labels" / s / f"{p.stem}.txt", DST / "labels" / s / f"{p.stem}.txt"
            if lp.exists() and not lq.exists():
                lq.write_text(lp.read_text())
    names = sorted(p.stem for p in (SRC / "images/train").iterdir())
    with ProcessPoolExecutor(28) as ex:
        res = list(ex.map(one, names, chunksize=8))
    print("full", len(names), "tiles", sum(r[0] for r in res), "aug tiles", sum(r[1] for r in res),
          "aug full", sum(r[2] for r in res), flush=True)
    (DST / "data.yaml").write_text((SRC / "data.yaml").read_text().replace(str(SRC), str(DST)))


if __name__ == "__main__":
    main()
