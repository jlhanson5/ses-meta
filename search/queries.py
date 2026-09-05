"""Load queries.yaml and expand it into the canonical query set.

The canonical set is the cross product brain x ses x method. Each element is a
`Query` (three terms). `format_for(source, query)` renders a Query into the
target source's dialect. Nothing hardcodes a full query string; the blocks in
queries.yaml are the only place terms live.
"""
from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

DEFAULT_QUERIES = Path(__file__).with_name("queries.yaml")

# Sources that support boolean AND + phrase quoting + wildcards.
_BOOLEAN_SOURCES = {"pubmed", "europepmc"}


@dataclass(frozen=True)
class Query:
    brain: str
    ses: str
    method: str = ""

    @property
    def terms(self) -> tuple[str, ...]:
        # drop an empty method so a spec with no method block yields a
        # two-term (region AND ses) query
        return tuple(t for t in (self.brain, self.ses, self.method) if t)

    @property
    def id(self) -> str:
        raw = "|".join(self.terms)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def load_spec(path: Path = DEFAULT_QUERIES) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    for block in ("brain", "ses"):
        if not spec.get(block):
            raise ValueError(f"queries.yaml missing non-empty '{block}' block")
    return spec


def build_queries(spec: dict) -> list[Query]:
    """Cross product of the blocks, deterministically ordered.

    method is optional: with a method block the set is brain x ses x method (as
    before); without one it is brain x ses, and each query carries only the
    region and SES terms.
    """
    methods = spec.get("method") or [""]
    combos = itertools.product(spec["brain"], spec["ses"], methods)
    return [Query(b, s, m or "") for b, s, m in combos]


def query_set_hash(queries: Iterable[Query]) -> str:
    """Stable hash of the whole query set, for the runs table."""
    joined = "\n".join(sorted(q.id for q in queries))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Per-source formatting
# ---------------------------------------------------------------------------

def _render_term_boolean(term: str) -> str:
    """Quote phrases; leave wildcard terms unquoted (quotes disable truncation)."""
    if term.endswith("*"):
        return term                      # e.g. hippocamp*
    return f'"{term}"'


def _render_term_keyword(term: str) -> str:
    """Relevance engines: strip trailing wildcard, drop quotes."""
    return term[:-1] if term.endswith("*") else term


def format_for(source: str, query: Query) -> str:
    """Render a Query into `source`'s search-string dialect."""
    if source == "pubmed":
        parts = [f"{_render_term_boolean(t)}[tiab]" for t in query.terms]
        return " AND ".join(parts)
    if source == "europepmc":
        parts = [_render_term_boolean(t) for t in query.terms]
        return " AND ".join(parts)
    if source in ("openalex", "semanticscholar"):
        # relevance keyword search: space-joined phrases, wildcard stripped
        return " ".join(_render_term_keyword(t) for t in query.terms)
    raise ValueError(f"unknown source dialect: {source}")
