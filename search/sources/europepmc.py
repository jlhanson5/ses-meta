"""Europe PMC REST search.

Single JSON endpoint. Date window applied via the FIRST_PDATE range operator
appended to the query. Pagination via cursorMark until nextCursorMark stops
changing. Europe PMC is generous on rate but we stay polite.
"""
from __future__ import annotations

import json

from .base import Source
from ..http import RateLimiter, cached_fetch, get_json, query_hash
from ..model import Record

ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PAGE_SIZE = 100
MAX_PAGES = 10


class EuropePMC(Source):
    name = "europepmc"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.limiter = RateLimiter(0.2)

    def run(self, query: str, date_from: str, date_to: str) -> list[Record]:
        qhash = query_hash(f"{query}|{date_from}|{date_to}")
        payload = cached_fetch(
            self.raw_dir, self.run_date, self.name, qhash,
            lambda: self._fetch(query, date_from, date_to),
        )
        return self._parse(payload)

    def _fetch(self, query: str, date_from: str, date_to: str) -> dict:
        dated = f"({query}) AND (FIRST_PDATE:[{date_from} TO {date_to}])"
        results = []
        cursor = "*"
        for _ in range(MAX_PAGES):
            params = {
                "query": dated,
                "format": "json",
                "pageSize": PAGE_SIZE,
                "cursorMark": cursor,
                "resultType": "core",
                # Europe PMC expands queries with MeSH synonyms by default, which
                # widens matches well beyond the terms we asked for. Turn it off.
                "synonym": "false",
            }
            data = get_json(ENDPOINT, params=params, limiter=self.limiter)
            hits = data.get("resultList", {}).get("result", [])
            results.extend(hits)
            nxt = data.get("nextCursorMark")
            if not nxt or nxt == cursor or not hits:
                break
            cursor = nxt
        return {"results": results}

    def _parse(self, payload: dict) -> list[Record]:
        out: list[Record] = []
        for item in payload.get("results", []):
            authors = None
            alist = item.get("authorList", {}).get("author", [])
            if alist:
                names = []
                for a in alist:
                    fn = a.get("fullName")
                    if fn:
                        names.append(fn)
                    elif a.get("lastName"):
                        names.append(f"{a['lastName']} {a.get('initials', '')}".strip())
                authors = "; ".join(names) or None
            out.append(Record(
                doi=item.get("doi"),
                pmid=item.get("pmid"),
                title=item.get("title"),
                abstract=item.get("abstractText"),
                authors=authors,
                year=self._year(item.get("pubYear") or item.get("firstPublicationDate")),
                journal=(item.get("journalInfo", {}) or {}).get("journal", {}).get("title"),
                source=self.name,
                raw_json=json.dumps({"id": item.get("id"), "src": item.get("source")},
                                    ensure_ascii=False),
            ))
        return out
