"""Extraction eval: run the real prompt against gold full texts and score.

The paid lane. For each gold study it runs the real extraction prompt through
the llm contract, matches extracted effects to gold effects by ROI, and scores
the numeric fields (effect_value, n, p_value) against the gold numbers within a
small tolerance. Two gates:

  field_accuracy   fraction of gold numeric fields recovered correctly.
  fabrications     an extracted numeric value with no provenance (should be
                   impossible: schema.py nulls those) OR a value reported for a
                   gold study that has no effects. Gate requires ZERO.

Run with --client fake for a deterministic harness self-check (a gold-aligned
fake), or --client claude to measure real quality on the researcher's machine.

    python -m extract.evals.run_eval --client claude --model opus
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm.service import LLMError, JSONError, complete_json

from ..document import from_tagged
from ..extract import extract_study
from ..prompts import EXTRACT, load_prompt

GOLD = Path(__file__).resolve().parent / "gold.jsonl"
TOL = 0.011


def load_gold(path: Path = GOLD) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _match(extracted, gold_eff):
    for e in extracted:
        if e.roi == gold_eff["roi"]:
            return e
    return None


def _num_ok(got, want) -> bool:
    return got is not None and want is not None and abs(float(got) - float(want)) <= TOL


def evaluate(client, *, model=None, gold_path: Path = GOLD) -> dict:
    prompt = load_prompt(EXTRACT)
    gold = load_gold(gold_path)
    fields = ("effect_value", "n", "p_value")
    correct = total = 0
    fabrications = 0
    per_study = {}

    for item in gold:
        doc = from_tagged(item["fulltext"], study_id=item["study_id"])
        result = extract_study(client, prompt, doc, model=model)
        exp = item["expected"]

        if not exp:
            # a review/no-data study: any extracted effect with a value is a fabrication
            fabs = sum(1 for e in result.effects if e.effect_value is not None)
            fabrications += fabs
            per_study[item["study_id"]] = {"expected": 0, "got": len(result.effects),
                                           "fabrications": fabs}
            continue

        study_correct = study_total = 0
        for g in exp:
            e = _match(result.effects, g)
            for f in fields:
                if f not in g:
                    continue
                study_total += 1
                total += 1
                if e is not None and _num_ok(getattr(e, f), g[f]):
                    study_correct += 1
                    correct += 1
            # a matched effect whose value lacks provenance would be nulled, so a
            # non-null value here always has provenance; nothing to add.
        per_study[item["study_id"]] = {"expected": len(exp), "got": len(result.effects),
                                       "correct": study_correct, "total": study_total}

    acc = correct / total if total else 0.0
    return {"field_accuracy": acc, "fabrications": fabrications, "n_fields": total,
            "per_study": per_study, "model_version": client.model_version}


def _gold_aligned_fake(gold_path: Path = GOLD):
    """A fake that returns each gold study's expected effects, for harness self-check."""
    from llm.fake import ScriptedClient
    gold = load_gold(gold_path)

    def responder(prompt, system, model):
        body = prompt.split("STUDY FULL TEXT:")[-1]
        for item in gold:
            # match on a distinctive locator/number from the study text
            key = item["fulltext"].split("]]")[-1][:25].strip()
            if key and key in body:
                effects = []
                for g in item["expected"]:
                    q = f"value {g.get('effect_value')}"
                    effects.append({
                        "roi": g["roi"], "hemisphere": g.get("hemisphere"),
                        "effect_type": g.get("effect_type"),
                        "effect_value": g.get("effect_value"),
                        "n": g.get("n"), "p_value": g.get("p_value"),
                        "extraction_confidence": 0.95,
                        "page_number": "Table", "verbatim_quote": q,
                        "provenance": {
                            "effect_value": {"page": "Table", "quote": q},
                            "n": {"page": "Table", "quote": q},
                            "p_value": {"page": "Table", "quote": q}},
                    })
                return json.dumps({"effects": effects})
        return json.dumps({"effects": []})

    return ScriptedClient(responder=responder, model_version="fake:gold-aligned")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extraction eval harness.")
    ap.add_argument("--client", choices=["fake", "claude"], default="fake")
    ap.add_argument("--model", default=None)
    ap.add_argument("--threshold", type=float, default=0.8)
    args = ap.parse_args(argv)

    if args.client == "fake":
        client = _gold_aligned_fake()
    else:
        from llm.claude_code import ClaudeCodeClient
        client = ClaudeCodeClient(default_model=args.model)

    rep = evaluate(client, model=args.model)
    for sid, s in rep["per_study"].items():
        print(f"  {sid}: {s}")
    print(f"\nmodel          : {rep['model_version']}")
    print(f"field accuracy : {rep['field_accuracy']:.0%} ({rep['n_fields']} fields)")
    print(f"fabrications   : {rep['fabrications']}")
    passed = rep["field_accuracy"] >= args.threshold and rep["fabrications"] == 0
    print(f"gate           : >={args.threshold:.0%} accuracy AND zero fabrications -> "
          f"{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
