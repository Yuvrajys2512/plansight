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

- none yet
