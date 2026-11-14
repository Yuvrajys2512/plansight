# Submission texts (paste into the Junction platform)

## Punchline
Ask a construction drawing anything in plain English: get the answer, the exact spot on the sheet it came from, and
what the question cost, in fractions of a cent.

## Description

**The problem.** Site engineers lose hours a day searching drawings, and general-purpose AI fails on them. We measured
it: across the 120 floor plans of AECV-Bench, no frontier model (Gemini, Claude, GPT) counts doors or windows correctly
more than 43% of the time. They read text well and count symbols badly, and a bigger model next year won't fix a
perception problem.

**What PlanSight does.** You ask a question in any of 7+ languages. PlanSight answers, draws a box around every piece of
evidence on the sheet, and shows what the question cost. One click on a box rejects it, one click adds a missed item, and
the count updates live. A human verifies the answer in seconds, and every correction is logged as future training data.

**How (hybrid, cheap first).**
- A multilingual router (template bank + English parser, Gemma as a fallback) sends each question to the cheapest tool
  that can answer it.
- IFC/BIM models → ifcopenshell facts. Swiss vector plans → PyMuPDF geometry. Schedule sheets → table extraction.
  All exact and $0.
- Raster plans → two YOLO11 detectors we trained on a Verda GPU (doors, windows, fixtures, rooms), served as ONNX on CPU.
- Room questions → a vote of three readers: OCR label lexicon, rooms detector, and NVIDIA Nemotron 3.5 Super VL (self-hosted on Verda).

**Results.**
- Stoa dataset: Swiss plans 99.5% and IFC models 99.7% (all languages, $0); multilingual routing 99.8% held-out;
  CubiCasa test split: toilets 92%, sinks 86%; schedule sheets 83%.
- AECV-Bench held-out split (never tuned on). We first audited leakage: 20 of its 120 plans are in our detector's
  training data (CubiCasa5K), so we drop them for every system. On the clean held-out split PlanSight averages **62%** vs
  Gemini 3.5 Flash 68%, Claude Fable 5 67%, GPT-5.5 63%, at **$0.0005 per plan, 60–450× cheaper**, with every count boxed.
  It doesn't beat frontier yet (Gemini 3 Pro gets 47% on doors vs our 39%), and we say so.
- Overnight we tried five ways to close that gap (rule tuning, SAHI tiling, a wall check, a detector retrained on Verda
  with tiles + style augmentation, an ensemble). Each was tuned on one half of the benchmark and judged on the other.
  None held up, so none shipped. The full log is in the repo.

**Tech:** Python, FastAPI, PyMuPDF, ifcopenshell, Ultralytics YOLO11 → ONNX, RapidOCR, vLLM, React. Deployed on Modal. Aiven PostgreSQL stores the answer cache, the per-question cost log and reviewer corrections (live
counter in the demo). Cloudinary hosts the sheets and renders zoomed evidence crops plus a shareable "evidence sheet" image
with every region outlined.
Nemotron + training on Verda. Built with Claude Code and Codex in two parallel git-worktree lanes.

## Nemotron explanation (NVIDIA track)

**Model:** NVIDIA Nemotron 3.5 Super VL (120B, ~12B active), NVFP4 checkpoint, self-hosted with vLLM on a Verda
RTX PRO 6000. About 0.8 s and ~$0.0002 per whole-plan read.

**What it does:** Nemotron reads the whole floor plan and reports its room labels (bedrooms, toilets/WCs) in any language
(CHAMBRE, Bed 1, Schlafzimmer, MH). It is one of three voters for room counts, next to an OCR label lexicon and a fine-tuned
rooms detector. The demo shows a "How PlanSight got N" trace for every answer: each voter's count, which one was used,
and Nemotron's cost and latency.

**Why it matters:** OCR misses stylised, rotated or abbreviated labels, and the detector only knows the plan style it was
trained on. Nemotron generalises across countries and drawing styles, which is exactly what a construction company with
drawings from many architects needs.

