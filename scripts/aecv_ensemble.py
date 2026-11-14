"""Fuse two cached AECV detector runs (WBF-style): same-class boxes with IoU > thr are averaged (conf = mean),
unmatched boxes keep conf / 2.   python scripts/aecv_ensemble.py a.jsonl b.jsonl out.jsonl"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import RUNS  # noqa: E402

D = RUNS / "detcache"


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def fuse(da, db, thr=0.5):
    out, used = [], set()
    for c, s, *b in da:
        best, bj = 0, None
        for j, (c2, s2, *b2) in enumerate(db):
            if c2 == c and j not in used:
                v = iou(b, b2)
                if v > best:
                    best, bj = v, j
        if bj is not None and best > thr:
            used.add(bj); s2, b2 = db[bj][1], db[bj][2:]
            w = s + s2
            out.append([c, round((s + s2) / 2, 4), *[round((x * s + y * s2) / w, 1) for x, y in zip(b, b2)]])
        else:
            out.append([c, round(s / 2, 4), *b])
    out += [[c, round(s / 2, 4), *b] for j, (c, s, *b) in enumerate(db) if j not in used]
    return sorted(out, key=lambda d: -d[1])


def main():
    a = {json.loads(l)["plan"]: json.loads(l) for l in open(D / sys.argv[1], encoding="utf-8")}
    b = {json.loads(l)["plan"]: json.loads(l) for l in open(D / sys.argv[2], encoding="utf-8")}
    with open(D / sys.argv[3], "w", encoding="utf-8") as f:
        for n, r in a.items():
            f.write(json.dumps({**r, "dets": fuse(r["dets"], b[n]["dets"])}) + "\n")


if __name__ == "__main__":
    main()
