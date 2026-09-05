"""OpenAlex /works search.

Full-text-ish search via `search=`, date window via
from_publication_date/to_publication_date filters. Abstracts come back as an
inverted index and must be reconstructed. Uses the polite pool (mailto). Cursor
pagination.
"""
from __future__ import annotations

import json
from typing import Optional

from .base import Source
from ..http import RateLimiter, cached_fetch, get_json, query_hash
from ..model import Record

ENDPOINT = "https://api.openalex.org/works"
PER_PAGE = 100
MAX_PAGES = 10


def reconstruct_abstract(inv: Optional[dict]) -> Optional[str]:
    """Rebuild abstract text from OpenAlex inverted index {word: [positions]}."""
    if not inv:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


class OpenAlex(Source):
    name = "openalex"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.limiter = RateLimiter(0.11)

    def run(self, query: str, date_from: str, date_to: str) -> list[Record]:
        qhash = query_hash(f"{query}|{date_from}|{date_to}")
        payload = cached_fetch(
            self.raw_dir, self.run_date, self.name, qhash,
            lambda: self._fetch(query, date_from, date_to),
        )
        return self._parse(payload)

    def _fetch(self, query: str, date_from: str, date_to: str) -> dict:
        results = []
        cursor = "*"
        for _ in range(MAX_PAGES):
            # title_and_abstract.search scopes matching to title + abstract only
            # (the plain `search` param also matches full text, which floods the
            # results with papers that merely mention a term in the body).
            filt = (
                f"title_and_abstract.search:{query},"
                f"from_publication_date:{date_from},"
                f"to_publication_date:{date_to}"
            )
            params = {
                "filter": filt,
                "per-page": PER_PAGE,
                "cursor": cursor,
                "mailto": self.mailto,
            }
            data = get_json(ENDPOINT, params=params, limiter=self.limiter)
            hits = data.get("results", [])
            results.extend(hits)
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor or not hits:
                break
        return {"results": results}

    def _parse(self, payload: dict) -> list[Record]:
        out: list[Record] = []
        for w in payload.get("results", []):
            doi = w.get("doi")  # "https://doi.org/10.x" -> normalized in Record
            pmid = None
            ids = w.get("ids", {}) or {}
            if ids.get("pmid"):
                pmid = str(ids["pmid"]).rsplit("/", 1)[-1]
            authors = "; ".join(
                a.get("author", {}).get("display_name", "")
                for a in w.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ) or None
            venue = (w.get("primary_location") or {}).get("source") or {}
            out.append(Record(
                doi=doi,
                pmid=pmid,
                title=w.get("title"),
                abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
                authors=authors,
                year=self._year(w.get("publication_year")),
                journal=venue.get("display_name"),
                source=self.name,
                raw_json=json.dumps({"id": w.get("id")}, ensure_ascii=False),
            ))
        return out
