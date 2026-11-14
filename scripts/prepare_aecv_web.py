"""Copy AECV plans.json and create compact web thumbnails from its source image paths."""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"D:\Junction\runs\aecv-report\plans.json")
DEST = ROOT / "web" / "public" / "aecv"

def main() -> None:
    plans = json.loads(SOURCE.read_text(encoding="utf-8"))
    (DEST / "img").mkdir(parents=True, exist_ok=True)
    (DEST / "plans.json").write_text(json.dumps(plans, separators=(",", ":")), encoding="utf-8")
    missing = []
    for plan, data in plans.items():
        source = Path(data["image"])
        if not source.is_file():
            missing.append((plan, str(source)))
            continue
        with Image.open(source) as image:
            data["image_width"], data["image_height"] = image.size
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image.convert("RGB").save(DEST / "img" / f"{plan}.jpg", "JPEG", quality=86, optimize=True)
    print(f"prepared {len(plans)-len(missing)}/{len(plans)} plans; missing={len(missing)}")
    if missing:
        print("first missing:", missing[:3])

if __name__ == "__main__":
    main()
