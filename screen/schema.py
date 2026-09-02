"""The screening decision schema and its validator.

Every model pass must return exactly:
    {"decision": "include|exclude|uncertain",
     "criteria_hit": [...],
     "reason": "<=25 words",
     "confidence": 0.0-1.0}

`parse_decision` is strict but forgiving of the harmless: it coerces a missing
criteria_hit to [], clamps confidence to [0,1], and truncates an over-long
reason. It rejects the load-bearing errors: an unknown decision label, or a
non-numeric confidence. A screening decision is never invented here; a
malformed decision raises so the caller can route the record to review instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_DECISIONS = ("include", "exclude", "uncertain")
MAX_REASON_WORDS = 25


class DecisionError(ValueError):
    """Model reply did not conform to the decision schema."""


@dataclass
class Decision:
    decision: str
    criteria_hit: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.decision not in VALID_DECISIONS:
            raise DecisionError(f"invalid decision {self.decision!r}")
        if not isinstance(self.confidence, (int, float)):
            raise DecisionError(f"confidence not numeric: {self.confidence!r}")
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        words = self.reason.split()
        if len(words) > MAX_REASON_WORDS:
            self.reason = " ".join(words[:MAX_REASON_WORDS])
        if not isinstance(self.criteria_hit, list):
            raise DecisionError("criteria_hit must be a list")
        self.criteria_hit = [str(c) for c in self.criteria_hit]

    @property
    def is_review_or_meta(self) -> bool:
        return "review_or_meta" in self.criteria_hit


def parse_decision(obj: dict[str, Any]) -> Decision:
    if "decision" not in obj:
        raise DecisionError(f"missing 'decision' in {obj!r}")
    decision = str(obj["decision"]).strip().lower()
    criteria = obj.get("criteria_hit", []) or []
    if isinstance(criteria, str):
        criteria = [criteria]
    reason = str(obj.get("reason", "")).strip()
    confidence = obj.get("confidence", 0.0)
    return Decision(decision=decision, criteria_hit=list(criteria),
                    reason=reason, confidence=confidence)
