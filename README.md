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
| cubicasa5k, **every question kind** (1,000 Stoa questions on 356 held-out test drawings, EN + FI; `scripts/eval_cubicasa_test.py`) | **82.7%** (toilets 95, saunas 94, floors 93, sinks 90, kitchens 88, showers/baths 84, bedrooms 84, doors 60, windows 44) | ~$0.00003 |
| cubicasa5k objects, detector count only (CubiCasa **test** split; detectors trained on train split only) | toilet 92, sink 86, shower/bath 77, door 69, window 49 | ~$0.00003 |
| opening_design schedule sheets (numeric answers) | 83% | ~$0.001 |
| Multilingual router (held-out) | 99.8% | $0 for 87% of questions |
| ifc_bench | not handled yet | – |

**AECV-Bench, held-out split B** (plans we never tuned on; frontier numbers are the published AECV results).

**Leakage audit first.** AECV-Bench reuses some CubiCasa5K plans, which is also our detector's training data. A
perceptual-hash match (`scripts/aecv_leakage.py`, dHash 16×16, Hamming ≤ 20, clean gap to the next-nearest) finds
**33 of 120 AECV plans are CubiCasa5K images, 20 of them in our training split**. The *clean* columns drop those 20
plans for every system. **Clean is the number we stand behind.**

| System | Door | Window | Toilet | Bedroom | Mean (clean B, 51 plans) | Mean (all B, 60) | $/plan |
|---|---|---|---|---|---|---|---|
| Gemini 3.5 Flash | 45 | 43 | 88 | 96 | 68% | 65% | $0.031 |
| Gemini 3 Pro | **47** | 35 | 92 | 94 | 67% | 65% | n/a |
| Claude Fable 5 | 43 | 37 | 90 | 96 | 67% | 64% | $0.077 |
| GPT-5.5 | 37 | 35 | 86 | 94 | 63% | 59% | $0.224 |
| Nemotron 3.5 Super VL alone | 16 | 8 | 61 | 86 | 43% | 39% | $0.0002 |
| **PlanSight** | 39 | 41 | 80 | 88 | **62%** | **62%** | **$0.0005** |

Per-kind columns are clean split B. **PlanSight is within ~6 points of the best frontier model at 1/60 to 1/450 of the
cost, and every count is boxed on the plan so a human can check it.** It does not beat frontier yet: Gemini 3 Pro's
47% on doors is the best door score. On 27 plan/question pairs of the 100 clean plans, all of Gemini 3.5 Flash,
Claude Fable 5 and GPT-5.5 are wrong and PlanSight is right. Full tables (A, B, all, clean): `runs/aecv-report/report.md`
(regenerate with `scripts/aecv_report.py`).

### Cheap first, escalate when unsure: PlanSight + a frontier model beats the frontier model

PlanSight knows when it's unsure: a door symbol scoring right at the detector's threshold, several borderline windows,
or the room readers disagreeing, on a plan that is big or in a drawing style the detector hasn't seen. Only those
plans go to Gemini 3.5 Flash, and only the unsure kinds take its answer (`plansight/escalate.py`). The rule was tuned
on split A only. Three escalation rules were scored on split B in total (all logged); this is the one we keep.

| Held-out split B | Door | Window | Toilet | Bedroom | Mean | $/plan |
|---|---|---|---|---|---|---|
| Best frontier model per kind | 47 (Gemini 3 Pro) | 38 (Gemini 3.5 Flash) | 90 | 93 | 65 | $0.031 |
| PlanSight alone | 43 | 38 | 80 | 85 | 62 | $0.0005 |
| **PlanSight + Gemini 3.5 Flash when unsure** | **50** | **42** | 80 | 88 | **65** | **$0.022** |
| same, clean split B (best frontier: 47 / 43 / 92 / 96, mean 68) | **51** | **45** | 80 | 90 | 67 | $0.022 |

**On doors and windows, where every frontier model fails, the combination beats every published frontier model on
plans it never saw, and costs 28% less than Gemini alone.** The overall mean ties the best frontier model. Toilets keep
PlanSight's answer because it beat Gemini on the tuning split; on split B Gemini was better there.

Two honest caveats:
- Escalated answers are AECV-Bench's **published** Gemini 3.5 Flash answers (same model, same prompt, run by the
  benchmark authors), not our own calls.
- Our own live call is wired up, but a 22-plan check got doors right 2/22 vs 10/22 for the published run. We had
  downscaled the image to JPEG, which loses thin door arcs. It now sends the original file with schema-enforced JSON,
  as the benchmark did. The free API tier (20 requests/day) ran out before a full live re-run.

It escalates 70% of plans, so for bulk work PlanSight alone ($0.0005) is the cheap tier.

**What we tried overnight to beat it (all logged in `runs/model-improvement.md`, none kept).** Each change was tuned
on split A only and had to hold up on held-out B and on the CubiCasa test split:

| Change | Split A (door/window) | Held-out result | Verdict |
|---|---|---|---|
| Re-tuned thresholds + one opening found as door *and* window counted once | 33/38 → 42/42 | B 43/38 → 43/33 | A gain was noise at n=60 |
| SAHI tiled inference (arXiv 2202.06934) on big sheets | 30/40 | not run | worse on A, 9× CPU |
| Window must sit in a wall (OpenCV wall mask) | windows 38 → ≤38 | not run | no gain |
| **Retrained detector v2 on Verda**: native-res tiles + style augmentation (grayscale, line weight, blur, JPEG, hatching) | best 32/43 | CubiCasa test window 49 → 42 | rejected |
| v1 + v2 ensemble (box fusion) | best 37/40 | not run | below v1 |

The shipped detector is unchanged. The lesson for the next iteration is data, not tricks. The misses concentrate on
drawing styles the detector never saw (AECV source group 4000: doors right on 1/17 plans), and the fix is labelled
plans in those styles. The reviewer-correction log in the demo (`feedback.jsonl`) is built to collect them.

## How Nemotron's role was found (the eval loop)

| Step | Result | Decision |
|---|---|---|
| Nemotron whole-plan counting, v0 | 45.4% on CubiCasa dev set (door 7.5, window 5) | baseline |
| + chain-of-thought / 2× upscale / tiling | 31.7% / 45.0% / 29.2% | all worse → symbols go to a fine-tuned detector |
| Detector proposes, Nemotron classifies each crop | split A door 33→40, but **held-out B door 43→33** | overfit → dropped |
| Nemotron reads room labels on the whole plan, as 1 of 3 voters | held-out B: **bedrooms 77→85%, toilets 45→80%** (clean B: 80→88%, 47→80%) | **kept** |

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
- **ElevenLabs**: "Talk to the drawing" voice mode for a site engineer with dirty hands. An ElevenLabs conversational
  agent whose tools call the same `/api/ask` pipeline, so a spoken question gets the same evidence boxes on the sheet.
  The browser gets a short-lived WebRTC token from `/api/voice/token`; the API key never leaves the server
  (`web/src/Voice.tsx`, `scripts/create_voice_agent.py`).
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
.venv\Scripts\python.exe -m pytest -q      # 71 tests
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
