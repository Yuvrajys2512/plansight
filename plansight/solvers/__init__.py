"""Solver registry. `get_solver(name)` for one, `route(path)` to pick by drawing.

Lane A owns this file. New solvers are registered here at phase merges.
"""
from __future__ import annotations

from plansight.solvers.base import Solver


def _registry() -> dict[str, Solver]:
    from plansight.solvers.cubicasa_text import CubicasaTextSolver
    from plansight.solvers.ifc import IfcSolver
    from plansight.solvers.swiss import SwissSolver

    return {s.name: s for s in [SwissSolver(), IfcSolver(), CubicasaTextSolver()]}


def get_solver(name: str) -> Solver:
    reg = _registry()
    if name not in reg:
        raise KeyError(f"unknown solver {name!r}; have {sorted(reg)}")
    return reg[name]


def route(path: str) -> Solver | None:
    """First registered solver that can handle this drawing, or None."""
    return next((s for s in _registry().values() if s.can_handle(path)), None)
