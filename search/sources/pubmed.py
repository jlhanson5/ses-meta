"""PubMed via NCBI E-utilities.

Two-step: esearch returns PMIDs for the query + date window, efetch returns
full article XML which we parse for DOI, title, abstract, authors, year,
journal. Rate limit: 3 req/s without a key, ~10 req/s with NCBI_API_KEY. We stay
conservative.

Raw cache stores {"esearch": {...}, "efetch_xml": "..."} as one payload per query.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Optional

from .base import Source
from ..http import RateLimiter, cached_fetch, get_json, get_text, query_hash
from ..model import Record

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RETMAX = 200


class PubMed(Source):
    name = "pubmed"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # 3/s no key, 10/s with key. Add margin.
        self.limiter = RateLimiter(0.11 if self.api_key else 0.34)

    def run(self, query: str, date_from: str, date_to: str) -> list[Record]:
        qhash = query_hash(f"{query}|{date_from}|{date_to}")
        payload = cached_fetch(
            self.raw_dir, self.run_date, self.name, qhash,
            lambda: self._fetch(query, date_from, date_to),
        )
        return self._parse(payload)

    # -- network --------------------------------------------------------------
    def _fetch(self, query: str, date_from: str, date_to: str) -> dict:
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": RETMAX,
            "retmode": "json",
            "datetype": "pdat",
            "mindate": date_from.replace("-", "/"),
            "maxdate": date_to.replace("-", "/"),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        esearch = get_json(ESEARCH, params=params, limiter=self.limiter)
        idlist = esearch.get("esearchresult", {}).get("idlist", [])
        efetch_xml = ""
        if idlist:
            fparams = {"db": "pubmed", "id": ",".join(idlist), "retmode": "xml"}
            if self.api_key:
                fparams["api_key"] = self.api_key
            efetch_xml = get_text(EFETCH, params=fparams, limiter=self.limiter)
        return {"esearch": esearch, "efetch_xml": efetch_xml}

    # -- parse ----------------------------------------------------------------
    def _parse(self, payload: dict) -> list[Record]:
        xml = payload.get("efetch_xml") or ""
        if not xml.strip():
            return []
        root = ET.fromstring(xml)
        records: list[Record] = []
        for art in root.findall(".//PubmedArticle"):
            records.append(self._parse_article(art))
        return records

    def _parse_article(self, art: ET.Element) -> Record:
        pmid = art.findtext(".//PMID")
        title = art.findtext(".//ArticleTitle")
        journal = art.findtext(".//Journal/Title")
        year = self._year(art.findtext(".//JournalIssue/PubDate/Year")
                          or art.findtext(".//JournalIssue/PubDate/MedlineDate"))
        # abstract may be split into labeled sections
        abstract_parts = [e.text or "" for e in art.findall(".//Abstract/AbstractText")]
        abstract = " ".join(p.strip() for p in abstract_parts if p).strip() or None
        # authors
        authors = []
        for a in art.findall(".//AuthorList/Author"):
            last = a.findtext("LastName")
            initials = a.findtext("Initials")
            if last:
                authors.append(f"{last} {initials}".strip() if initials else last)
        authors_str = "; ".join(authors) or None
        # DOI lives in ELocationID or ArticleIdList
        doi: Optional[str] = None
        for el in art.findall(".//ELocationID"):
            if el.get("EIdType") == "doi":
                doi = el.text
                break
        if not doi:
            for aid in art.findall(".//ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = aid.text
                    break
        return Record(
            doi=doi, pmid=pmid, title=title, abstract=abstract,
            authors=authors_str, year=year, journal=journal, source=self.name,
            raw_json=json.dumps({"pmid": pmid, "title": title}, ensure_ascii=False),
        )
