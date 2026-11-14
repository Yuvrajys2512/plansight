# PlanSight on Verda: what the GPU did

PlanSight answers questions about construction drawings with an answer, a box on the exact spot of the sheet, and the
cost of the question. The live demo runs **CPU-only** and costs fractions of a cent per question. That only works
because the heavy lifting happened once, on a Verda GPU, during the hackathon. This is that process.

## The box

| | |
|---|---|
| Instance | `plansight-nemotron`, 1× **NVIDIA RTX PRO 6000 (96 GB)**, Verda FIN-03, on-demand ($2.81/h) |
| Software | vLLM v0.31.0 in Docker, Ultralytics YOLO11, ONNX export |
| Credit | €200 hackathon credit; **~€58 used** (Fri night → Sun 01:10), €141.60 left |
| Control | `scripts/verda.py status|start|shutdown` (Verda REST API). The instance is shut down whenever it's idle |

## What ran on it

### 1. Self-hosted NVIDIA Nemotron 3.5 Super VL (120B, ~12B active)
- Model `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, served by vLLM as an OpenAI-compatible endpoint
  (`nemotron-3.5-super-vl`, 16k context, MTP speculative decoding with 5 tokens).
- **Why self-host:** the free API tiers cap at ~40 req/min (NVIDIA Build) or 50 req/day (OpenRouter free). Our eval loops
  needed thousands of image calls in a few hours. The NVFP4 checkpoint fits on one 96 GB card, and Blackwell runs FP4 natively.
- Client: `plansight/vlm/nemotron.py` (backend order: self-hosted → OpenRouter → NVIDIA Build, with retries and a disk cache).
- **Throughput/cost:** ~0.8 s per whole-plan read, **~$0.0002 per plan** at the on-demand GPU price. That's the number
  shown next to Nemotron in the demo.

### 2. Training two floor-plan detectors (the reason PlanSight can count)
Nemotron alone counted doors and windows correctly only 5–13% of the time (see `README.md`, "How Nemotron's role was
found"), so we trained small detectors for symbols on the same GPU, next to the running vLLM server (vLLM was capped with
`--kv-cache-memory 5e9`, leaving ~15 GB for training).

| Model | Classes | Data | Result (CubiCasa **test** split) |
|---|---|---|---|
| `cubicasa_objects` YOLO11m @1280 | window, door, opening, toilet, sink, double sink, shower, shower cabin, bathtub | CubiCasa5K **train split only**, labels converted from the public SVG annotations | 74.9% exact count (toilet 92, sink 86, shower/bath 77, door 69, window 49) |
| `cubicasa_rooms` YOLO11m @1024 | bedroom, kitchen, bathroom, WC, sauna, balcony, floor | same | mAP50 0.90 |

Both are exported to **ONNX and run on CPU** in the deployed app (`plansight/detect/onnx_yolo.py`, no torch). Train once on
a GPU, serve forever on a CPU for ~$0.00003 per question.

### 3. Evaluation runs
- Nemotron prompt and strategy experiments on a frozen dev set (40 CubiCasa plans × 6 visual questions): v0 whole plan,
  chain-of-thought, 2× upscale, tiling. All logged with accuracy and $ per question.
- **AECV-Bench** (arXiv 2601.04819): Nemotron 3.5 Super VL on all 120 plans (not on their published leaderboard, so we added
  it), plus per-crop reclassification experiments on the tuning split A, checked on held-out split B.

### 4. Overnight retrain attempt (Sun 00:10–01:10): a documented negative result
- Goal: fix the detector's weak spots on the held-out AECV benchmark (small symbols on big sheets, unseen drawing styles).
- Built on the box in 10 s with 28 processes (`scripts/build_tiles_v2.py`): 4.2k full plans + 4.1k native-resolution
  tiles (slicing-aided fine-tuning, arXiv 2202.06934) + 1.8k style-augmented copies (grayscale, line thinning and
  thickening, blur, JPEG 30–90, gamma, noise, hatching). vLLM was stopped so the whole GPU trained.
- Fine-tuned v1 (YOLO11m @1280, AdamW 2e-4, cosine, batch 16, ~2 min/epoch, early stop at epoch 19). A watcher script
  exported ONNX, ran the test-split eval and powered the instance off when done.
- Result: CubiCasa test doors 69 → 68, **windows 49 → 42**, and worse door counts on AECV tuning split A. **Rejected**;
  the shipped detector is unchanged. Cost: **€3.46**. Full log: `runs/model-improvement.md`.
- Lesson: augmentation alone doesn't bridge the style gap. The next run needs labelled plans in the new styles, which
  is what the demo's reviewer-correction log collects.

## Why this needed Verda and not a laptop
- A 120B multimodal model doesn't run on a laptop. Self-hosting it made thousands of eval calls possible in one night,
  with no rate limits.
- Training two YOLO11m models at 1024–1280 px on ~4k plans takes hours on a big GPU and would take days on a laptop.
- Because the GPU ran *beside* the inference server, we could train, evaluate against Nemotron and iterate in the same hour.

## Path to scale
- **Batch preprocessing:** the same box can pre-run detectors, OCR and Nemotron label reads over a customer's whole drawing
  set overnight and store regions + facts (Postgres/pgvector). Questions then hit the cache at ~$0 each.
- **Serving:** the detectors are CPU ONNX, so they scale horizontally on cheap instances (the demo runs on Modal CPU).
  Nemotron is only needed for reads that the deterministic tools can't do, so one shared GPU endpoint (Verda's managed
  Nemotron endpoint or an auto-scaling container) covers many users.
- **Retraining:** reviewer corrections from the demo (click a box to reject it, add a missed one) are logged to
  `feedback.jsonl`. These are the next training labels for the detectors on Verda.

## Reproduce
```powershell
.venv\Scripts\python.exe scripts\verda.py start
ssh -i ~/.ssh/plansight_verda root@<instance-ip> "nohup /root/serve.sh > /root/serve.log 2>&1 &"   # ~4 min to healthy
$env:PLANSIGHT_NEMOTRON="self"; .venv\Scripts\python.exe -m plansight.vlm.run --version v0     # dev-set eval
.venv\Scripts\python.exe scripts\verda.py shutdown
```
