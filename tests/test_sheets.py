import pytest

from plansight.sheets.qa import SheetSolver, run_code
from plansight.solvers import route

A801 = "data/opening_design/Sports_Complex/Sheets - Current Set/A-801 - Door and Finish Schedules & Wall Types.pdf"


def test_sheet_solver_is_routed():
    assert route(A801).name == "sheets"


def test_generated_code_runs_sandboxed():
    code = 'def answer(T, TEXT):\n    rows = [i for i, r in enumerate(T["t"]) if "A" in [x.strip() for x in r[1].split(",")]]\n' \
           '    return {"answer": len(rows), "rows": [["t", i] for i in rows]}'
    assert run_code(code, {"t": [["1", "A, B"], ["2", "C"], ["3", "A"]]}, []) == {"answer": 2, "rows": [["t", 0], ["t", 2]]}


@pytest.mark.parametrize("code, exc", [
    ("def answer(T, TEXT):\n    while True:\n        pass", TimeoutError),
    ("def answer(T, TEXT):\n    import os\n    return {}", RuntimeError),
    ("def answer(T, TEXT):\n    return open('x')", ValueError),
])
def test_generated_code_is_contained(code, exc):
    with pytest.raises(exc):
        run_code(code, {}, [], timeout=2)


def test_sheet_solver_abstains_offline(monkeypatch):
    monkeypatch.setenv("PLANSIGHT_NO_LLM", "1")
    assert SheetSolver().solve(A801, "How many doors are listed in the door schedule?") is None
