# Model work, read-out version (5 lines)

1. **The problem:** every frontier model, Gemini, Claude, GPT, gets doors and windows on floor plans wrong more than half the time. Our own detector was 60× cheaper but still a few points behind.
2. **The insight:** PlanSight knows when it's unsure: a symbol scoring right at the threshold, or its readers disagreeing. So it answers the easy plans itself, and only the unsure parts go to a frontier model.
3. **The result, on held-out plans we never tuned on:** doors 48% and windows 43%. That beats every published frontier model (best: 47% and 38%), costs less than Gemini alone, and every count is still boxed on the plan.
4. **The discipline:** we found 20 benchmark plans were in our own training data and report the clean numbers too (doors 49%, windows 47%). Every rule was tuned on one half and tested once on the other. Five overnight tricks, including a GPU retrain, failed that test and were thrown away.
5. **So why PlanSight and not a frontier model?** Because PlanSight plus a frontier model is more accurate than the frontier model, cheaper, and checkable in seconds. For bulk work, PlanSight alone costs $0.0005 a plan.
