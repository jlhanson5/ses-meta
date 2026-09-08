"""The effect-row schema and its validator.

Loads schema.json and turns a model's raw dict into a validated Effect. Two
rules are enforced here in code, not left to the model's good behavior:

1. Provenance. Every numeric field (n, mean_age, pct_female, effect_value,
   se_or_ci, p_value) must carry both a locator (page_number) and a verbatim
   quote. If either is missing, the value is forced to null. A row whose
   effect_value ends up null is marked extraction_confidence 0. This makes "no
   locatable source -> null, never a guess" a property of the data, not a hope.

2. Enums. Categorical fields must be one of the allowed values or null; an
   unknown category becomes null rather than a fabricated category.

Nothing here converts or standardizes an effect size. Values pass through as
reported.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
_SCHEMA = json.loads(SCHEMA_PATH.read_text())

NUMERIC_FIELDS = tuple(_SCHEMA["numeric_fields"])
FIELDS = _SCHEMA["fields"]
ENUMS = {k: set(v["values"]) for k, v in FIELDS.items() if v.get("type") == "enum"}
PROVENANCE_FIELDS = tuple(k for k, v in FIELDS.items() if v.get("provenance"))


class ExtractionError(ValueError):
    """A row could not be coerced into the schema."""


@dataclass
class Effect:
    study_id: str
    roi: str
    extraction_confidence: float
    cohort_name: str | None = None
    sample_overlap_group: str | None = None
    n: float | None = None
    mean_age: float | None = None
    age_range: str | None = None
    pct_female: float | None = None
    sample_type: str | None = None
    ses_construct: str | None = None
    ses_timing: str | None = None
    hemisphere: str | None = None
    volume_pipeline: str | None = None
    icv_adjustment: str | None = None
    covariates: list | None = None
    effect_type: str | None = None
    effect_value: float | None = None
    se_or_ci: str | None = None
    p_value: float | None = None
    direction_coded_positive_means_higher_SES_larger_volume: bool | None = None
    page_number: str | None = None
    verbatim_quote: str | None = None
    # per-field provenance the model supplied: {field: {"page":..,"quote":..}}
    provenance: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("provenance", None)
        if self.covariates is not None:
            d["covariates"] = "; ".join(str(c) for c in self.covariates)
        return d


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _enum(field_name: str, v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in ENUMS[field_name] else None


def _prov_ok(prov: dict, field_name: str, page: Any, quote: Any) -> bool:
    """A numeric field is sourced iff it has both a locator and a quote."""
    p = prov.get(field_name, {}) if isinstance(prov, dict) else {}
    loc = p.get("page") or p.get("locator") or page
    q = p.get("quote") or quote
    return bool(loc) and bool(q)


def parse_effect(obj: dict, *, study_id: str) -> Effect:
    if not isinstance(obj, dict):
        raise ExtractionError(f"effect is not an object: {obj!r}")
    roi = _enum("roi", obj.get("roi"))
    if roi is None:
        raise ExtractionError(f"effect has no valid roi: {obj.get('roi')!r}")

    prov = obj.get("provenance") or {}
    page = obj.get("page_number")
    quote = obj.get("verbatim_quote")

    eff = Effect(
        study_id=study_id,
        roi=roi,
        extraction_confidence=max(0.0, min(1.0, _num(obj.get("extraction_confidence")) or 0.0)),
        cohort_name=(str(obj["cohort_name"]).strip() if obj.get("cohort_name") else None),
        sample_overlap_group=None,   # assigned later by cohorts.assign_overlap_group
        n=_num(obj.get("n")),
        mean_age=_num(obj.get("mean_age")),
        age_range=(str(obj["age_range"]) if obj.get("age_range") else None),
        pct_female=_num(obj.get("pct_female")),
        sample_type=_enum("sample_type", obj.get("sample_type")),
        ses_construct=_enum("ses_construct", obj.get("ses_construct")),
        ses_timing=_enum("ses_timing", obj.get("ses_timing")),
        hemisphere=_enum("hemisphere", obj.get("hemisphere")),
        volume_pipeline=(str(obj["volume_pipeline"]) if obj.get("volume_pipeline") else None),
        icv_adjustment=_enum("icv_adjustment", obj.get("icv_adjustment")),
        covariates=(list(obj["covariates"]) if isinstance(obj.get("covariates"), list) else None),
        effect_type=_enum("effect_type", obj.get("effect_type")),
        effect_value=_num(obj.get("effect_value")),
        se_or_ci=(str(obj["se_or_ci"]) if obj.get("se_or_ci") else None),
        p_value=_num(obj.get("p_value")),
        direction_coded_positive_means_higher_SES_larger_volume=(
            bool(obj["direction_coded_positive_means_higher_SES_larger_volume"])
            if obj.get("direction_coded_positive_means_higher_SES_larger_volume") is not None
            else None),
        page_number=(str(page) if page else None),
        verbatim_quote=(str(quote)[:400] if quote else None),
        provenance=prov if isinstance(prov, dict) else {},
    )
    _enforce_provenance(eff)
    return eff


def _enforce_provenance(eff: Effect) -> None:
    """Null out any numeric field lacking a locator + quote; then re-floor confidence."""
    for f in PROVENANCE_FIELDS:
        val = getattr(eff, f)
        if val is None:
            continue
        if not _prov_ok(eff.provenance, f, eff.page_number, eff.verbatim_quote):
            setattr(eff, f, None)
    # the effect is only as trustworthy as its headline number
    if eff.effect_value is None:
        eff.extraction_confidence = 0.0
