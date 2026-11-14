# CODEX_LOG.md

What the Codex CLI built for PlanSight, in order. Codex works in a parallel lane (git worktree, `codex/p<N>`
branches) and its work is merged into `main` at the end of each phase. See `AGENTS.md` for the rules it follows.

## Entries

### <Sat 01:41 Helsinki> Phase 1: evaluation harness
- Built: Added configured JSONL loading with source/language tags, deterministic proportional sampling by source/type/language, exact count and 2% measurement scoring, text-unscored handling, solver routing/selection, exception capture, latency/evidence/cost recording, grouped console and Markdown summaries, and timestamped JSONL outputs. Added Phase 1 preset and five scorer/sampler/language tests.
- Files: `plansight/eval/__init__.py`, `plansight/eval/__main__.py`, `plansight/eval/data.py`, `plansight/eval/scoring.py`, `plansight/eval/runner.py`, `tests/test_eval.py`, `CODEX_LOG.md`
- Verified: `D:\Junction\.venv\Scripts\python.exe -m plansight.eval --preset phase1` → 600 rows; Swiss English accuracy 100.0%, aggregate scored accuracy 25.3% including abstentions, abstain rate 74.7%, 0 errors, total cost $0.000000; outputs in `runs/20261114-051122/`. Manual invocation of all five test functions → passed. Dataset load → 127,044 rows, language tags en/fi/de/fr/it/da/et/other.
- Open issues: `python -m pytest -q tests/test_eval.py` could not start because `pytest` is not installed in the shared environment. Screenshot of the Codex session not captured. IFC questions abstain because the Lane A IFC solver is not registered in this worktree yet.

<!-- Template:
### <Sat 00:40> Phase N: <what>
- Built: ...
- Files: ...
- Verified: `<command>` → <result>
- Open issues: ...
-->

## Requests (changes Codex needs in Lane A's shared files)

- Register `CubicasaTextSolver` in `plansight/solvers/__init__.py` at the Phase 2 merge (Lane A-owned shared file).

### <Sat 02:34 Helsinki> Phase 2: CubiCasa room-label OCR solver
- Built: Added CPU RapidOCR with SHA-256 JSON disk cache in `cache/ocr/`, token confidence and pixel boxes; added `CubicasaTextSolver` for sauna, kitchen, bedroom, bathroom, separate WC and balcony count questions in English and Finnish. Labels include room-number/dimension suffixes, `MH+3`, room summary codes such as `2H+KK+S`, OCR variants `W0`/`GH`/`PE`, and the `MAKUUH` bedroom abbreviation. The solver returns one page-0 pixel evidence box per matched OCR label and abstains when OCR is unavailable, title-block-only, or uncertain.
- Files: `plansight/ocr/__init__.py`, `plansight/ocr/rapid.py`, `plansight/solvers/cubicasa_text.py`, `tests/test_cubicasa_text.py`, `requirements.txt`, `CODEX_LOG.md`
- Verified: `D:\Junction\.venv\Scripts\python.exe -m pytest -q tests/test_cubicasa_text.py` -> 21 passed. Full suite -> 34 passed after final OCR and label-rule changes. `python -m plansight.eval --solvers cubicasa_text --sources cubicasa5k --per-source 3000 --seed 0` (temporary worktree-local bootstrap supplied the unregistered Lane A solver to the existing harness; removed before commit) -> 2,670 question rows on 300 seed-0 plans, 1,335 English + 1,335 Finnish, exact count accuracy 51.6%, abstain 15.7%, errors 0, cost $0. Per-template accuracy was identical by language: balcony 72.6% (117/lang), WC room 67.5% (206/lang), bedroom 50.8% (240/lang), sauna 48.2% (280/lang), bathroom 43.5% (214/lang), kitchen 41.4% (278/lang). Cached mean latency 0.4 ms.
- Error analysis and iteration: Initial English run was 44.6% exact (22.8% abstain). First iteration accepted dimension-suffixed codes and parsed composite `2H+KK+S` labels; it reached 50.9% (15.7% abstain). Cache review found `MAKUUH`, plus OCR confusions `GH` and `PE`; adding these raised final accuracy to 51.6%. Template accuracy improved from initial to final: sauna 37.1% -> 48.2%, kitchen 33.8% -> 41.4%, bedroom 45.0% -> 50.8%, bathroom 38.8% -> 43.5%, WC 62.1% -> 67.5%, balcony 67.5% -> 72.6%. Remaining misses are mostly expected positive counts predicted as zero (bathroom 82 cases; sauna 68; kitchen 54) where room labels were not recognized or absent; kitchen also has 56 one-to-two overcounts, often multiple K/KK/TK codes whose room identity is ambiguous from OCR alone. Accuracy remains below the 85% target.
- Open issues: `plansight/solvers/__init__.py` is Lane A-owned and currently does not register `cubicasa_text`; request registration at merge. OCR/text-label approach misses visually indicated rooms with no readable label and can overcount repeated or ambiguous kitchen abbreviations.
