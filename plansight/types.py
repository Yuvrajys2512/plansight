"""Shared result types. Every answer carries the evidence a human needs to verify it."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    """A region on a drawing that supports the answer.

    bbox is in the coordinate space of `file` page `page` (PDF points for PDFs, pixels for raster images;
    origin top-left), so the UI can draw it directly on the rendered sheet. `polygon` (same space), when
    present, is the exact outline (e.g. a rotated room); the UI should draw it instead of the box.
    """

    file: str
    page: int
    bbox: tuple[float, float, float, float]
    label: str = ""
    polygon: list[tuple[float, float]] | None = None


@dataclass
class Answer:
    value: Any
    unit: str | None
    evidence: list[Evidence] = field(default_factory=list)
    method: str = "deterministic"  # deterministic | detector | vlm | llm
    cost_usd: float = 0.0
    confidence: float = 1.0
    explanation: str = ""
    # Human-review hints for counts: {"low", "high", "likely": [evidence indices counted but borderline],
    # "possible": [[x0, y0, x1, y1, score], ...] near-miss candidates not counted, "reason": str}. None when sure.
    review: dict | None = None

    def to_dict(self) -> dict:
        return _plain(asdict(self))


def _plain(x):
    """Convert numpy scalars (from the ONNX detectors) to plain Python so the dict is JSON-safe."""
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if hasattr(x, "item") and type(x).__module__ == "numpy":
        return x.item()
    return x
