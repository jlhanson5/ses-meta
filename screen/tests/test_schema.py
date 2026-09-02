import pytest

from screen.schema import Decision, DecisionError, parse_decision


def test_valid_decision():
    d = parse_decision({"decision": "include", "criteria_hit": [],
                        "reason": "ok", "confidence": 0.9})
    assert d.decision == "include"
    assert d.confidence == 0.9


def test_invalid_label_raises():
    with pytest.raises(DecisionError):
        parse_decision({"decision": "maybe", "confidence": 0.5})


def test_missing_decision_raises():
    with pytest.raises(DecisionError):
        parse_decision({"confidence": 0.5})


def test_confidence_clamped():
    assert parse_decision({"decision": "exclude", "confidence": 1.7}).confidence == 1.0
    assert parse_decision({"decision": "exclude", "confidence": -3}).confidence == 0.0


def test_confidence_non_numeric_raises():
    with pytest.raises(DecisionError):
        parse_decision({"decision": "exclude", "confidence": "high"})


def test_reason_truncated_to_25_words():
    long_reason = " ".join(["w"] * 40)
    d = parse_decision({"decision": "uncertain", "reason": long_reason,
                        "confidence": 0.5})
    assert len(d.reason.split()) == 25


def test_criteria_string_coerced_to_list():
    d = parse_decision({"decision": "exclude", "criteria_hit": "animal",
                        "confidence": 0.9})
    assert d.criteria_hit == ["animal"]


def test_review_or_meta_flag():
    d = parse_decision({"decision": "exclude", "criteria_hit": ["review_or_meta"],
                        "confidence": 0.95})
    assert d.is_review_or_meta
