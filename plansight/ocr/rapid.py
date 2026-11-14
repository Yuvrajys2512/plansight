"""CPU OCR using RapidOCR, with JSON results cached by image content."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from plansight.config import REPO


@dataclass(frozen=True)
class OCRToken:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


_ENGINE = None
_ENGINE_LOCK = Lock()
_HASHES: dict[str, tuple[int, int, str]] = {}
_HASH_LOCK = Lock()


def _engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                from rapidocr_onnxruntime import RapidOCR

                _ENGINE = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    return _ENGINE


def _cache_path(image_path: Path) -> Path:
    stat = image_path.stat()
    key = str(image_path.resolve())
    with _HASH_LOCK:
        cached = _HASHES.get(key)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            digest = cached[2]
        else:
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            _HASHES[key] = (stat.st_mtime_ns, stat.st_size, digest)
    return REPO / "cache" / "ocr" / f"{digest}.json"


def read_text(image_path: Path) -> list[OCRToken]:
    """Return recognized text and pixel boxes, loading/writing the on-disk cache."""
    cache_path = _cache_path(image_path)
    if cache_path.exists():
        try:
            rows = json.loads(cache_path.read_text(encoding="utf-8"))
            return [OCRToken(row["text"], tuple(row["bbox"]), float(row["confidence"])) for row in rows]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    result, _elapsed = _engine()(str(image_path))
    tokens = []
    for box, text, confidence in result or []:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        tokens.append(OCRToken(str(text), (min(xs), min(ys), max(xs), max(ys)), float(confidence)))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"text": token.text, "bbox": token.bbox, "confidence": token.confidence} for token in tokens]
    temp_path = cache_path.with_suffix(f".{id(tokens)}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(cache_path)
    return tokens
