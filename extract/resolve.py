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

CONVERTER = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"

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
                   chunk: int = 200) -> dict[str, str]:
    """Return {study_id: pmcid} for studies the converter recognizes."""
    records = list(records)
    # prefer PMID (numeric, unambiguous); fall back to DOI
    id_to_study: dict[str, str] = {}
    send: list[str] = []
    for r in records:
        sid = r["id"]
        pmid = r.get("pmid")
        doi = _norm_doi(r.get("doi"))
        if pmid:
            id_to_study[str(pmid)] = sid
            send.append(str(pmid))
        elif doi:
            id_to_study[doi] = sid
            send.append(doi)

    out: dict[str, str] = {}
    for i in range(0, len(send), chunk):
        batch = send[i:i + chunk]
        data = fetch(batch)
        if not data:
            continue
        for rec in data.get("records", []):
            pmcid = rec.get("pmcid")
            if not pmcid:
                continue
            # match the returned record back to a study via pmid or doi
            key = str(rec.get("pmid") or "") or _norm_doi(rec.get("doi")) or ""
            sid = id_to_study.get(key)
            if sid is None and rec.get("doi"):
                sid = id_to_study.get(_norm_doi(rec["doi"]))
            if sid:
                out[sid] = pmcid
    return out


def live_resolver(tool: str = "ses-meta", email: str = "meta-analysis@example.org") -> ConvFetch:
    import json
    import urllib.parse
    import urllib.request

    def fetch(ids: list[str]) -> Optional[dict]:
        params = urllib.parse.urlencode(
            {"ids": ",".join(ids), "format": "json", "tool": tool, "email": email})
        url = f"{CONVERTER}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            return None

    return fetch
