import json

from llm.fake import ScriptedClient

from extract import db as edb
from extract.reverify import reverify_all
from extract.schema import parse_effect, effect_from_row


def _eff(**over):
    d = {"roi": "hippocampus", "effect_value": 0.06, "effect_type": "beta",
         "hemisphere": "left", "ses_construct": "income", "ses_timing": "concurrent",
         "age_range": "9 to 10 years", "extraction_confidence": 0.95,
         "page_number": "Table 2", "verbatim_quote": "beta = 0.06",
         "provenance": {
             "effect_value": {"page": "Table 2", "quote": "beta = 0.06"},
             "age_range": {"page": "Results", "quote": "aged 9 and 10 years"}}}
    d.update(over)
    return parse_effect(d, study_id="s1")


def test_provenance_round_trips_through_db(db):
    edb.save_effect(db, _eff(), prompt_hash="h", model_version="m",
                    verified="disputed", needs_review=True, review_reason="disputed: age_range")
    row = edb.all_effects(db)[0]
    eff = effect_from_row(row)
    assert eff.provenance["age_range"]["quote"] == "aged 9 and 10 years"
    assert eff.age_range == "9 to 10 years"


def test_reverify_clears_stale_dispute(db):
    edb.save_effect(db, _eff(), prompt_hash="h", model_version="m",
                    verified="disputed", needs_review=True,
                    review_reason="disputed: age_range")
    # a verifier that now confirms every claim (the range-aware v2 behavior)
    confirms = ScriptedClient(responder=lambda p, s, m: json.dumps(
        {"verdicts": [{"index": i, "verdict": "confirm", "confidence": 0.95}
                      for i in range(10)]}))
    result = reverify_all(db, confirms)
    assert result["changed"] == 1
    row = edb.all_effects(db)[0]
    assert row["needs_review"] == 0
    assert row["verified"] == "confirmed"
