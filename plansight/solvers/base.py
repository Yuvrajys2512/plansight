"""The contract every solver implements. The eval harness, the API and the router only talk to this.

Only Lane A edits this file. If Lane B (Codex) needs a change, it writes a request in CODEX_LOG.md.
"""
from __future__ import annotations

from typing import Protocol

from plansight.types import Answer


class Solver(Protocol):
    name: str

    def can_handle(self, path: str) -> bool:
        """True if this solver is responsible for the drawing at `path` (dataset-relative, e.g. 'data/...')."""
        ...

    def solve(self, path: str, question: str) -> Answer | None:
        """Answer `question` about the drawing at `path`.

        Return None to abstain (question not understood, or evidence too weak). Abstaining is scored as
        wrong but is far better for the demo than a confident wrong answer. Never raise for a normal miss.
        """
        ...
