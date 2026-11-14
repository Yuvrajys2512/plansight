from plansight.escalate import unsure_kinds


def test_confident_plan_is_not_escalated():
    dets = [("door", 0.9), ("door", 0.8), ("window", 0.7), ("window", 0.1)]
    assert unsure_kinds(dets, {"bedroom": [2, 2, 2]}) == []


def test_borderline_door_escalates_doors_only():
    assert unsure_kinds([("door", 0.3), ("window", 0.9)]) == ["door"]


def test_windows_need_three_borderline_hits():
    assert unsure_kinds([("window", 0.2)] * 2) == []
    assert unsure_kinds([("window", 0.2)] * 3) == ["window"]


def test_bedroom_readers_disagreeing_escalates():
    assert unsure_kinds([], {"bedroom": [1, 3, 2]}) == ["bedroom"]
    assert unsure_kinds([], {"bedroom": [2, 3, 2]}) == []
