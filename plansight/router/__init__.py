"""Multilingual question router: question (any language) -> (template, params) for the deterministic solvers.

Cheapest first:
1. English parser of the solver ($0)
2. template bank: per-language patterns mined from the dataset ($0)
3. Gemma 4 31B on AI Studio, strict JSON, verbatim-slot validation, cached (fractions of a cent)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from plansight.router.english import domain_of, parse_en


@dataclass
class Route:
    template: str | None
    params: dict = field(default_factory=dict)
    method: str = "none"  # en | bank | gemma | none
    lang: str = "en"
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.template is not None

    def describe(self) -> str:
        how = {"en": "English parser", "bank": f"template bank ({self.lang})", "gemma": "Gemma 4 31B"}
        return f"Question routed by {how.get(self.method, self.method)} to {self.template} {self.params}"


def parse(path: str, question: str, *, use_llm: bool | None = None, bank=None) -> Route:
    """Route a question about the drawing at `path`. Returns Route with template None if nothing fits.
    Gemma is used unless use_llm=False or env PLANSIGHT_NO_LLM=1 (tests, offline demo)."""
    if use_llm is None:
        use_llm = os.getenv("PLANSIGHT_NO_LLM", "") not in ("1", "true")
    from plansight.router.bank import default_bank

    t0 = time.perf_counter()
    dom = domain_of(path)
    if dom is None:
        return Route(None)

    def done(r: Route) -> Route:
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if (p := parse_en(dom, question)) is not None:
        return done(Route(*p, method="en", lang="en"))
    if (m := (bank or default_bank()).match(dom, question)) is not None:
        return done(Route(m.template, m.params, method="bank", lang=m.lang))
    if use_llm:
        from plansight.router import gemma
        from plansight.router.lang import detect

        try:
            p, cost, _ = gemma.route(dom, question)
        except Exception:
            return done(Route(None, method="none", lang=detect(question)))
        if p is not None:
            return done(Route(*p, method="gemma", lang=detect(question), cost_usd=cost))
        return done(Route(None, method="none", lang=detect(question), cost_usd=cost))
    return done(Route(None))
