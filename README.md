# PlanSight

**Ask a construction drawing anything in plain English: get the answer, the exact spot on the sheet it came from,
and what the question cost, in fractions of a cent.**

Built in 40 hours at Junction 2026 for Stoa's **Make Blueprints Talk** challenge by team **Single Thread**
("the only human on the team").

**Live demo:** https://yuvrajys2512--plansight.us-east.modal.run (CPU only, may take ~5 s to wake up)

---

## The problem, measured

Site engineers spend hours a day hunting through drawings, and general-purpose AI fails on them. We checked this on
**AECV-Bench** (arXiv 2601.04819): 120 real floor plans with the published answers of ~30 frontier models.
**Across all 120 plans, no frontier model counts doors or windows right more than 43% of the time.** Frontier models are great at *reading*
("CHAMBRE", "Bed 1") and bad at *counting symbols*. A bigger model next year doesn't fix a perception problem.

## The approach: cheap first, verify always

PlanSight never sends a whole drawing to a big model when a parser, a detector or OCR can answer. Every answer comes
with evidence boxes on the sheet, so a human can check it in seconds and correct it with one click.

```
question (any of 7+ languages)
   │
   ▼
Router ── template bank / English parser ($0) ── Gemma fallback for unseen phrasings
   │
   ├─▶ IFC / BIM models ........ ifcopenshell facts (counts, areas, volumes) ......... $0, exact
   ├─▶ Swiss vector plans ...... PyMuPDF geometry + labels .......................... $0, exact
   ├─▶ Schedule sheets ......... table extraction + row lookup ...................... ~$0
   └─▶ Raster floor plans
          ├─ symbols (doors, windows, toilets, sinks...) → fine-tuned YOLO11 (ONNX, CPU)
          └─ rooms (bedrooms, WCs...) → vote of 3 readers:
                 OCR room-label lexicon  +  rooms detector  +  NVIDIA Nemotron 3.5 Super VL
   │
   ▼
answer + evidence boxes on the sheet + cost of the question  →  reviewer clicks to reject / add  →  feedback log
```

## Results

**Stoa dataset** (~127k questions across 5 sources):

| Source | Accuracy | Cost / question |
|---|---|---|
| swiss_dwellings (4,000-question sample, all languages) | **99.5%** | $0 |
| ifc_models | **99.7%** | $0 |
| cubicasa5k objects (CubiCasa **test** split; detectors trained on train split only) | toilet 92, sink 86, shower/bath 77, door 69, window 49 | ~$0.00003 |
| opening_design schedule sheets (numeric answers) | 83% | ~$0.001 |
| Multilingual router (held-out) | 99.8% | $0 for 87% of questions |
| ifc_bench | not handled yet | – |

**AECV-Bench, held-out split B** (60 plans we never tuned on; frontier numbers are the published AECV results):

| System | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| Gemini 3.5 Flash | 43 | 38 | 85 | 93 | 65% | $0.031 |
| Claude Fable 5 | 42 | 33 | 87 | 93 | 64% | $0.077 |
| GPT-5.5 | 35 | 32 | 78 | 92 | 59% | $0.224 |
| Nemotron 3.5 Super VL alone | 13 | 7 | 55 | 82 | 39% | $0.0002 |
| **PlanSight** | **43** | **38** | 80 | 85 | **62%** | **$0.0005** |

**Frontier-level accuracy at 1/60 to 1/450 of the cost, and every count is boxed on the plan.** On 31 plan/question
pairs all three frontier models above are wrong and PlanSight is right. Full table: `runs/aecv-report/report.md`
(regenerate with `scripts/aecv_report.py`).

## How Nemotron's role was found (the eval loop)

| Step | Result | Decision |
|---|---|---|
| Nemotron whole-plan counting, v0 | 45.4% on CubiCasa dev set (door 7.5, window 5) | baseline |
| + chain-of-thought / 2× upscale / tiling | 31.7% / 45.0% / 29.2% | all worse → symbols go to a fine-tuned detector |
| Detector proposes, Nemotron classifies each crop | split A door 33→40, but **held-out B door 43→33** | overfit → dropped |
| Nemotron reads room labels on the whole plan, as 1 of 3 voters | **bedrooms 77→85% on held-out B** | **kept** |

