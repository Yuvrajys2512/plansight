from plansight.eval.data import detect_language, sample_questions
from plansight.eval.scoring import score


def test_count_is_exact_and_rejects_non_integer_values():
    assert score(5, 5, "count")["correct"] is True
    assert score(5, "5", "count")["correct"] is True
    assert score(5, 5.01, "count")["correct"] is False
    assert score(5, None, "count")["status"] == "incorrect"


def test_measurement_two_percent_boundary():
    assert score(100, 102, "area")["correct"] is True
    assert score(100, 102.01, "length")["correct"] is False
    assert score(0, 0, "volume")["correct"] is True
    assert score(0, 0.01, "volume")["correct"] is False


def test_text_is_unscored_and_none_abstention_is_not_correct():
    assert score("oak", "oak", "text") == {"status": "unscored", "correct": None}
    assert score(3, None, "count") == {"status": "incorrect", "correct": False}


def test_sampler_is_deterministic_stratified_and_capped_per_source():
    rows = [
        {"id": f"{source}-{kind}-{lang}-{n}", "source": source, "type": kind, "lang": lang}
        for source in ("a", "b")
        for kind, lang, size in (("count", "en", 8), ("area", "de", 4), ("count", "fi", 2))
        for n in range(size)
    ]
    one = sample_questions(rows, per_source=7, seed=42)
    two = sample_questions(rows, per_source=7, seed=42)
    assert [r["id"] for r in one] == [r["id"] for r in two]
    assert len(one) == 14
    for source in ("a", "b"):
        selected = [r for r in one if r["source"] == source]
        assert len(selected) == 7
        assert {r["lang"] for r in selected} == {"en", "de", "fi"}


def test_language_detector_tags_supported_examples():
    assert detect_language("How many doors are on this floor plan?") == "en"
    assert detect_language("Wie viele Zimmer gibt es?") == "de"
    assert detect_language("Combien de pièces sont indiquées?") == "fr"
