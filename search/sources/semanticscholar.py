"""Semantic Scholar Graph API paper search.

The bulk/search endpoint filters by year only, not full date, so we derive a
year range from the date window and post-filter is not possible on exact date.
This limitation is documented and surfaced in the run log. Rate limit is harsh
without a key (shared pool); with S2_API_KEY, ~1 req/s. We stay at 1 req/s
either way to avoid 429 storms.
"""
from __future__ import annotations

import json

from .base import Source
from ..http import RateLimiter, cached_fetch, get_json, query_hash
from ..model import Record

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,venue,externalIds,authors"
LIMIT = 100
MAX_PAGES = 10


class SemanticScholar(Source):
    name = "semanticscholar"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.limiter = RateLimiter(1.05)

    def run(self, query: str, date_from: str, date_to: str) -> list[Record]:
        qhash = query_hash(f"{query}|{date_from}|{date_to}")
        payload = cached_fetch(
            self.raw_dir, self.run_date, self.name, qhash,
            lambda: self._fetch(query, date_from, date_to),
        )
        return self._parse(payload)

    def _fetch(self, query: str, date_from: str, date_to: str) -> dict:
        year_range = f"{date_from[:4]}-{date_to[:4]}"
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        results = []
        offset = 0
        for _ in range(MAX_PAGES):
            params = {
                "query": query,
                "year": year_range,
                "fields": FIELDS,
                "limit": LIMIT,
                "offset": offset,
            }
            data = get_json(ENDPOINT, params=params, headers=headers, limiter=self.limiter)
            hits = data.get("data", []) or []
            results.extend(hits)
            nxt = data.get("next")
            if nxt is None or not hits:
                break
            offset = nxt
        return {"results": results, "year_range": year_range}

    def _parse(self, payload: dict) -> list[Record]:
        out: list[Record] = []
        for p in payload.get("results", []):
            ext = p.get("externalIds", {}) or {}
            authors = "; ".join(a.get("name", "") for a in p.get("authors", [])
                                if a.get("name")) or None
            out.append(Record(
                doi=ext.get("DOI"),
                pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
                title=p.get("title"),
                abstract=p.get("abstract"),
                authors=authors,
                year=self._year(p.get("year")),
                journal=p.get("venue"),
                source=self.name,
                raw_json=json.dumps({"paperId": p.get("paperId")}, ensure_ascii=False),
            ))
        return out
