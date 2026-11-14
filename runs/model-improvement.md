# Model improvement log (Sun 15 Nov, Helsinki)

Protocol: tune on AECV split A only; split B once per finalist. "clean" = AECV plans that are in our detector's
CubiCasa train split removed (20 plans, `runs/aecv_leakage.json`). CubiCasa test = 400-plan count eval (`eval_cubicasa_det.py`).

| time | track | change | A door/win/toilet | B door/win/toilet | clean A / clean B door/win | CubiCasa test door/win | kept? |
|---|---|---|---|---|---|---|---|
| 22:15 | 0 | Leakage audit: 33/120 AECV plans (all in source group 5000) are CubiCasa5K images; 20 in our train split, 11 val, 2 test. dHash 16x16, matches at Hamming 0-12, no near-misses 21-40 | | | | | audit |
| 22:20 | base | v1 detector, td .35 / tw .30 / merge gap 6 px (shipped) | 33/38/87 | 43/38/80 | 22/41 · 39/41 | 69/49 | baseline |
| 22:10 | B | Verda: v2 fine-tune started (v1 best.pt → 4.2k full + 4.1k native-res tiles + 1.8k style-aug; YOLO11m @1280, 40 ep, cos LR, patience 10). Swiss Dwellings DXF labels skipped (not wireable in 30 min) | | | | | running |
| 22:35 | A1 | Rules on cached v1 dets, grid on A: td .30, tw .25, gap 6, door/window dedupe IoU>.3. Double-leaf rule (long side ≥1.6-1.9× plan median door) hurt A at every setting → dropped. Style-adaptive low window threshold: no A gain → dropped | 42/42/87 | 43/33/80 | 31/45 · 39/35 | n/a (no det change) | **no**: B windows −5 (A gains are noise at n=60) |
| 22:25 | A2 | v1 + SAHI (full pass + native-res 1280 tiles, 25% overlap, edge-cut drop, NMS + IoS merge; only 37/120 plans tiled). 9 s vs 1 s CPU on a 3079 px sheet | 30/40/85 (best re-tuned 35/42) | not run | 22/43 · - | ≤6 test plans tiled | **no** for v1 (v1 never saw native-scale symbols); retry with v2 |
| 22:30 | A3 | Window-on-wall verifier (wall mask = raster_scene recipe; support = wall pixels past both ends of the box). Filter unsure windows / admit low-conf candidates on walls, grid on A | windows 33-38 filter, 37 admit (base 38) | not run | - | n/a | **no**: no A gain; mask misses colour-filled walls |
