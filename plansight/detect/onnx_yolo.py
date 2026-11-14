"""Minimal YOLO (ultralytics export, no NMS in graph) runner on onnxruntime: no torch needed at inference.

Output of the exported graph: (1, 4 + nc, N) with rows cx, cy, w, h (letterboxed input pixels) then class scores.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from plansight.config import REPO

MODELS = REPO / "models"
Image.MAX_IMAGE_PIXELS = None


@dataclass
class Det:
    cls: str
    conf: float
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in original image pixels


class Detector:
    def __init__(self, onnx_path: Path):
        import onnxruntime as ort

        meta = json.loads(onnx_path.with_suffix(".json").read_text(encoding="utf-8"))
        self.names: list[str] = meta["names"]
        self.imgsz: int = meta["imgsz"]
        self.thresholds: dict[str, float] = meta.get("thresholds", {})
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        self._lock = threading.Lock()

    def _letterbox(self, im: np.ndarray):
        h, w = im.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nh, nw = round(h * r), round(w * r)
        im = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA if r < 1 else cv2.INTER_LINEAR)
        top, left = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        canvas[top:top + nh, left:left + nw] = im
        return canvas, r, left, top

    def __call__(self, image: str | Path | Image.Image, conf: float = 0.05, iou: float = 0.5) -> list[Det]:
        im = Image.open(image) if not isinstance(image, Image.Image) else image
        arr = np.asarray(im.convert("RGB"))
        lb, r, dx, dy = self._letterbox(arr)
        x = lb.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self._lock:
            out = self.sess.run(None, {self.inp: x})[0][0]  # (4+nc, N)
        boxes, scores = out[:4].T, out[4:].T
        cls = scores.argmax(1); sc = scores[np.arange(len(cls)), cls]
        keep = sc >= conf
        boxes, cls, sc = boxes[keep], cls[keep], sc[keep]
        if not len(sc):
            return []
        xywh = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2, boxes[:, 2], boxes[:, 3]], 1)
        idx = cv2.dnn.NMSBoxesBatched(xywh.tolist(), sc.tolist(), cls.tolist(), conf, iou)
        H, W = arr.shape[:2]
        dets = []
        for i in np.array(idx).reshape(-1):
            x0, y0, w, h = xywh[i]
            x0 = (x0 - dx) / r; y0 = (y0 - dy) / r
            dets.append(Det(self.names[int(cls[i])], float(sc[i]),
                            (max(0.0, x0), max(0.0, y0), min(W, x0 + w / r), min(H, y0 + h / r))))
        return sorted(dets, key=lambda d: -d.conf)


def tiled(det: Detector, image: Image.Image, scale: float = 2.0, conf: float = 0.05, iou: float = 0.5,
          overlap: float = 0.2) -> list[Det]:
    """Upscale by `scale`, run the detector on imgsz-sized tiles (with overlap), map back, merge with class-wise NMS.

    Small symbols (windows in dense plans) cover more input pixels than in the single letterboxed pass.
    """
    im = image.convert("RGB")
    W, H = im.size
    big = im.resize((round(W * scale), round(H * scale)), Image.LANCZOS) if scale != 1 else im
    BW, BH = big.size
    t = det.imgsz
    step = int(t * (1 - overlap))
    xs = list(range(0, max(BW - t, 0) + 1, step)) or [0]
    ys = list(range(0, max(BH - t, 0) + 1, step)) or [0]
    if xs[-1] + t < BW:
        xs.append(BW - t)
    if ys[-1] + t < BH:
        ys.append(BH - t)
    raw: list[Det] = []
    for y in ys:
        for x in xs:
            tile = big.crop((x, y, min(x + t, BW), min(y + t, BH)))
            for d in det(tile, conf=conf, iou=iou):
                x0, y0, x1, y1 = d.bbox
                raw.append(Det(d.cls, d.conf, ((x0 + x) / scale, (y0 + y) / scale, (x1 + x) / scale, (y1 + y) / scale)))
    if not raw:
        return []
    xywh = [[d.bbox[0], d.bbox[1], d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]] for d in raw]
    idx = cv2.dnn.NMSBoxesBatched(xywh, [d.conf for d in raw], [det.names.index(d.cls) for d in raw], conf, iou)
    return sorted((raw[i] for i in np.array(idx).reshape(-1)), key=lambda d: -d.conf)


@lru_cache(maxsize=4)
def load(name: str) -> Detector | None:
    """models/<name>.onnx (+ <name>.json with names, imgsz, per-kind thresholds); None if not downloaded."""
    p = MODELS / f"{name}.onnx"
    return Detector(p) if p.exists() else None
