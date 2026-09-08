"""Extraction: one study's full text -> validated Effect rows.

Feeds the locator-tagged full text to the model through the shared llm contract,
parses the returned effects, enforces the provenance rule in code (schema.py),
and assigns sample_overlap_group from the cohort registry. The model never
converts or standardizes anything; values pass through as reported.

A parse failure is not a silent drop: it returns zero effects plus an error note
the caller records, and the study surfaces as yielding nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from llm.service import LLMClient, LLMError, JSONError, complete_json

from . import cohorts
from .document import Document
from .prompts import Prompt
from .schema import Effect, ExtractionError, parse_effect


@dataclass
class ExtractResult:
    study_id: str
    effects: list[Effect]
    error: str | None = None


def extract_study(client: LLMClient, prompt: Prompt, doc: Document, *,
                  model: str | None = None) -> ExtractResult:
    rendered = prompt.render(fulltext=doc.render())
    try:
        obj = complete_json(client, rendered, model=model)
    except (LLMError, JSONError) as exc:
        return ExtractResult(doc.study_id, [], error=f"model/parse error: {exc}")

    raw_effects = obj.get("effects")
    if not isinstance(raw_effects, list):
        return ExtractResult(doc.study_id, [], error="reply had no 'effects' list")

    full_text = doc.render()
    out: list[Effect] = []
    for raw in raw_effects:
        try:
            eff = parse_effect(raw, study_id=doc.study_id)
        except ExtractionError:
            continue                       # malformed single effect: skip, not guess
        eff.sample_overlap_group = cohorts.assign_overlap_group(
            eff.cohort_name, text=full_text)
        out.append(eff)
    return ExtractResult(doc.study_id, out)


def unrecognized_cohorts(result: ExtractResult) -> list[str]:
    """Cohort names present but not matched to a known overlap group."""
    flagged = []
    for e in result.effects:
        if e.cohort_name and e.sample_overlap_group is None:
            flagged.append(e.cohort_name)
    return sorted(set(flagged))
