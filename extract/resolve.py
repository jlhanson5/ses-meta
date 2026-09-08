"""Resolve PMCIDs for included studies.

Europe PMC full-text XML is keyed by PMCID, but the search layer stored only
PMIDs and DOIs, so tier-1 retrieval was being skipped for every study. This
resolves PMID/DOI -> PMCID via the NCBI ID Converter (up to 200 ids per call),
so studies with an author manuscript or OA copy in PMC become retrievable as
clean XML rather than scraped PDF.

The converter only returns IDs for articles that are in PMC, so a study with no
PMCID simply falls through to the PDF tiers. Network access is injected for
testing; the live resolver uses the converter endpoint.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

CONVERTER = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"

# a fetch takes a list of ids and returns the parsed converter JSON (or None)
ConvFetch = Callable[[list[str]], Optional[dict]]


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for pre in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(pre):
            d = d[len(pre):]
    return d or None


def resolve_pmcids(records: Iterable[dict], fetch: ConvFetch,
                   chunk: int = 50) -> dict[str, str]:
    """Return {study_id: pmcid} for studies the converter recognizes.

    The NCBI ID Converter wants a single id TYPE per request and a bounded URL,
    so PMIDs and DOIs are sent in separate, small, chunked requests. Mixing
    types or sending 100+ long DOIs in one request returns nothing, which is why
    a full-corpus batch silently resolved zero PMCIDs.
    """
    records = list(records)
    id_to_study: dict[str, str] = {}
    pmids: list[str] = []
    dois: list[str] = []
    for r in records:
        sid = r["id"]
        pmid = r.get("pmid")
        doi = _norm_doi(r.get("doi"))
        if pmid:
            id_to_study[str(pmid)] = sid
            pmids.append(str(pmid))
        elif doi:
            id_to_study[doi] = sid
            dois.append(doi)

    out: dict[str, str] = {}

    def ingest(data: Optional[dict]) -> int:
        if not data:
            return 0
        n = 0
        for rec in data.get("records", []):
            pmcid = rec.get("pmcid")
            if not pmcid:
                continue
            key = str(rec.get("pmid") or "") or _norm_doi(rec.get("doi")) or ""
            sid = id_to_study.get(key)
            if sid is None and rec.get("doi"):
                sid = id_to_study.get(_norm_doi(rec["doi"]))
            if sid:
                out[sid] = pmcid
                n += 1
        return n

    for stream in (pmids, dois):
        for i in range(0, len(stream), chunk):
            batch = stream[i:i + chunk]
            if ingest(fetch(batch)) == 0 and len(batch) > 1:
                # a batch that resolves nothing falls back to per-id calls, the
                # single-id path that is known to work, so a rejected batch or
                # one bad id never zeroes the whole resolve.
                for one in batch:
                    ingest(fetch([one]))
    return out


def build_converter_url(ids: list[str], tool: str, email: str) -> str:
    """Converter URL with LITERAL commas in ids.

    requests percent-encodes commas by default ('111,222' -> '111%2C222'), and
    the converter does not decode them, so a multi-id batch resolves nothing
    while a single id works. Keep commas literal.
    """
    import urllib.parse
    q = urllib.parse.urlencode(
        {"ids": ",".join(ids), "format": "json", "tool": tool, "email": email},
        safe=",")
    return f"{CONVERTER}?{q}"


def live_resolver(tool: str = "ses-meta", email: str = "meta-analysis@example.org") -> ConvFetch:
    import json
    import urllib.request

    from search.http import RateLimiter
    limiter = RateLimiter(0.34)          # ~3 req/s, polite for NCBI
    ua = f"{tool}/1.0 (mailto:{email})"

    def fetch(ids: list[str]) -> Optional[dict]:
        # NCBI's PMC id-converter 403s the requests client regardless of headers
        # (it fingerprints the client), but serves urllib fine, so this endpoint
        # is called with urllib directly rather than through the requests-based
        # get_json. Rate-limited so a bulk resolve stays polite.
        url = build_converter_url(ids, tool, email)
        limiter.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            return None

    return fetch
