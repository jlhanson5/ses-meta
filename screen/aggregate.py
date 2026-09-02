"""Combine two independent passes into a final routing decision.

The rule set, verbatim from the spec, in the order checked:

1. Passes disagree            -> queue (pass_disagreement)
2. Either/both uncertain      -> queue (model_uncertain)   [covered by #1 when
                                 one side is uncertain; explicit when both are]
3. Agreed exclude, but either
   pass confidence < 0.8      -> queue (low_confidence_exclude)
4. Agreed exclude, both >=0.8 -> exclude
5. Agreed include            -> include (provisional; advances to full text)

Nothing is excluded on a single low-confidence call: an exclude needs both
passes to agree AND both to be confident. A disagreement or any uncertainty
sends the record to a human. Includes are provisional and advance regardless of
confidence, because an include here only means "keep for full-text screening",
never a final inclusion.

`is_refmine_target` is set when the agreed exclude reason is review_or_meta, so
the reference miner can harvest its citations later.
"""
from __future__ import annotations

from dataclasses import dataclass

from .schema import Decision

EXCLUDE_CONFIDENCE_FLOOR = 0.8

# roll-up decision labels
INCLUDE = "include"
EXCLUDE = "exclude"
QUEUED = "queued"


@dataclass
class Aggregated:
    final: str                 # include | exclude | queued
    routed_to_queue: bool
    queue_reason: str | None   # why it queued, or None
    is_refmine_target: bool
    criteria_hit: list[str]


def aggregate(pass_a: Decision, pass_b: Decision) -> Aggregated:
    a, b = pass_a.decision, pass_b.decision
    merged_hits = sorted(set(pass_a.criteria_hit) | set(pass_b.criteria_hit))

    # 1. disagreement (this also captures "one side uncertain, other not")
    if a != b:
        return Aggregated(QUEUED, True, "pass_disagreement", False, merged_hits)

    # 2. both uncertain
    if a == "uncertain":
        return Aggregated(QUEUED, True, "model_uncertain", False, merged_hits)

    # from here both agree and neither is uncertain
    if a == "exclude":
        if min(pass_a.confidence, pass_b.confidence) < EXCLUDE_CONFIDENCE_FLOOR:
            return Aggregated(QUEUED, True, "low_confidence_exclude", False,
                              merged_hits)
        refmine = pass_a.is_review_or_meta and pass_b.is_review_or_meta
        return Aggregated(EXCLUDE, False, None, refmine, merged_hits)

    # a == include, agreed
    return Aggregated(INCLUDE, False, None, False, merged_hits)


def agreement(pass_a: Decision, pass_b: Decision) -> bool:
    """Did the two passes land on the same decision label?"""
    return pass_a.decision == pass_b.decision
