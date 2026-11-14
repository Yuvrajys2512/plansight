from plansight.solvers.room_labels import find_labels, is_label
from plansight.vlm.openings import merge_adjacent, nms_any


def test_bedroom_labels_multilingual():
    for t in ["CHAMBRE 1", "CHAMBRE3", "Bed1", "BEDROOM#2", "Master bedroom", "MAINBEDROOM", "MH2", "Schlafzimmer",
              "Camera", "卧室"]:
        assert is_label(t, "bedroom"), t
    for t in ["BATH", "SALON", "BEDSIDE", "CUISINE", "12.5 m2", "CH"]:
        assert not is_label(t, "bedroom"), t


def test_toilet_labels_multilingual():
    for t in ["WC", "W.C.", "W0", "TOIL.", "BAINS", "SDB", "M.BATH", "BATHROOM2", "ENSUITE", "Douche", "PH", "卫生间"]:
        assert is_label(t, "toilet"), t
    for t in ["BATHTUB", "TUB", "LAVATORY", "KITCHEN", "WALK-IN"]:
        assert not is_label(t, "toilet"), t


def test_two_token_label_and_dedupe():
    toks = [("MASTER", 0.9, (0, 0, 60, 10)), ("BEDROOM", 0.9, (65, 0, 130, 10)),
            ("Bed2", 0.9, (300, 300, 340, 310)), ("Bed2", 0.8, (301, 300, 341, 310))]
    labels = find_labels(toks, "bedroom")
    assert len(labels) == 2


def test_window_grouping_and_class_agnostic_nms():
    assert len(merge_adjacent([(0, 0, 10, 4), (12, 0, 22, 4), (100, 0, 110, 4)], gap=6)) == 2
    cands = [("door", 0.9, (0, 0, 10, 10)), ("window", 0.5, (1, 1, 10, 10)), ("window", 0.6, (50, 50, 60, 60))]
    assert len(nms_any(cands)) == 2
