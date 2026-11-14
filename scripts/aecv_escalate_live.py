"""Live run of the escalation partner: Gemini 3.5 Flash (AECV prompt) on every AECV plan, cached, resumable.

    python scripts/aecv_escalate_live.py            -> runs/detcache/aecv-gemini35flash-live.jsonl
Then score with:  python scripts/aecv_escalate.py --live --cfg ... --show A,B,B_clean
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from plansight.config import RUNS  # noqa: E402
from plansight.escalate import frontier_counts  # noqa: E402
from scripts.aecv_cache import aecv_plans  # noqa: E402
from scripts.aecv_eval import REPO  # noqa: E402

OUT = RUNS / "detcache" / "aecv-gemini35flash-live.jsonl"


def main():
    done = {json.loads(line)["plan"] for line in OUT.open(encoding="utf-8")} if OUT.exists() else set()
    todo = [(n, p) for n, p, _ in aecv_plans(REPO) if n not in done]

    def one(np):
        n, p = np
        try:
            return {"plan": n, **frontier_counts(p)}
        except Exception as e:  # noqa: BLE001
            return {"plan": n, "error": repr(e)[:200]}

    with ThreadPoolExecutor(4) as ex, OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(ex.map(one, todo)):
            if "error" not in r:
                f.write(json.dumps(r) + "\n")
                f.flush()
            print(i + 1, len(todo), r.get("plan"), r.get("error", ""), flush=True)


if __name__ == "__main__":
    main()
