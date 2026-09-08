import json

from llm.fake import ScriptedClient

from extract.document import Document, Segment
from extract.extract import extract_study, unrecognized_cohorts
from extract.prompts import EXTRACT, VERIFY, load_prompt
from extract.verify import verify_effect


def _doc(text="income and hippocampal volume in ABCD", sid="s1"):
    return Document(sid, "test", [Segment("Table 2", text)])


EXTRACT_REPLY = json.dumps({"effects": [{
    "cohort_name": "ABCD", "n": 500, "roi": "hippocampus", "hemisphere": "left",
    "ses_construct": "income", "ses_timing": "concurrent", "effect_type": "r",
    "effect_value": 0.2, "p_value": 0.01, "extraction_confidence": 0.95,
    "page_number": "Table 2", "verbatim_quote": "r = 0.2, N = 500, p = 0.01",
    "provenance": {
        "effect_value": {"page": "Table 2", "quote": "r = 0.2"},
        "n": {"page": "Table 2", "quote": "N = 500"},
        "p_value": {"page": "Table 2", "quote": "p = 0.01"}},
}]})


def test_extract_returns_effect_with_cohort_assigned():
    client = ScriptedClient(mapping={"STUDY FULL TEXT": EXTRACT_REPLY})
    result = extract_study(client, load_prompt(EXTRACT), _doc())
    assert len(result.effects) == 1
    e = result.effects[0]
    assert e.roi == "hippocampus"
    assert e.effect_value == 0.2
    assert e.sample_overlap_group == "ABCD"       # assigned from registry


def test_extract_flags_unrecognized_cohort():
    reply = json.dumps({"effects": [{
        "cohort_name": "Springfield Youth Study", "roi": "amygdala",
        "effect_value": 0.1, "effect_type": "r", "extraction_confidence": 0.9,
        "page_number": "p.3", "verbatim_quote": "r = 0.1",
        "provenance": {"effect_value": {"page": "p.3", "quote": "r = 0.1"}}}]})
    client = ScriptedClient(mapping={"STUDY FULL TEXT": reply})
    result = extract_study(client, load_prompt(EXTRACT),
                           _doc(text="Springfield Youth Study amygdala"))
    assert result.effects[0].sample_overlap_group is None
    assert unrecognized_cohorts(result) == ["Springfield Youth Study"]


def test_extract_parse_error_is_not_silent():
    client = ScriptedClient(mapping={"STUDY FULL TEXT": "not json"})
    result = extract_study(client, load_prompt(EXTRACT), _doc())
    assert result.effects == [] and result.error


def _effect_for_verify():
    client = ScriptedClient(mapping={"STUDY FULL TEXT": EXTRACT_REPLY})
    return extract_study(client, load_prompt(EXTRACT), _doc()).effects[0]


def test_verify_confirms_when_quotes_support():
    eff = _effect_for_verify()
    verdicts = json.dumps({"verdicts": [
        {"index": 0, "verdict": "confirm", "confidence": 0.95},
        {"index": 1, "verdict": "confirm", "confidence": 0.95},
        {"index": 2, "verdict": "confirm", "confidence": 0.95}]})
    client = ScriptedClient(mapping={"CLAIMS": verdicts})
    v = verify_effect(client, load_prompt(VERIFY), eff)
    assert v.confirmed and not v.needs_review


def test_verify_disputes_route_to_review():
    eff = _effect_for_verify()
    verdicts = json.dumps({"verdicts": [
        {"index": 0, "verdict": "confirm", "confidence": 0.9},
        {"index": 1, "verdict": "dispute", "confidence": 0.9},
        {"index": 2, "verdict": "confirm", "confidence": 0.9}]})
    client = ScriptedClient(mapping={"CLAIMS": verdicts})
    v = verify_effect(client, load_prompt(VERIFY), eff)
    assert not v.confirmed and v.needs_review
    assert "effect_value" in v.reason


def test_verify_low_confidence_routes_to_review():
    client = ScriptedClient(mapping={"STUDY FULL TEXT": EXTRACT_REPLY.replace('0.95', '0.5')})
    eff = extract_study(client, load_prompt(EXTRACT), _doc()).effects[0]
    verdicts = json.dumps({"verdicts": [
        {"index": i, "verdict": "confirm", "confidence": 0.9} for i in range(3)]})
    vclient = ScriptedClient(mapping={"CLAIMS": verdicts})
    v = verify_effect(vclient, load_prompt(VERIFY), eff)
    assert v.needs_review and v.reason == "low_confidence"
