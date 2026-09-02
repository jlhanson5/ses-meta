"""Shared record model and field-normalization helpers.

Every source module returns a list of `Record`. Normalization here is the single
source of truth for how DOIs, titles, and author names are compared during dedup
and how the stable record id is derived. Same input, same id, always.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Field normalization
# ---------------------------------------------------------------------------

_DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)
_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Lowercase, strip resolver prefixes and surrounding whitespace.

    Returns None for empty/placeholder values so downstream code can treat
    "no DOI" uniformly.
    """
    if not doi:
        return None
    d = doi.strip()
    d = _DOI_PREFIX.sub("", d)
    d = d.strip().lower()
    return d or None


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_title(title: Optional[str]) -> str:
    """Fold to a comparison key: accents removed, lowercased, alnum-only, single-spaced."""
    if not title:
        return ""
    t = _strip_accents(title)
    t = t.lower()
    t = _NON_ALNUM.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


def first_author_last(authors: Optional[str]) -> str:
    """Extract a normalized last name from the first author.

    `authors` is stored as a semicolon-joined string ("Smith J; Doe A"). We take
    the token before the first semicolon and the last whitespace-delimited word
    that is not a lone initial. Best-effort: author strings are messy across
    sources, so this only needs to be stable, not perfect.
    """
    if not authors:
        return ""
    first = authors.split(";")[0].strip()
    if not first:
        return ""
    # "Smith J" or "Smith, John" or "John Smith"
    if "," in first:
        last = first.split(",")[0]
    else:
        parts = [p for p in first.split() if len(p.rstrip(".")) > 1]
        last = parts[-1] if parts else first
    last = _strip_accents(last).lower()
    last = _NON_ALNUM.sub("", last)
    return last


def compute_id(doi: Optional[str], title: Optional[str], authors: Optional[str],
               year: Optional[int]) -> str:
    """Deterministic primary key.

    DOI when present (globally unique); otherwise a hash of
    normalized_title | first_author_last | year. This id is what makes DB inserts
    idempotent: the same paper always hashes to the same row.
    """
    nd = normalize_doi(doi)
    if nd:
        return f"doi:{nd}"
    key = f"{normalize_title(title)}|{first_author_last(authors)}|{year or ''}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"k:{h}"


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

@dataclass
class Record:
    doi: Optional[str] = None
    pmid: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: Optional[str] = None          # "Smith J; Doe A"
    year: Optional[int] = None
    journal: Optional[str] = None
    source: Optional[str] = None           # single source tag as fetched
    sources: list[str] = field(default_factory=list)  # all sources after merge
    raw_json: Optional[str] = None         # original API item, JSON-encoded

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        if self.source and self.source not in self.sources:
            self.sources.append(self.source)

    @property
    def id(self) -> str:
        return compute_id(self.doi, self.title, self.authors, self.year)

    def to_row(self, first_seen_run: str) -> dict:
        return {
            "id": self.id,
            "doi": self.doi,
            "pmid": self.pmid,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "source": ",".join(self.sources) if self.sources else self.source,
            "first_seen_run": first_seen_run,
            "raw_json": self.raw_json,
        }

    def as_dict(self) -> dict:
        return asdict(self)
