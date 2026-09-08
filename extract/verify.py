"""Second-pass verification.

A separate model call re-reads ONLY the quoted spans the extraction pass
supplied and confirms or disputes each number. It never sees the full text, so
it cannot re-extract; it can only check whether each quote supports its value.

A row is routed to human review when any of its claims is disputed OR the row's
extraction_confidence is below 0.9. The verdict is written back to the effect.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from llm.service import LLMClient, LLMError, JSONError, complete_json

from .prompts import Prompt
from .schema import Effect, PROVENANCE_FIELDS

CONFIDENCE_FLOOR = 0.9


@dataclass
class Verdict:
    confirmed: bool
    needs_review: bool
    reason: str | None


def _claims_for(eff: Effect) -> list[dict]:
    claims = []
    for f in PROVENANCE_FIELDS:
        val = getattr(eff, f)
        if val is None:
            continue
        prov = eff.provenance.get(f, {}) if isinstance(eff.provenance, dict) else {}
        quote = prov.get("quote") or eff.verbatim_quote or ""
        locator = prov.get("page") or prov.get("locator") or eff.page_number or ""
        claims.append({"field": f, "value": val, "locator": locator, "quote": quote})
    return claims


def verify_effect(client: LLMClient, prompt: Prompt, eff: Effect, *,
                  model: str | None = None) -> Verdict:
    claims = _claims_for(eff)
    if not claims:
        # nothing numeric with provenance to check; low-confidence still reviews
        if eff.extraction_confidence < CONFIDENCE_FLOOR:
            return Verdict(False, True, "low_confidence_no_claims")
        return Verdict(True, False, None)

    indexed = [{"index": i, **c} for i, c in enumerate(claims)]
    rendered = prompt.render(claims=json.dumps(indexed, ensure_ascii=False))
    try:
        obj = complete_json(client, rendered, model=model)
        verdicts = obj.get("verdicts", [])
    except (LLMError, JSONError) as exc:
        return Verdict(False, True, f"verify_error: {str(exc)[:60]}")

    disputed = [v for v in verdicts if str(v.get("verdict", "")).lower() == "dispute"]
    if disputed:
        fields = ", ".join(claims[v["index"]]["field"]
                           for v in disputed if isinstance(v.get("index"), int)
                           and v["index"] < len(claims))
        return Verdict(False, True, f"disputed: {fields}")

    if eff.extraction_confidence < CONFIDENCE_FLOOR:
        return Verdict(True, True, "low_confidence")

    return Verdict(True, False, None)
