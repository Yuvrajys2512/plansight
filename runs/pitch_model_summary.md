# Model work, read-out version (5 lines)

1. **What was wrong:** our door/window detector was strong on its own drawing style but weak on unseen styles (one AECV source: doors right on 1 of 17 plans). And 20 of the benchmark plans turned out to be in our own training data.
2. **What we did:** we audited that leakage with image hashing and now quote only the clean numbers. Overnight we tested five fixes: re-tuned counting rules, tiled inference, a wall check, and a detector retrained on a Verda GPU with tiles and style augmentation, plus an ensemble.
3. **The discipline:** every fix was tuned on half the benchmark and judged on the held-out half plus the CubiCasa test split. None held up, so none shipped. The retrain cost about €3.50 of GPU time and dropped windows 49 → 42 on CubiCasa test, so we threw it away.
4. **Held-out result (clean split B):** PlanSight 62% mean vs 68% for the best frontier model (Gemini 3.5 Flash). That's 39% doors, 41% windows, 80% toilets and 88% bedrooms, at $0.0005 a plan instead of $0.03 (60× cheaper), with every count boxed on the plan.
5. **Next:** the gap is data, not model size. Reviewer corrections in the demo are logged as the next training labels for exactly those unseen styles.
