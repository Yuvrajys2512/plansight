"""Multilingual router: bank matches, Gemma output validation, solvers answering non-English questions.
Lane A owns this file. No network: Gemma is never called here (use_llm=False or validate() only)."""
import pytest

from plansight.config import QUESTIONS
from plansight.router import parse
from plansight.router.gemma import validate

SW = "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf"
IFC = "data/ifc_models/bsc-esplanades_1807-ep-ar-v18_plan-01-1-korrus.pdf"
CC = "data/cubicasa5k/colorful-10052.png"

BANK_CASES = [
    (SW, "Wie gross ist die Nettofläche von Raum 7.01 («Balkon») in m²?", "room_area", {"number": "7.01"}),
    (SW, "Quelle est la surface nette de la pièce 5.10 (« Séjour/repas ») en m² ?", "room_area", {"number": "5.10"}),
    (SW, "Quanti locali con la denominazione «Camera da letto» ci sono in questo piano?",
     "count_rooms_named", {"name": "Camera da letto"}),
    (SW, "Wie gross ist die Nettowohnfläche von Wohnung B in m² (Summe aller Räume ohne Balkone, Loggien, "
         "Terrassen und andere Aussenräume)?", "apartment_area", {"letter": "B"}),
    (SW, "Combien de douches sont dessinées sur ce plan ?", "count", {"kind": "showers"}),
    (IFC, "Kui suur on ruumi „KORIDOR (119)“ netopõrandapind korrusel „1.korrus“ (m²)?",
     "room_area", {"room": "KORIDOR (119)", "storey": "1.korrus"}),
    (IFC, "Wie viele Türen enthält das Modell „Ein unbekanntes Modell“?", "count",
     {"kind": "doors", "model": "Ein unbekanntes Modell"}),
    (CC, "Kuinka monta erillistä WC-tilaa pohjapiirustuksessa on?", "count", {"kind": "wc_room"}),
]


@pytest.mark.parametrize("path,q,template,params", BANK_CASES)
def test_bank_routes(path, q, template, params):
    r = parse(path, q, use_llm=False)
    assert r.method == "bank" and r.template == template and r.params == params


def test_english_first():
    r = parse(SW, "How many windows are drawn on this floor plan?", use_llm=False)
    assert (r.method, r.template, r.params) == ("en", "count", {"kind": "windows"})


def test_unknown_question_abstains_without_llm():
    assert not parse(SW, "Was kostet die Küche?", use_llm=False).ok


def test_gemma_validation_rejects_hallucinated_slots():
    q = "Hvor mange døre er vist på plantegningen for 'Kælder'?"
    ok = validate("ifc", q, '{"template": "count", "params": {"kind": "doors", "storey": "kælder"}}')
    assert ok == ("count", {"kind": "doors", "storey": "Kælder"})  # verbatim spelling restored from the question
    assert validate("ifc", q, '{"template": "count", "params": {"kind": "doors", "storey": "Basement"}}') is None
    assert validate("ifc", q, '{"template": "count", "params": {"kind": "chairs", "storey": "Kælder"}}') is None
    assert validate("ifc", q, '{"template": "teleport", "params": {}}') is None
    assert validate("ifc", q, "no json here") is None


@pytest.mark.skipif(not QUESTIONS.exists(), reason="dataset not available")
@pytest.mark.parametrize("path,q,expected", [
    (SW, "Wie viele Räume mit der Bezeichnung «Schlafzimmer» gibt es in diesem Geschoss?", 5),
    (SW, "Wie gross ist die Nettofläche von Raum 7.01 («Balkon») in m²?", 15.47),
    (IFC, "Kui suur on ruumi „KORIDOR (119)“ netopõrandapind korrusel „1.korrus“ (m²)?", 63.84),
])
def test_solvers_answer_translations(path, q, expected):
    from plansight.solvers import route

    a = route(path).solve(path, q)
    assert a is not None and abs(a.value - expected) <= 0.02 * expected and a.evidence
