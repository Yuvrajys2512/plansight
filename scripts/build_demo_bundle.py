"""Build the small dataset bundle the public demo needs (the full dataset is 12 GB; the demo lists ~9 drawings).

    python scripts/build_demo_bundle.py [--extra data/x.pdf ...]
Writes deploy/bundle/junction-dataset/{questions.jsonl, data/...}: the drawings /api/drawings would list (plus their
IFC models) and every question about them, so /api/examples and /api/ask behave exactly as locally.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plansight.config import QUESTIONS, REPO, resolve  # noqa: E402

OUT = REPO / "deploy" / "bundle" / "junction-dataset"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()
    from plansight.api.app import _records
    from plansight.api.scene3d import build_scene, cache_paths

    items = [i for src in _records().values() for i in src]
    paths = {i["path"] for i in items} | {i["model_path"] for i in items if i.get("model_path")} | set(a.extra)
    print(f"{len(items)} demo drawings, {len(paths)} files")
    for item in items:
        if item["source"] not in ("swiss_dwellings", "ifc_models"):
            continue
        drawing = resolve(item["path"])
        model = resolve(item["model_path"]) if item.get("model_path") else None
        scene = build_scene(item["path"], drawing, ifc_model=model)
        _, glb = cache_paths(item["path"])
        print(f"  scene {item['path']}: {scene['kind']}" + (f", GLB {glb.stat().st_size / 1e6:.2f} MB" if glb.exists() else ""))
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    n = 0
    with QUESTIONS.open(encoding="utf-8") as src, (OUT / "questions.jsonl").open("w", encoding="utf-8") as dst:
        for line in src:
            if json.loads(line)["path"] in paths:
                dst.write(line)
                n += 1
    size = 0
    for p in sorted(paths):
        src = resolve(p)
        # solvers read same-stem siblings (Swiss: .dxf geometry + .png next to the .pdf)
        for s in sorted(src.parent.glob(src.stem + ".*")):
            d = OUT / Path(p).parent / s.name
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
            size += s.stat().st_size
            print(" ", d.relative_to(OUT))
    print(f"{n} questions, {size / 1e6:.1f} MB of drawings -> {OUT}")


if __name__ == "__main__":
    main()