**How we improved its outputs (eval-driven, every step measured):**
1. Baseline, whole-plan counting: 45.4% on a frozen CubiCasa dev set (240 questions), but doors 7.5% and windows 5%.
2. Chain-of-thought (31.7%), 2× upscaling (45.0%) and tiling (29.2%) were all worse. Conclusion: small-symbol counting is a
   perception problem, so we moved symbols to fine-tuned detectors.
3. Detector proposes boxes and Nemotron classifies each crop: helped the tuning split (doors 33→40%) but hurt the held-out
   split (43→33%). We dropped it instead of shipping an overfit result.
4. Final role, Nemotron reading labels as one of three voters. On the held-out AECV split: **bedrooms 77% → 85%,
   toilets 45% → 80%** (with only two readers the median has no tie-breaker; Nemotron is that third vote). On the
   leakage-clean held-out split: bedrooms 80% → 88%, toilets 47% → 80%.
   We also added Nemotron 3.5 Super VL to the AECV-Bench comparison (it isn't on the published leaderboard): 39% alone
   vs 62% inside PlanSight.

**Where to see it in the demo:** open the "Frontier vs PlanSight" benchmark view and pick a plan. The trace shows
Nemotron's count next to the other voters, which one was used, and Nemotron's cost and latency. These are the real
recorded Nemotron reads from our self-hosted run. Live Nemotron calls are off on the public demo (`PLANSIGHT_NO_LLM=1`)
so it stays free and up while the GPU is powered down; set a Nemotron backend key to turn them on.

## Verda (post the docs/VERDA.md link in Verda's Discord)
PlanSight (Junction 2026, Stoa "Make Blueprints Talk") on Verda: one RTX PRO 6000 self-hosted NVIDIA Nemotron 3.5 Super VL
(NVFP4, vLLM) and trained two YOLO11 floor-plan detectors right next to it, so we could train, evaluate against Nemotron
and iterate within the hour. Thousands of eval calls with no rate limits. The detectors ship as CPU ONNX, so the public
demo answers for ~$0.00003 per question. Overnight we ran a second training (tiles + style augmentation, 10 s dataset
build on 28 cores, auto-export and auto-shutdown watcher). It didn't beat v1 on the held-out test, so it was documented
and not shipped. ~€58 of credit in total. Write-up: https://github.com/Yuvrajys2512/plansight/blob/main/docs/VERDA.md

## Codex
Codex built the eval harness, the CubiCasa OCR solver, the demo API, the web UI and the Frontier vs PlanSight view in a
parallel git-worktree lane (`codex/p*` branches, merged per phase). Log: `CODEX_LOG.md`. Screenshots: `docs/codex/`.

## ElevenLabs
"Talk to the drawing" voice mode: an ElevenLabs conversational agent whose tools call the same `/api/ask` pipeline, so
a spoken question ("how many doors on this plan?") gets the same evidence boxes on the sheet. Built for a site engineer
with dirty hands. The browser gets a short-lived WebRTC token from our server; the API key never reaches the client.

## Tech challenges: tick / untick (checked against the code and the live site, Sun 01:45)
| Tech | Keep? | Evidence |
|---|---|---|
| Nemotron | ✅ | 3rd voter for rooms; held-out toilets 45→80%, bedrooms 77→85% |
| Verda | ✅ | self-hosted Nemotron, two detector trainings, `docs/VERDA.md` |
| Gemma | ✅ | router fallback for unseen phrasings/languages (`plansight/router/gemma.py`) |
| Codex | ✅ | `CODEX_LOG.md`, `docs/codex/` |
| Aiven | ✅ | answer cache + question/cost log + corrections; live `/api/stats` (207 questions logged) |
| Cloudinary | ✅ | evidence crops + shareable evidence sheet via URL transforms. **Fill cld.media/hackathon-survey** |
| Modal | ✅ | hosts the public demo |
| ElevenLabs | ✅ | voice mode live (`/api/voice/token` returns 200) |
| Gemini API | ❌ **untick** | only used as the transport to reach Gemma and as the LLM inside the voice agent; not a distinct job |
