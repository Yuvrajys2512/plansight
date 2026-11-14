"""Capture local P3 evidence views from the running API for the Codex log."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "codex"
BASE = "http://127.0.0.1:8000"


def get_json(url: str):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


drawings = get_json(f"{BASE}/api/drawings")
for source in ("swiss_dwellings", "ifc_models", "cubicasa5k"):
    drawing = next(item for item in drawings if item["source"] == source)
    payload = json.dumps({"path": drawing["path"], "question": drawing["sample_question"]}).encode()
    request = urllib.request.Request(f"{BASE}/api/ask", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        answer = json.loads(response.read())
    assert not answer.get("abstained") and answer.get("evidence"), (source, answer)
    page_path = answer["evidence"][0]["file"]
    query = urllib.parse.urlencode({"path": page_path, "page": 0})
    with urllib.request.urlopen(f"{BASE}/api/render?{query}") as response:
        page = Image.open(BytesIO(response.read())).convert("RGB")
    meta = get_json(f"{BASE}/api/meta?{query}")
    sx, sy = page.width / meta["width"], page.height / meta["height"]

    scale = min(1.0, 1400 / page.width, 1100 / page.height)
    if scale < 1:
        page = page.resize((round(page.width * scale), round(page.height * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (max(page.width, 900), page.height + 76), "#f2f5f3")
    canvas.paste(page, ((canvas.width - page.width) // 2, 76))
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((0, 0, canvas.width, 75), fill="#123f38")
    font = ImageFont.load_default()
    title = f"{source.replace('_', ' ').upper()}  ·  {answer['value']} {answer.get('unit') or ''}  ·  {len(answer['evidence'])} evidence regions"
    draw.text((18, 13), "PLANSIGHT  /  P3 EVIDENCE CHECK", font=font, fill="#d3f59a")
    draw.text((18, 43), title[:110], font=font, fill="white")
    ox, oy = (canvas.width - page.width) // 2, 76
    for index, evidence in enumerate(answer["evidence"]):
        color = (255, 61, 35, 245)
        if evidence.get("polygon"):
            points = [(ox + x * sx * scale, oy + y * sy * scale) for x, y in evidence["polygon"]]
            draw.polygon(points, fill=(187, 255, 38, 55), outline=color, width=3)
        else:
            x0, y0, x1, y1 = evidence["bbox"]
            box = (ox + x0 * sx * scale, oy + y0 * sy * scale, ox + x1 * sx * scale, oy + y1 * sy * scale)
            draw.rectangle(box, fill=(187, 255, 38, 48), outline=color, width=3)
        x0, y0, _, _ = evidence["bbox"]
        label = (evidence.get("label") or f"Evidence {index + 1}")[:50]
        label_x, label_y = ox + x0 * sx * scale, oy + y0 * sy * scale
        draw.text((label_x + 2, max(oy, label_y - 13)), label, font=font, fill="#b32918", stroke_width=2, stroke_fill="white")
    output = OUT / f"p3-{source}.png"
    canvas.save(output)
    print(f"{output.name}: {answer['value']} {answer.get('unit') or ''}, {len(answer['evidence'])} regions")
