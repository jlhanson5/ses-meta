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

# The fixed exclude vocabulary. The model is asked to tag excludes from this set;
# the normalizer below is the deterministic guarantee that only these land in the
# database, so off-schema tags the model invents ("not_a_study", "no SES
# indicator") never pollute the exclude analytics. Two names beyond the original
# six give a home to reasons the criteria already imply: no SES measure at all,
# and wrong publication type (editorial, commentary, protocol, news).
CANONICAL_EXCLUDE_TAGS = (
    "animal",
    "review_or_meta",
    "case_report",
    "no_volume_outcome",
    "ses_nuisance_only",
    "sample_lt_20",
    "no_ses_measure",
    "wrong_pub_type",
)

# internal / non-exclude tags that are still allowed to pass through untouched
_INTERNAL_TAGS = ("parse_error", "no_abstract", "other")
ALLOWED_TAGS = set(CANONICAL_EXCLUDE_TAGS) | set(_INTERNAL_TAGS)

_DROP = object()   # sentinel: an alias that means "discard this tag"

# common off-schema variants the model emits, mapped to the canonical tag
_TAG_ALIASES: dict[str, object] = {
    "no_ses_indicator": "no_ses_measure",
    "no_ses": "no_ses_measure",
    "ses_absent": "no_ses_measure",
    "no_ses_exposure": "no_ses_measure",
    "not_a_study": "wrong_pub_type",
    "editorial": "wrong_pub_type",
    "commentary": "wrong_pub_type",
    "protocol": "wrong_pub_type",
    "erratum": "wrong_pub_type",
    "news": "wrong_pub_type",
    "review": "review_or_meta",
    "meta_analysis": "review_or_meta",
    "systematic_review": "review_or_meta",
    # uncertainty is a decision, not an exclude tag: drop these
    "outcome_unclear": _DROP,
    "unclear": _DROP,
    "na": _DROP,
    "n_a": _DROP,
    "none": _DROP,
}


def normalize_tags(tags: list) -> list[str]:
    """Map criteria_hit to the fixed vocabulary.

    Lowercases, unifies separators, applies aliases, drops uncertainty markers,
    and collapses anything still off-schema to "other" so a single bucket
    absorbs the noise instead of scattering it. Order preserved, deduped.
    """
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        key = str(t).strip().lower().replace("-", "_").replace(" ", "_")
        if not key:
            continue
        mapped = _TAG_ALIASES.get(key, key)
        if mapped is _DROP:
            continue
        if mapped not in ALLOWED_TAGS:
            mapped = "other"
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out


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
        self.criteria_hit = normalize_tags([str(c) for c in self.criteria_hit])

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
