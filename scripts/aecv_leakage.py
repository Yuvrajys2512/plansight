"""Leakage audit: which AECV-Bench plans are CubiCasa5K images, and are any in our detector's train split?

dHash (16x16 grayscale, 256 bits) of every AECV plan vs every junction-dataset CubiCasa PNG; Hamming <= 20 = match.
Writes runs/aecv_leakage.json.
"""
import json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
ROOT = Path(__file__).resolve().parents[1]
AECV = Path(os.environ.get("AECV_DIR", r"C:\Users\YUVRAJ~1\AppData\Local\Temp\aecv\repo\data\Use Case 1 - Object Counting\1 - Full Datasets"))
CC = ROOT / "junction-dataset" / "data" / "cubicasa5k"


def dhash(p):
    im = Image.open(p)
    im.draft("L", (512, 512))
    im = im.convert("L").resize((17, 16), Image.LANCZOS)
    a = np.asarray(im, dtype=np.int16)
    return np.packbits((a[:, 1:] > a[:, :-1]).ravel()), im.size


def main():
    aecv = {}
    for d in sorted(AECV.iterdir()):
        pngs = [p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
        if pngs:
            aecv[d.name] = dhash(pngs[0])[0]
    ids = list(aecv)
    A = np.stack([aecv[i] for i in ids])  # n x 32 bytes
    split = {}
    for s in ("train", "val", "test"):
        for line in (ROOT / "plansight/detect/splits" / f"{s}.txt").read_text().split():
            sub, num = line.strip("/").split("/")
            split[f"{sub}-{num}"] = s
    files = sorted(p for p in CC.glob("*.png") if not p.name.startswith("snap-"))
    best = {i: (999, None) for i in ids}
    for k in range(0, len(files), 500):
        batch = files[k:k + 500]
        H = np.stack([dhash(p)[0] for p in batch])
        dist = np.unpackbits(A[:, None, :] ^ H[None, :, :], axis=2).sum(2)
        for r, i in enumerate(ids):
            c = int(dist[r].argmin())
            if dist[r, c] < best[i][0]:
                best[i] = (int(dist[r, c]), batch[c].stem)
        print(f"{k + len(batch)}/{len(files)}", flush=True)
    matches = {}
    for i in ids:
        d, name = best[i]
        if d <= 20:
            matches[i] = {"cubicasa": name, "hamming": d, "split": split.get(name, "unknown")}
    out = {
        "threshold": 20, "n_aecv": len(ids), "n_cubicasa": len(files),
        "matches": matches,
        "train_overlap": sorted(i for i, m in matches.items() if m["split"] == "train"),
        "any_cubicasa_overlap": sorted(matches),
        "nearest": {i: {"cubicasa": best[i][1], "hamming": best[i][0]} for i in ids},
    }
    (ROOT / "runs" / "aecv_leakage.json").write_text(json.dumps(out, indent=1))
    print("matches", len(matches), "train overlap", len(out["train_overlap"]))
    for i, m in matches.items():
        print(i, m)


if __name__ == "__main__":
    main()
