"""Small, lazy Postgres adapter. The local demo remains usable without DATABASE_URL."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager


@contextmanager
def connection():
    url = os.getenv("DATABASE_URL")
    if not url:
        yield None
        return
    import psycopg
    with psycopg.connect(url, connect_timeout=3) as conn:
        yield conn


def cache_key(path: str, question: str) -> str:
    return hashlib.sha256((path.strip() + "\0" + question.strip().casefold()).encode()).hexdigest()


def cached_answer(path: str, question: str):
    try:
        with connection() as conn:
            if conn is None:
                return None
            row = conn.execute("SELECT answer FROM answer_cache WHERE cache_key=%s", (cache_key(path, question),)).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def save_answer(path: str, question: str, answer: dict) -> None:
    try:
        with connection() as conn:
            if conn is None:
                return
            conn.execute("""INSERT INTO answer_cache(cache_key,drawing_path,question,answer)
                VALUES (%s,%s,%s,%s) ON CONFLICT(cache_key) DO UPDATE SET answer=EXCLUDED.answer,
                created_at=now()""", (cache_key(path, question), path, question, json.dumps(answer)))
    except Exception:
        return


def search_drawings(embedding: list[float], limit: int = 5):
    """Cosine nearest-neighbour lookup; caller supplies a 384-dimensional text embedding."""
    if len(embedding) != 384:
        raise ValueError("embedding must contain 384 values")
    with connection() as conn:
        if conn is None:
            return []
        rows = conn.execute("""SELECT id,source,image_url,sheet_text,1-(embedding <=> %s::vector) AS score
            FROM drawings WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s""",
            (json.dumps(embedding), json.dumps(embedding), max(1, min(limit, 50)))).fetchall()
        return [{"id":r[0],"source":r[1],"image_url":r[2],"sheet_text":r[3],"score":float(r[4])} for r in rows]