Nemotron does what it's good at (reading a whole plan) and stays out of what it's bad at (counting small symbols).
The demo shows each voter's count, which one was used and why, plus Nemotron's own cost and latency.

## Sponsor tech, and what each one actually does

- **NVIDIA Nemotron 3.5 Super VL**: whole-plan room-label reader, one of three voters for bedrooms/toilets. Self-hosted
  (NVFP4) on Verda via vLLM. Visible in the demo's "How PlanSight got N" trace.
- **Verda**: RTX PRO 6000 GPU that self-hosted Nemotron, trained both YOLO11 detectors and ran every eval. See
  [`docs/VERDA.md`](docs/VERDA.md).
- **Gemma (Gemma 4 31B)**: router fallback. It maps questions in phrasings or languages the $0 template bank hasn't seen onto a solver
  template (`plansight/router/gemma.py`), cached so it stays off the hot path.
- **OpenAI Codex**: built the eval harness, the CubiCasa OCR solver, the demo API, the web UI and the Frontier vs PlanSight
  view in a parallel git-worktree lane. Log and evidence: [`CODEX_LOG.md`](CODEX_LOG.md), `docs/codex/`.
- **Aiven PostgreSQL (+ pgvector)**: the system of record. Answer cache (a repeat question costs $0), a log of every
  question (solver, cost, latency, evidence count) and every reviewer correction (rejected / added boxes, the next
  detector training labels). `/api/stats` reads it live and the demo header shows "N questions answered · $X total vs $Y
  frontier · N corrections". One persistent connection, background writes and a circuit breaker keep the demo fast if the
  DB is slow (`plansight/store/postgres.py`).
- **Cloudinary**: every sheet is uploaded once as the exact PNG we render, so evidence boxes map 1:1. Per answer,
  Cloudinary URL transformations produce **zoomed crops of each evidence region** (shown under the answer) and one
  **shareable evidence sheet** with every region outlined, a single link a site engineer can send to a colleague. No
  server-side image work (`plansight/media/cloudinary.py`). The UI was scaffolded with `create-cloudinary-react`.
- **Modal**: hosts the public demo (FastAPI + React UI + ONNX detectors, CPU, scales to zero) and stores reviewer
  corrections on a Modal volume.

## Run it locally

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv -r requirements.txt
copy .env.example .env                     # keys are optional; PLANSIGHT_NO_LLM=1 runs without any
cd web; npm install; npm run build; cd ..
$env:PLANSIGHT_NO_LLM="1"; .venv\Scripts\python.exe -m uvicorn plansight.api.app:app --port 8765
# open http://127.0.0.1:8765
.venv\Scripts\python.exe -m pytest -q      # 64 tests
```

Not in the repo: the Stoa dataset (10 GB, from the challenge page) and the detector weights `models/*.onnx`
(~80 MB each; trained on Verda, see `docs/VERDA.md`).

## Repo map

- `plansight/api/app.py`: FastAPI (`/api/drawings`, `/api/ask`, `/api/render`, `/api/feedback`)
- `plansight/solvers/`: `swiss.py`, `ifc.py`, `cubicasa.py` (detectors), `cubicasa_text.py`, `room_labels.py`
- `plansight/router/`: multilingual question → template (English parser, template bank, Gemma)
- `plansight/vlm/`: Nemotron client (self-hosted / OpenRouter / NVIDIA Build, retries, disk cache)
- `plansight/detect/`: CubiCasa SVG → YOLO labels, ONNX inference, evaluation
- `plansight/sheets/`: schedule-sheet table QA
- `plansight/eval/`: eval harness over the Stoa dataset
- `scripts/aecv_*.py`: AECV-Bench pipeline and report
- `deploy/modal_app.py`: Modal deployment · `web/`: Vite + React UI

## Credits and data

- Stoa "Make Blueprints Talk" dataset (Junction 2026).
- AECV-Bench, AEC Foundry (arXiv 2601.04819), used for evaluation and the comparison view.
- CubiCasa5K (Zenodo 2613548, CC BY-NC-SA 4.0); detectors were trained on its official train split only.
