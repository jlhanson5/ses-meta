"""The extraction eval harness gets a free gate test via a gold-aligned fake."""
import json

from llm.fake import ScriptedClient

from extract.evals.run_eval import evaluate, _gold_aligned_fake


def test_gold_aligned_fake_scores_high_and_no_fabrication():
    rep = evaluate(_gold_aligned_fake())
    assert rep["field_accuracy"] >= 0.8
    assert rep["fabrications"] == 0


def test_fabrication_on_review_study_is_caught():
    # a fake that always invents an effect must trip the fabrication counter,
    # because the gold set contains a review study with no effects (g4).
    def responder(prompt, system, model):
        return json.dumps({"effects": [{
            "roi": "hippocampus", "effect_value": 0.99, "effect_type": "r",
            "extraction_confidence": 0.9, "page_number": "p.1",
            "verbatim_quote": "invented", "provenance": {
                "effect_value": {"page": "p.1", "quote": "invented"}}}]})
    always = ScriptedClient(responder=responder, model_version="fake:fabricator")
    rep = evaluate(always)
    assert rep["fabrications"] > 0
