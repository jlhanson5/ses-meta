"""The eval harness itself gets a free gate test.

With the gold-aligned fake, the harness must score 100% and zero false-excludes,
which proves the scoring plumbing (pass -> aggregate -> gold mapping) is right.
A deliberately wrong fake must be caught as a false-exclude.
"""
import json

from llm.fake import ScriptedClient

from screen.evals.run_eval import evaluate, _gold_aligned_fake


def test_gold_aligned_fake_scores_perfect():
    report = evaluate(_gold_aligned_fake())
    assert report["accuracy"] == 1.0
    assert report["false_excludes"] == 0


def test_false_exclude_is_detected():
    # a fake that excludes everything must trip the false-exclude counter,
    # because the gold set contains includes.
    always_exclude = ScriptedClient(
        responder=lambda p, s, m: json.dumps(
            {"decision": "exclude", "criteria_hit": [], "reason": "x",
             "confidence": 0.95}),
        model_version="fake:always-exclude")
    report = evaluate(always_exclude)
    assert report["false_excludes"] > 0
