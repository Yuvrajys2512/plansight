import pytest

from plansight.ocr import OCRToken
from plansight.ocr import rapid as ocr_module
from plansight.solvers import cubicasa_text as module
from plansight.solvers.cubicasa_text import CubicasaTextSolver, _template


@pytest.mark.parametrize("question,kind", [
    ("How many saunas are on this floor plan?", "sauna"),
    ("Kuinka monta saunaa pohjapiirustuksessa on?", "sauna"),
    ("How many kitchens (including kitchenettes) are on this floor plan?", "kitchen"),
    ("How many sinks and wash basins (kitchen and bathroom combined) are drawn on this floor plan?", None),
    ("Kuinka monta pesu- ja tiskiallasta (keitti? ja kylpytilat yhteens?) pohjapiirustukseen on piirretty?", None),
    ("Kuinka monta keitti\u00f6t\u00e4 pohjapiirustuksessa on?", "kitchen"),
    ("How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?", "bedroom"),
    ("Kuinka monta makuuhuonetta (MH) pohjapiirustuksessa on?", "bedroom"),
    ("How many bathrooms or washrooms (e.g. KH, KPH, PH, PESUH, SH)?", "bathroom"),
    ("Kuinka monta kylpy- tai pesuhuonetta (esim. KH, KPH, PH, PESUH, SH) pohjapiirustuksessa on, erillisi\u00e4 WC-tiloja lukuun ottamatta?", "bathroom"),
    ("How many separate WC rooms (toilet rooms marked WC)?", "wc_room"),
    ("Kuinka monta erillist\u00e4 WC-tilaa pohjapiirustuksessa on?", "wc_room"),
    ("How many balconies (parveke, including glazed balconies)?", "balcony"),
    ("Kuinka monta parveketta pohjapiirustuksessa on?", "balcony"),
])
def test_question_templates(question, kind):
    assert _template(question) == kind


def test_solver_counts_labels_and_returns_pixel_evidence(monkeypatch):
    path = "data/cubicasa5k/example.png"
    tokens = [
        OCRToken("MH1", (10, 20, 30, 40), 0.99),
        OCRToken("MH 2", (50, 60, 70, 80), 0.96),
        OCRToken("KH", (90, 100, 110, 120), 0.98),
        OCRToken("MH+3", (120, 130, 140, 150), 0.97),
        OCRToken("SUUNTAA-ANTAVA", (0, 0, 10, 5), 0.99),
    ]
    monkeypatch.setattr(module, "read_text", lambda _: tokens)
    answer = CubicasaTextSolver().solve(path, "Kuinka monta makuuhuonetta (MH) pohjapiirustuksessa on?")
    assert answer is not None
    assert answer.value == 3
    assert [e.bbox for e in answer.evidence] == [(10, 20, 30, 40), (50, 60, 70, 80), (120, 130, 140, 150)]
    assert all(e.file == path and e.page == 0 for e in answer.evidence)


def test_solver_returns_zero_only_when_room_labels_were_read(monkeypatch):
    monkeypatch.setattr(module, "read_text", lambda _: [
        OCRToken("MH", (1, 2, 3, 4), 0.99),
        OCRToken("KH", (5, 6, 7, 8), 0.99),
    ])
    answer = CubicasaTextSolver().solve(
        "data/cubicasa5k/example.png", "How many saunas are on this floor plan?")
    assert answer is not None and answer.value == 0 and answer.evidence == []


def test_solver_abstains_on_title_block_only_and_visual_templates(monkeypatch):
    monkeypatch.setattr(module, "read_text", lambda _: [OCRToken("CUBICASA", (1, 2, 3, 4), 0.99)])
    solver = CubicasaTextSolver()
    assert solver.solve("data/cubicasa5k/example.png", "How many saunas are on this floor plan?") is None
    assert solver.solve("data/cubicasa5k/example.png", "How many toilet bowls are drawn?") is None
    assert solver.solve("data/other/example.png", "How many saunas are on this floor plan?") is None


def test_low_confidence_matching_label_causes_abstention(monkeypatch):
    monkeypatch.setattr(module, "read_text", lambda _: [
        OCRToken("MH", (1, 2, 3, 4), 0.99), OCRToken("KPH", (5, 6, 7, 8), 0.12),
    ])
    assert CubicasaTextSolver().solve(
        "data/cubicasa5k/example.png", "How many bathrooms or washrooms?") is None


def test_ocr_results_are_cached_on_disk(monkeypatch, tmp_path):
    image = tmp_path / "sheet.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setattr(ocr_module, "REPO", tmp_path)
    calls = []

    class FakeOCR:
        def __call__(self, _path):
            calls.append(1)
            return [([[1, 2], [5, 2], [5, 8], [1, 8]], "MH", 0.9)], 0.01

    monkeypatch.setattr(ocr_module, "_engine", lambda: FakeOCR())
    first = ocr_module.read_text(image)
    second = ocr_module.read_text(image)
    assert first == second
    assert len(calls) == 1
    assert first[0].bbox == (1.0, 2.0, 5.0, 8.0)
    assert list((tmp_path / "cache" / "ocr").glob("*.json"))


def test_room_summaries_and_dimension_suffixes(monkeypatch):
    tokens = [
        OCRToken("MH", (0, 0, 10, 10), 0.99),
        OCRToken("KPH 3.6", (10, 10, 20, 20), 0.98),
        OCRToken("2H+KK+S", (20, 20, 40, 40), 0.97),
        OCRToken("TUPAK.", (40, 40, 60, 60), 0.96),
    ]
    monkeypatch.setattr(module, "read_text", lambda _: tokens)
    solver = CubicasaTextSolver()
    path = "data/cubicasa5k/example.png"
    kitchen = solver.solve(path, "How many kitchens are on this floor plan?")
    sauna = solver.solve(path, "How many saunas are on this floor plan?")
    bathroom = solver.solve(path, "How many bathrooms or washrooms?")
    assert kitchen is not None and kitchen.value == 2
    assert sauna is not None and sauna.value == 1
    assert bathroom is not None and bathroom.value == 1


def test_known_ocr_confusions_and_full_bedroom_word(monkeypatch):
    tokens = [
        OCRToken("MH", (0, 0, 10, 10), 0.99),
        OCRToken("MAKUUH", (10, 10, 20, 20), 0.95),
        OCRToken("GH", (20, 20, 30, 30), 0.92),
        OCRToken("PE", (30, 30, 40, 40), 0.93),
    ]
    monkeypatch.setattr(module, "read_text", lambda _: tokens)
    solver = CubicasaTextSolver()
    path = "data/cubicasa5k/example.png"
    bedroom = solver.solve(path, "How many bedrooms are on this floor plan?")
    bathroom = solver.solve(path, "How many bathrooms are on this floor plan?")
    assert bedroom is not None and bedroom.value == 2
    assert bathroom is not None and bathroom.value == 2


def test_solver_abstains_when_ocr_fails_or_has_no_confident_room_labels(monkeypatch):
    solver = CubicasaTextSolver()
    path = "data/cubicasa5k/example.png"
    monkeypatch.setattr(module, "read_text", lambda _: (_ for _ in ()).throw(ValueError("bad image")))
    assert solver.solve(path, "How many bedrooms are on this floor plan?") is None
    monkeypatch.setattr(module, "read_text", lambda _: [OCRToken("MH", (0, 0, 5, 5), 0.1)])
    assert solver.solve(path, "How many kitchens are on this floor plan?") is None
