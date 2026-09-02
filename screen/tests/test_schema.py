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


# --- tag normalization (pinning the exclude vocabulary) ---

from screen.schema import normalize_tags, CANONICAL_EXCLUDE_TAGS


def test_offschema_tag_maps_to_canonical():
    assert normalize_tags(["not_a_study"]) == ["wrong_pub_type"]
    assert normalize_tags(["no SES indicator"]) == ["no_ses_measure"]
    assert normalize_tags(["systematic review"]) == ["review_or_meta"]


def test_uncertainty_marker_dropped():
    assert normalize_tags(["outcome_unclear"]) == []


def test_unknown_tag_collapses_to_other():
    assert normalize_tags(["some_weird_reason"]) == ["other"]


def test_canonical_tags_pass_through():
    for t in CANONICAL_EXCLUDE_TAGS:
        assert normalize_tags([t]) == [t]


def test_dedup_after_mapping():
    assert normalize_tags(["review", "review_or_meta"]) == ["review_or_meta"]


def test_internal_tags_preserved():
    assert normalize_tags(["parse_error"]) == ["parse_error"]
    assert normalize_tags(["no_abstract"]) == ["no_abstract"]


def test_decision_normalizes_criteria_hit():
    d = parse_decision({"decision": "exclude", "criteria_hit": ["not_a_study"],
                        "confidence": 0.9})
    assert d.criteria_hit == ["wrong_pub_type"]
