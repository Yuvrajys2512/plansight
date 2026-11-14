"""Load a JSONL export of drawings/regions/facts into Aiven. Run after schema.sql."""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import psycopg

def load(source: Path) -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    count = 0
    with psycopg.connect(url) as conn, source.open(encoding="utf-8") as rows:
        conn.execute((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
        for line in rows:
            item = json.loads(line)
            conn.execute("INSERT INTO drawings(id,source,image_url,width,height,sheet_text,embedding,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s::vector,%s) ON CONFLICT(id) DO UPDATE SET image_url=EXCLUDED.image_url,width=EXCLUDED.width,height=EXCLUDED.height,sheet_text=EXCLUDED.sheet_text,embedding=EXCLUDED.embedding,metadata=EXCLUDED.metadata",
                (item["id"], item.get("source", ""), item.get("image_url"), item.get("width"), item.get("height"), item.get("sheet_text", ""), json.dumps(item["embedding"]) if item.get("embedding") is not None else None, json.dumps(item.get("metadata", {}))))
            conn.execute("DELETE FROM regions WHERE drawing_id=%s", (item["id"],))
            conn.execute("DELETE FROM facts WHERE drawing_id=%s", (item["id"],))
            for region in item.get("regions", []):
                conn.execute("INSERT INTO regions(drawing_id,bbox,label,kind,metadata) VALUES(%s,%s,%s,%s,%s)", (item["id"], region["bbox"], region.get("label", ""), region.get("kind", ""), json.dumps(region.get("metadata", {}))))
            for key, value in item.get("facts", {}).items():
                conn.execute("INSERT INTO facts(drawing_id,key,value) VALUES(%s,%s,%s)", (item["id"], key, json.dumps(value)))
            count += 1
    return count

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("jsonl", type=Path)
    print(f"loaded {load(parser.parse_args().jsonl)} drawings")
