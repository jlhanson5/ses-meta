import pytest

from extract.schema import Effect, ExtractionError, parse_effect


def _base(**over):
    d = {
        "roi": "hippocampus",
        "effect_value": 0.2,
        "effect_type": "r",
        "n": 200,
        "p_value": 0.01,
        "extraction_confidence": 0.95,
        "page_number": "Table 2",
        "verbatim_quote": "r = 0.2, N = 200, p = 0.01",
        "provenance": {
            "effect_value": {"page": "Table 2", "quote": "r = 0.2"},
            "n": {"page": "Table 2", "quote": "N = 200"},
            "p_value": {"page": "Table 2", "quote": "p = 0.01"},
        },
    }
    d.update(over)
    return d


def test_roi_required():
    with pytest.raises(ExtractionError):
        parse_effect({"roi": "thalamus", "extraction_confidence": 0.5}, study_id="s1")


def test_sourced_numeric_survives():
    eff = parse_effect(_base(), study_id="s1")
    assert eff.effect_value == 0.2
    assert eff.n == 200
    assert eff.p_value == 0.01


def test_numeric_without_provenance_is_nulled():
    # effect_value present but no provenance entry and no quote -> nulled
    obj = _base(provenance={}, verbatim_quote=None, page_number=None)
    eff = parse_effect(obj, study_id="s1")
    assert eff.effect_value is None
    assert eff.n is None


def test_null_effect_value_forces_zero_confidence():
    obj = _base(effect_value=None, provenance={})
    eff = parse_effect(obj, study_id="s1")
    assert eff.effect_value is None
    assert eff.extraction_confidence == 0.0


def test_enum_coercion_unknown_becomes_null():
    eff = parse_effect(_base(ses_construct="vibes", hemisphere="middle"), study_id="s1")
    assert eff.ses_construct is None
    assert eff.hemisphere is None


def test_enum_valid_passes():
    eff = parse_effect(_base(ses_construct="income-to-needs", hemisphere="left"),
                       study_id="s1")
    assert eff.ses_construct == "income-to-needs"
    assert eff.hemisphere == "left"


def test_confidence_clamped():
    eff = parse_effect(_base(extraction_confidence=5), study_id="s1")
    assert eff.extraction_confidence == 1.0
