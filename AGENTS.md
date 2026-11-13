# AGENTS.md: rules for Codex (Lane B)

PlanSight answers natural-language questions about construction drawings (Stoa "Make Blueprints Talk",
Junction 2026). It returns the answer, evidence boxes on the sheet, and the cost of each question.
Two agents build it in parallel: **Claude Code (Lane A)** in `D:\Junction` on `main`, and **you, Codex
(Lane B)** in this worktree `D:\Junction-codex` on a `codex/p<N>` branch.

## Start of every session
1. Read `D:\Junction\ROADMAP.md` (absolute path; it is not in this repo). Find the current phase and
   do **only the Lane B checklist** of that phase.
2. Read `CODEX_LOG.md` to see what you already did.

## Environment
- Windows. Python: `D:\Junction\.venv\Scripts\python.exe` (shared with Lane A, Python 3.12).
  Run from this folder so `import plansight` resolves to this worktree's code.
- Dataset (read-only): `D:\Junction\junction-dataset` (`questions.jsonl` + `data/<source>/...`).
  `.env` here sets `PLANSIGHT_DATA` to it. Always go through `plansight.config` (`QUESTIONS`, `resolve()`, `source_of()`).
- API keys live in `.env` (gitignored). Never print, log or commit them.

## Hard rules
1. **Edit only the files the current phase assigns to Lane B.** Never edit these shared contract files:
   `plansight/types.py`, `plansight/config.py`, `plansight/solvers/base.py`, `plansight/solvers/__init__.py`.
   If you need a change there, write it under **Requests** in `CODEX_LOG.md` and work around it.
2. `requirements.txt` is append-only (add new lines at the end).
3. Commit to your `codex/p<N>` branch only, in small commits. Never commit to `main`, never push, never rebase.
4. Every solver implements the protocol in `plansight/solvers/base.py`: `solve()` returns
   `plansight.types.Answer` (with `Evidence` boxes) or `None` to abstain. Never raise for a normal miss.
5. Keep it cheap: deterministic code first, model calls only where needed, and record `cost_usd`.
6. Don't write data or outputs into git: `runs/`, `cache/` and the dataset are gitignored.

## Logging (this is our evidence for the Codex prize)
After each meaningful piece, append to `CODEX_LOG.md`: time (Helsinki), what you built, files, how you
verified it (command + result), and open issues. Keep it factual.
