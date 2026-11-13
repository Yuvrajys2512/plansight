"""Paths and settings shared by every module. Both work lanes import from here; only Lane A edits it.

The dataset is gitignored and lives only in the main checkout. A git worktree (e.g. the Codex lane at
D:/Junction-codex) points at it with PLANSIGHT_DATA in its own .env.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")

DATA_ROOT = Path(os.getenv("PLANSIGHT_DATA") or REPO / "junction-dataset")
QUESTIONS = DATA_ROOT / "questions.jsonl"
RUNS = REPO / "runs"  # eval outputs (gitignored)


def resolve(path: str) -> Path:
    """Dataset path as written in questions.jsonl ("data/<source>/<file>") -> absolute path on disk."""
    p = Path(path)
    return p if p.is_absolute() else DATA_ROOT / p


def source_of(path: str) -> str:
    """'data/swiss_dwellings/x.pdf' -> 'swiss_dwellings'."""
    parts = Path(path).parts
    return parts[parts.index("data") + 1] if "data" in parts else parts[0]
