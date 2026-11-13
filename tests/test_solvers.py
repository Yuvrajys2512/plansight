"""Known answers from questions.jsonl. Lane A owns this file (Codex owns tests/test_eval.py)."""
import pytest

from plansight.config import QUESTIONS
from plansight.solvers import route

pytestmark = pytest.mark.skipif(not QUESTIONS.exists(), reason="dataset not available")

CASES = [
    # (path, question, answer)
    ("data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf",
     "How many doors are shown on the floor plan of 'Grundplan'?", 12),
    ("data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-01-1-korrus.pdf",
     "What is the net floor area of the room 'KORIDOR (119)' on '1.korrus', in m²?", 63.84),
    ("data/ifc_models/bsc-duplex_duplex-a-20110907.ifc",
     "What is the net floor area of the room 'Living Room (A102)' on 'Level 1', in m²?", 27.66),
    ("data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf",
     "What is the total length of all walls on 'Grundplan', in metres?", 185.129),
    ("data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-01-1-korrus.pdf",
     "How many stairs are there in the model 'Maleva tänav 18 korterelamu (Esplanades example model)'?", 4),
]


@pytest.mark.parametrize("path,question,expected", CASES)
def test_known_answers(path, question, expected):
    a = route(path).solve(path, question)
    assert a is not None
    if isinstance(expected, int):
        assert a.value == expected
    else:
        assert abs(a.value - expected) <= 0.02 * expected


def test_ifc_evidence_lands_on_the_plan():
    p = "data/ifc_models/bsc-molio_molio-with-uris_plan-03-grundplan.pdf"
    a = route(p).solve(p, "How many doors are shown on the floor plan of 'Grundplan'?")
    assert len(a.evidence) == 12
    for e in a.evidence:  # every door box is small and inside the 880x763 pt sheet
        x0, y0, x1, y1 = e.bbox
        assert 0 <= x0 < x1 <= 881 and 0 <= y0 < y1 <= 764
        assert (x1 - x0) < 150 and (y1 - y0) < 150


def test_unparsed_question_abstains():
    p = "data/ifc_models/bsc-duplex_duplex-a-20110907.ifc"
    assert route(p).solve(p, "Wie viele Türen gibt es im Modell?") is None
