"""Scoring rules used by Stoa's evaluation."""
from __future__ import annotations

import math


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def score(expected, predicted, question_type: str) -> dict:
    """Return status/correct; text answers are retained but unscored until P5."""
    if question_type == "text":
        return {"status": "unscored", "correct": None}
    actual = _number(expected)
    value = predicted.get("value") if isinstance(predicted, dict) else predicted
    got = _number(value)
    if actual is None or got is None:
        return {"status": "incorrect", "correct": False}
    if question_type == "count":
        correct = actual.is_integer() and got.is_integer() and actual == got
    elif question_type in {"area", "length", "volume"}:
        correct = actual == got if actual == 0 else abs(got - actual) / abs(actual) <= 0.02
    else:
        correct = actual == got
    return {"status": "correct" if correct else "incorrect", "correct": correct}
