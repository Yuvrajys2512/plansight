from __future__ import annotations

import json
import mimetypes
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from plansight.config import DATA_ROOT, QUESTIONS, REPO, resolve, source_of
from plansight.eval.data import detect_language
from plansight.api.cost import naive_cost_usd
from plansight.solvers import route

app = FastAPI(title="PlanSight API")
ALLOWED_SOURCES = ("swiss_dwellings", "ifc_models", "cubicasa5k")


def _safe_path(raw: str) -> tuple[Path, str]:
    path = resolve(raw).resolve()
    try:
        rel = path.relative_to(DATA_ROOT.resolve()).as_posix()
    except ValueError:
        raise HTTPException(400, "Path must point inside the configured dataset")
    if not path.is_file():
        raise HTTPException(404, "Drawing not found")
    return path, rel if rel.startswith("data/") else f"data/{rel}"


def _page(path: Path, page: int):
    if page < 0:
        raise HTTPException(400, "page must be zero or greater")
    if path.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        if page >= len(doc):
            doc.close()
            raise HTTPException(404, "Page not found")
        return doc, doc[page]
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        if page != 0:
            raise HTTPException(404, "Raster drawings have only page 0")
        from PIL import Image
        return None, Image.open(path)
    raise HTTPException(415, "This file has no 2D sheet")


def _image_size(path: Path, page: int) -> tuple[int, int]:
    doc, obj = _page(path, page)
    if doc:
        rect = obj.rect
        size = (round(rect.width), round(rect.height))
        doc.close()
        return size
    return obj.size


def _title(raw: str) -> str:
    return Path(raw).stem.replace("_", " ").replace("-", " ").title()


def _equal(got, expected) -> bool:
    try:
        return abs(float(got) - float(expected)) <= 0.02 * max(abs(float(expected)), 1)
    except (TypeError, ValueError):
        return str(got).strip().casefold() == str(expected).strip().casefold()


@lru_cache(maxsize=1)
def _records() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {s: [] for s in ALLOWED_SOURCES}
    by_path: dict[str, list[dict]] = {}
    with QUESTIONS.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            src = source_of(row["path"])
            if src in grouped:
                by_path.setdefault(row["path"], []).append(row)
    # Keep the selection grounded in gold questions and only include solver-correct paths.
    for raw, rows in sorted(by_path.items(), key=lambda pair: (source_of(pair[0]), pair[0].lower().endswith(".ifc"), pair[0])):
        src = source_of(raw)
        if len(grouped[src]) >= 3:
            continue
        solver = route(raw)
        if solver is None:
            continue
        for row in rows:
            try:
                answer = solver.solve(raw, row["question"])
            except Exception:
                continue
            if answer is None or not _equal(answer.value, row.get("answer")):
                continue
            try:
                local, _ = _safe_path(raw)
            except HTTPException:
                continue
            # Prefer sheet-backed demonstrations for the viewer; model-only facts remain
            # available through /ask and are displayed as a model fact card.
            if local.suffix.lower() != ".ifc" and not answer.evidence:
                continue
            thumb = f"/api/render?path={raw}&page=0"
            model_path = raw.split("_plan-")[0] + ".ifc" if src == "ifc_models" and "_plan-" in raw else None
            grouped[src].append({"path": raw, "source": src, "title": _title(raw), "thumbnail_url": thumb,
                                 "sample_question": row["question"], "sample_answer": row.get("answer"),
                                 "solver": solver.name, "is_model": local.suffix.lower() == ".ifc",
                                 "model_path": model_path if model_path and resolve(model_path).is_file() else None})
            break
    return grouped


@app.get("/drawings")
@app.get("/api/drawings")
def drawings():
    return [item for source in ALLOWED_SOURCES for item in _records()[source]]


@app.get("/examples")
@app.get("/api/examples")
def examples(path: str):
    _safe_path(path)
    languages = {}
    with QUESTIONS.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["path"] == path and row.get("question") not in languages:
                languages[row["question"]] = detect_language(row["question"])
    if not languages:
        raise HTTPException(404, "No example questions for drawing")
    # The JSONL is not sorted by language, so promote a clear English sample and include multilingual input.
    questions = list(languages)
    english = next((q for q in questions if languages[q] == "en"), questions[0])
    non_english = next((q for q in questions if languages[q] not in ("en", "other")), None)
    ordered = [english] + ([non_english] if non_english and non_english != english else [])
    ordered.extend(q for q in questions if q not in ordered)
    return {"path": path, "examples": ordered[:5]}


@app.get("/meta")
@app.get("/api/meta")
def meta(path: str, page: int = 0):
    local, rel = _safe_path(path)
    if local.suffix.lower() == ".ifc":
        return {"path": rel, "page": 0, "model_fact": True, "width": None, "height": None}
    width, height = _image_size(local, page)
    units = "pt" if local.suffix.lower() == ".pdf" else "px"
    return {"path": rel, "page": page, "width": width, "height": height, "units": units,
            "model_fact": False}


@app.get("/render")
@app.get("/api/render")
def render(path: str, page: int = 0):
    local, _ = _safe_path(path)
    doc, obj = _page(local, page)
    if doc:
        pix = obj.get_pixmap(matrix=__import__("pymupdf").Matrix(1.5, 1.5), alpha=False)
        content = pix.tobytes("png")
        doc.close()
    else:
        import io
        buf = io.BytesIO()
        obj.convert("RGB").save(buf, format="PNG")
        content = buf.getvalue()
    return Response(content, media_type="image/png")


class AskRequest(BaseModel):
    path: str
    question: str


@app.post("/ask")
@app.post("/api/ask")
def ask(request: AskRequest):
    _, rel = _safe_path(request.path)
    start = time.perf_counter()
    try:
        solver = route(rel)
        if solver is None:
            return {"abstained": True, "reason": "No solver is registered for this drawing.",
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                    "naive_cost_usd": naive_cost_usd(question=request.question)}
        answer = solver.solve(rel, request.question)
    except Exception as exc:
        # Solver/data failures are treated as abstentions for a resilient demo endpoint.
        return {"abstained": True, "reason": f"The solver could not answer this question ({type(exc).__name__}).",
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                "naive_cost_usd": naive_cost_usd(question=request.question)}
    latency = round((time.perf_counter() - start) * 1000, 2)
    if answer is None:
        return {"abstained": True, "reason": "Not confident enough to return a supported answer.",
                "solver": solver.name, "latency_ms": latency,
                "naive_cost_usd": naive_cost_usd(question=request.question)}
    result = answer.to_dict()
    result.update({"solver": solver.name, "latency_ms": latency,
                   "naive_cost_usd": naive_cost_usd(question=request.question), "abstained": False})
    if rel.endswith(".ifc") and not answer.evidence and solver.name == "ifc":
        import re
        from plansight.solvers.ifc import facts, model_of
        match = re.search(r"Ifc[A-Za-z0-9]+", answer.explanation)
        kind = match.group(0) if match else "IFC entity"
        element = next((item for item in facts(model_of(rel))["elements"] if item["cls"] == kind), None)
        result["model_fact"] = {"element": kind, "guid": element.get("guid") if element else None,
                                "property": "model element count", "value": answer.value,
                                "element_name": element.get("name") if element else None}
    return result


_DIST = REPO / "web" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="web")
