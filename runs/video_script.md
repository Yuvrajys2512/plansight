# PlanSight: 2-minute pitch video (shot list + narration)

~270 words spoken at a calm pace ≈ 1:50. Record the screen at 1080p and the voice separately if you can. Live site:
https://yuvrajys2512--plansight.us-east.modal.run (open it 1 min before so it's warm). Each shot ends on something
moving. If a shot runs long, cut narration, never the evidence box.

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:12 | Landing sheet (black panel, the marked-up plan, title block of stats) | "Site engineers lose hours a day hunting through drawings. And general AI is bad at it: on 120 real floor plans, the best frontier model counts the doors right 43% of the time." |
| 2 | 0:12–0:35 | "Open the drawings" → Colorful 268 → click "How many windows are shown on this floor plan?" → blue boxes appear one by one, answer 3, "between 3 and 4", amber "Check before you trust this", cost panel | "PlanSight. Ask a drawing a question in any language. You get the answer, a box on every window it counted, and what the question cost: a few thousandths of a cent. And when it's not sure, it says so." |
| 3 | 0:35–0:47 | Tap the amber "?" box on the top-left window → count goes 3 → 4 (the correct answer). Then click "Run all" in the question list: statuses fill in (sure / check) | "One tap and a human fixes it: four, the right answer. Every question on the sheet gets a status, so a reviewer only looks at the ones that need it." |
| 4 | 0:47–1:05 | Finnish question row (or type German); then an IFC model in the list, a question answered exactly | "It's cheap because it's hybrid. Parsers answer BIM models and vector plans exactly, for free. Detectors we trained on a Verda GPU count symbols on CPU. NVIDIA Nemotron only reads what's hard: room labels in any language, as one of three voters." |
| 5 | 1:05–1:30 | "Frontier vs PlanSight" tab → pick a plan, show the frontier list (red crosses) and "How PlanSight got N" with Nemotron's vote | "Alone, PlanSight is within a few points of frontier models at one-sixtieth of the cost. And because it knows when it's unsure, it can hand just those parts to a frontier model: on plans we never tuned on, that combination beats every frontier model on doors and windows, for 28% less than the frontier model alone. Leakage audited." |
| 6 | 1:30–1:45 | Back on a Swiss plan → "Lift to 3D" (rooms light up); or "Ask by voice" | "Hands dirty on site? Ask by voice. Or lift any plan into 3D." |
| 7 | 1:45–1:55 | "AR on your table" on the phone (only if it works first try; else stay on 3D) | "Correct, checkable, and cheap enough to run on every drawing a company owns." |
| 8 | 1:55–2:00 | Back to the landing sheet / URL | "PlanSight. Make blueprints talk." |

**Say exactly "beats every frontier model on doors and windows".** Don't say "beats frontier" on its own. The overall
mean ties (65 vs 65 on split B) and PlanSight alone trails (62% vs 68% clean). If asked, the escalated answers are
AECV's published Gemini 3.5 Flash answers for the same prompt; our own live call ran on 22 plans before the free tier
ran out.

**If someone asks in peer review "what did you try overnight?"**, read `runs/pitch_model_summary.md`.
