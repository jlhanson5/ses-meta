"""Screening eval: run the real prompts against the LLM contract and score.

This is the periodic (paid) lane. It runs both passes on each gold abstract,
aggregates them exactly as production does, and scores the final routing against
hand labels. Two numbers gate a pass:

  accuracy       final routing matches gold, where gold 'uncertain' is correct
                 iff the record routed to the human queue.
  false_exclude  a gold 'include' that the pipeline excluded. This is the costly
                 error in a meta-analysis (a real study dropped), so the gate
                 requires ZERO of them, independent of accuracy.

Run it two ways:
  --client fake    gold-aligned fake, self-checks the harness (free, deterministic)
  --client claude  local Claude Code, measures real model quality (on Jamie's box)

    python -m screen.evals.run_eval --client claude --model sonnet --threshold 0.75
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llm.service import LLMError, JSONError, complete_json

from ..aggregate import aggregate
from ..prompts import load_all
from ..schema import DecisionError, parse_decision, Decision

GOLD = Path(__file__).resolve().parent / "gold.jsonl"

# map an aggregate final label to the gold vocabulary
FINAL_TO_GOLD = {"include": "include", "exclude": "exclude", "queued": "uncertain"}


@dataclass
class ItemResult:
    id: str
    gold: str
    got: str
    correct: bool
    false_exclude: bool


def load_gold(path: Path = GOLD) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _one_pass(client, prompt, item, model) -> Decision:
    rendered = prompt.render(item["title"], item["abstract"])
    try:
        return parse_decision(complete_json(client, rendered, model=model))
    except (LLMError, JSONError, DecisionError) as exc:
        return Decision("uncertain", ["parse_error"], str(exc)[:60], 0.0)


def evaluate(client, *, model: Optional[str] = None,
             gold_path: Path = GOLD) -> dict:
    prompts = load_all()
    gold = load_gold(gold_path)
    results: list[ItemResult] = []
    for item in gold:
        da = _one_pass(client, prompts["A"], item, model)
        db_ = _one_pass(client, prompts["B"], item, model)
        final = aggregate(da, db_).final
        got = FINAL_TO_GOLD[final]
        correct = got == item["gold"]
        false_exclude = item["gold"] == "include" and final == "exclude"
        results.append(ItemResult(item["id"], item["gold"], got, correct,
                                  false_exclude))
    n = len(results)
    acc = sum(r.correct for r in results) / n if n else 0.0
    fe = sum(r.false_exclude for r in results)
    return {"n": n, "accuracy": acc, "false_excludes": fe, "results": results,
            "model_version": client.model_version}


def _gold_aligned_fake(gold_path: Path = GOLD):
    """A fake that answers each gold item with its label, for harness self-check."""
    from llm.fake import ScriptedClient
    gold = load_gold(gold_path)

    def responder(prompt, system, model):
        skeptical = "pass B" in prompt or "skeptical" in prompt
        for item in gold:
            if item["title"] in prompt:
                g = item["gold"]
                if g == "include":
                    return json.dumps({"decision": "include", "criteria_hit": [],
                                       "reason": "gold", "confidence": 0.9})
                if g == "exclude":
                    return json.dumps({"decision": "exclude", "criteria_hit": [],
                                       "reason": "gold", "confidence": 0.95})
                # uncertain: both passes uncertain -> queued
                return json.dumps({"decision": "uncertain", "criteria_hit": [],
                                   "reason": "gold", "confidence": 0.4})
        return json.dumps({"decision": "uncertain", "criteria_hit": [],
                           "reason": "no match", "confidence": 0.3})

    return ScriptedClient(responder=responder, model_version="fake:gold-aligned")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Screening eval harness.")
    ap.add_argument("--client", choices=["fake", "claude"], default="fake")
    ap.add_argument("--model", default=None)
    ap.add_argument("--threshold", type=float, default=0.75)
    args = ap.parse_args(argv)

    if args.client == "fake":
        client = _gold_aligned_fake()
    else:
        from llm.claude_code import ClaudeCodeClient
        client = ClaudeCodeClient(default_model=args.model)

    report = evaluate(client, model=args.model)
    for r in report["results"]:
        flag = "ok " if r.correct else "MISS"
        fe = " FALSE-EXCLUDE" if r.false_exclude else ""
        print(f"  {flag} {r.id}  gold={r.gold:9s} got={r.got:9s}{fe}")
    print(f"\nmodel      : {report['model_version']}")
    print(f"n          : {report['n']}")
    print(f"accuracy   : {report['accuracy']:.0%}")
    print(f"false excl : {report['false_excludes']}")

    passed = report["accuracy"] >= args.threshold and report["false_excludes"] == 0
    print(f"threshold  : {args.threshold:.0%} accuracy AND zero false-excludes -> "
          f"{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
