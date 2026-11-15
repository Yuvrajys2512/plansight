"""Aiven Postgres (+ pgvector): answer cache, question/cost log, reviewer corrections, sheet search.

Everything is optional: without DATABASE_URL every call is a cheap no-op and the demo still works.
One persistent connection is shared (guarded by a lock) because the Modal app and the Aiven service sit in
different regions and a fresh TLS handshake per request would add ~0.5 s. A failure trips a 60 s circuit
breaker so a database outage never slows the demo down.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_LOCK = threading.Lock()
_CONN = None
_DOWN_UNTIL = 0.0
_SCHEMA = Path(__file__).with_name("schema.sql")


def enabled() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _connect():
    import psycopg
    conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5, autocommit=True)
    conn.execute(_SCHEMA.read_text(encoding="utf-8"))
    return conn


@contextmanager
def connection():
    """Yield a live connection, or None when Postgres is not configured / temporarily down."""
    global _CONN, _DOWN_UNTIL
    if not enabled() or time.monotonic() < _DOWN_UNTIL:
        yield None
        return
    with _LOCK:
        try:
            if _CONN is None or _CONN.closed:
                _CONN = _connect()
            yield _CONN
        except Exception:
            _DOWN_UNTIL = time.monotonic() + 60
            try:
                if _CONN is not None:
                    _CONN.close()
            except Exception:
                pass
            _CONN = None
            raise


def _run(fn, default=None):
    try:
        with connection() as conn:
            return default if conn is None else fn(conn)
    except Exception:
        return default


def _background(fn) -> None:
    if enabled():
        threading.Thread(target=_run, args=(fn,), daemon=True).start()


SOLVER_VERSION = "2026-11-15-gemma-live"  # bump when answers change, so the cache never serves an outdated answer


def cache_key(path: str, question: str) -> str:
    return hashlib.sha256((SOLVER_VERSION + "\0" + path.strip() + "\0" + question.strip().casefold()).encode()).hexdigest()


def cached_answer(path: str, question: str):
    def q(conn):
        row = conn.execute("SELECT answer FROM answer_cache WHERE cache_key=%s", (cache_key(path, question),)).fetchone()
        return row[0] if row else None
    return _run(q)


def save_answer(path: str, question: str, answer: dict) -> None:
    payload = json.dumps(answer)
    _background(lambda conn: conn.execute(
        """INSERT INTO answer_cache(cache_key,drawing_path,question,answer) VALUES (%s,%s,%s,%s)
           ON CONFLICT(cache_key) DO UPDATE SET answer=EXCLUDED.answer, created_at=now()""",
        (cache_key(path, question), path, question, payload)))


def log_question(path: str, question: str, result: dict) -> None:
    """One row per question asked: what answered it, what it cost, what a frontier model would have cost."""
    row = (path, question, result.get("solver"), bool(result.get("abstained")), bool(result.get("cached")),
           None if result.get("abstained") else json.dumps(result.get("value")),
           float(result.get("cost_usd") or 0.0), float(result.get("naive_cost_usd") or 0.0),
           float(result.get("latency_ms") or 0.0), len(result.get("evidence") or []))
    _background(lambda conn: conn.execute(
        """INSERT INTO question_log(drawing_path,question,solver,abstained,cached,answer,cost_usd,naive_cost_usd,
           latency_ms,evidence_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", row))


def save_correction(plan: str, kind: str, bbox: list[float], action: str) -> None:
    """Reviewer corrections (rejected / added evidence boxes): the next detector training labels."""
    _background(lambda conn: conn.execute(
        "INSERT INTO corrections(plan,kind,bbox,action) VALUES (%s,%s,%s,%s)", (plan, kind, bbox, action)))


def stats() -> dict:
    def q(conn):
        n, answered, cached, cost, naive, latency = conn.execute(
            """SELECT count(*), count(*) FILTER (WHERE NOT abstained), count(*) FILTER (WHERE cached),
                      coalesce(sum(cost_usd),0), coalesce(sum(naive_cost_usd),0), coalesce(avg(latency_ms),0)
               FROM question_log""").fetchone()
        corrections = conn.execute("SELECT count(*) FROM corrections").fetchone()[0]
        by_solver = dict(conn.execute(
            "SELECT coalesce(solver,'none'), count(*) FROM question_log GROUP BY 1 ORDER BY 2 DESC").fetchall())
        return {"enabled": True, "questions": n, "answered": answered, "cached": cached,
                "cost_usd": float(cost), "naive_cost_usd": float(naive), "mean_latency_ms": float(latency),
                "corrections": corrections, "by_solver": by_solver, "store": "Aiven PostgreSQL"}
    return _run(q, default={"enabled": False})


def search_drawings(embedding: list[float], limit: int = 5):
    """Cosine nearest-neighbour lookup; caller supplies a 384-dimensional text embedding."""
    if len(embedding) != 384:
        raise ValueError("embedding must contain 384 values")
    def q(conn):
        rows = conn.execute("""SELECT id,source,image_url,sheet_text,1-(embedding <=> %s::vector) AS score
            FROM drawings WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s""",
            (json.dumps(embedding), json.dumps(embedding), max(1, min(limit, 50)))).fetchall()
        return [{"id": r[0], "source": r[1], "image_url": r[2], "sheet_text": r[3], "score": float(r[4])} for r in rows]
    return _run(q, default=[])
