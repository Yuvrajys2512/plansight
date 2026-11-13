# PlanSight

Ask a construction drawing anything in plain English: get the answer, the exact spot on the sheet it came from,
and what the question cost, in fractions of a cent.

Built at Junction 2026 for Stoa's **Make Blueprints Talk** challenge by team **Single Thread**.

> Work in progress. Setup, architecture and eval results will be documented here.

## Setup

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv -r requirements.txt
copy .env.example .env   # then fill in keys
```
