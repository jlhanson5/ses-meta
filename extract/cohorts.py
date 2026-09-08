"""Known shared-cohort registry for sample_overlap_group.

Many included studies draw on the same public cohorts, so their effects are not
independent. The modeling step (step 4) needs to cluster on shared samples. Here
we assign a canonical sample_overlap_group from a registry of known cohorts,
matching on name and common aliases. A study whose cohort name matches nothing
in the registry is NOT guessed: it is flagged for a human to assign.
"""
from __future__ import annotations

import re

# canonical group -> alias patterns (matched case-insensitively as whole words)
REGISTRY: dict[str, list[str]] = {
    "ABCD": ["abcd", "adolescent brain cognitive development"],
    "HCP-D": ["hcp-d", "hcp development", "human connectome project development",
              "lifespan human connectome"],
    "HBN": ["hbn", "healthy brain network"],
    "NCANDA": ["ncanda", "national consortium on alcohol and neurodevelopment"],
    "PING": ["ping", "pediatric imaging neurocognition and genetics"],
    "UK Biobank": ["uk biobank", "ukbiobank", "ukb"],
    "Generation R": ["generation r", "gen r"],
    "ALSPAC": ["alspac", "avon longitudinal study"],
    "Dunedin": ["dunedin", "dunedin multidisciplinary"],
    "KHANDLE": ["khandle", "kaiser healthy aging and diverse life experiences"],
    "STAR": ["study of healthy aging in african americans", "star study"],
}


def _compile(aliases: list[str]) -> list[re.Pattern]:
    return [re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE) for a in aliases]


_COMPILED = {group: _compile(aliases) for group, aliases in REGISTRY.items()}


def assign_overlap_group(cohort_name: str | None, *, text: str | None = None) -> str | None:
    """Return the canonical group if recognized, else None (flag for human).

    Checks the reported cohort_name first, then, if given, the study text (a
    paper may name its cohort only in the methods).
    """
    haystacks = [h for h in (cohort_name, text) if h]
    for group, patterns in _COMPILED.items():
        for pat in patterns:
            if any(pat.search(h) for h in haystacks):
                return group
    return None


def is_known(group: str) -> bool:
    return group in REGISTRY


def all_groups() -> list[str]:
    return sorted(REGISTRY)
