"""Shared result types. Every answer carries the evidence a human needs to verify it."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    """A region on a drawing that supports the answer.

    bbox is in the coordinate space of `file` page `page` (PDF points, origin top-left),
    so the UI can draw it directly on the rendered sheet.
    """

    file: str
    page: int
    bbox: tuple[float, float, float, float]
    label: str = ""


@dataclass
class Answer:
    value: Any
    unit: str | None
    evidence: list[Evidence] = field(default_factory=list)
    method: str = "deterministic"  # deterministic | vlm | llm
    cost_usd: float = 0.0
    confidence: float = 1.0
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
