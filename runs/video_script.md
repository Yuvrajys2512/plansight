# PlanSight: 2-minute pitch video (shot list + narration)

~270 words spoken at a calm pace ≈ 1:50. Record the screen at 1080p and the voice separately if you can. Live site:
https://yuvrajys2512--plansight.us-east.modal.run (open it 1 min before so it's warm). Each shot ends on something
moving. If a shot runs long, cut narration, never the evidence box.

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:12 | Intro screen with the three stats | "Site engineers lose hours a day hunting through drawings. And general AI is bad at it: on a public benchmark of 120 real floor plans, no frontier model counts doors or windows right even half the time." |
| 2 | 0:12–0:35 | Stoa drawing, type "How many doors are on this floor?" → answer, boxes appear, cost panel | "PlanSight. Ask a drawing a question in any language. You get the answer, a box on every door it counted, and what the question cost: a few thousandths of a cent. A human checks it in two seconds." |
| 3 | 0:35–0:47 | Click a box to reject it, then "+ Add a missed item", tap the plan; count updates | "If it's wrong, one click fixes it, and every correction is saved as training data for the next model." |
| 4 | 0:47–1:05 | Same question in Finnish or German; then an IFC model question answered exactly | "It's cheap because it's hybrid. Parsers answer BIM models and vector plans exactly for free. Detectors we trained on a Verda GPU count symbols on CPU. NVIDIA Nemotron only reads what's hard: room labels in any language, as one of three voters." |
| 5 | 1:05–1:30 | "Frontier vs PlanSight" view → pick a plan, open "How PlanSight got N" trace (Nemotron's vote visible); then the README results table on screen | "Alone, PlanSight is within a few points of frontier models at one-sixtieth of the cost. And because it knows when it's unsure, it can hand just those parts to a frontier model: on plans we never tuned on, that combination beats every frontier model on doors and windows, for 28% less than the frontier model alone. Clean numbers, leakage audited." |
| 6 | 1:30–1:45 | Voice mode: ask out loud, boxes light up. Or the snap/QR flow: photograph a printed plan with the phone | "Hands dirty on site? Ask by voice. Or snap any paper plan with your phone." |
| 7 | 1:45–1:55 | AR view of the building on the table (only if it works first try; else stay on the evidence sheet) | "Correct, checkable, and cheap enough to run on every drawing a company owns." |
| 8 | 1:55–2:00 | Logo / URL / "Single Thread" | "PlanSight. Make blueprints talk." |

**Say exactly "beats every frontier model on doors and windows".** Don't say "beats frontier" on its own. The overall
mean ties (65 vs 65 on split B) and PlanSight alone trails (62% vs 68% clean). If asked, the escalated answers are
AECV's published Gemini 3.5 Flash answers for the same prompt; our own live call ran on 22 plans before the free tier
ran out.

**If someone asks in peer review "what did you try overnight?"**, read `runs/pitch_model_summary.md`.
