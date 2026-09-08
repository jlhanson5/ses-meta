"""Full-text retrieval for included studies.

For each included study, try in order:
  1. Europe PMC open-access full-text XML (by PMID/PMCID)
  2. publisher PDF via an Unpaywall-resolved OA location (by DOI)
  3. a manually dropped PDF at data/pdfs/manual/<study_id>.pdf

The first source that yields text wins. Every study gets a retrieval status
row; nothing fails silently. Studies that yield nothing land in an
unretrievable report, not a dropped record.

Network access is injected (fetch_xml, fetch_unpaywall, fetch_pdf_bytes) so this
is testable offline. The live implementations use the shared search.http layer
and Unpaywall/Europe PMC endpoints; in this sandbox those domains are blocked,
so live retrieval runs on the researcher's machine.

Nothing here ever deletes a PDF.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .document import Document, from_jats, from_pdf

MANUAL_DIR = Path("data/pdfs/manual")

EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UNPAYWALL = "https://api.unpaywall.org/v2"

# injectable network seams
FetchXml = Callable[[str], Optional[str]]              # pmcid -> JATS xml
FetchUnpaywall = Callable[[str], Optional[str]]        # doi -> pdf url
FetchPdfBytes = Callable[[str], Optional[bytes]]       # url -> pdf bytes


@dataclass
class Retrieval:
    study_id: str
    status: str            # "europepmc_xml" | "unpaywall_pdf" | "manual_pdf" | "unretrieved"
    detail: str            # where it came from, or why it failed
    document: Optional[Document] = None

    @property
    def ok(self) -> bool:
        return self.document is not None and bool(self.document.segments)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def retrieve_one(record: dict, *, fetch_xml: FetchXml, fetch_unpaywall: FetchUnpaywall,
                 fetch_pdf_bytes: FetchPdfBytes, manual_dir: Path = MANUAL_DIR,
                 cache_dir: Path = Path("data/pdfs/cache"),
                 pdf_to_doc: Callable[[Path, str, str], Document] = from_pdf) -> Retrieval:
    """record is a dict with id, doi, pmid (and optionally pmcid/raw_json)."""
    sid = record["id"]

    # 1. Europe PMC OA XML
    pmcid = record.get("pmcid") or _pmcid_from_raw(record)
    if pmcid:
        xml = fetch_xml(pmcid)
        if xml:
            doc = from_jats(xml, study_id=sid)
            if doc.segments:
                return Retrieval(sid, "europepmc_xml", f"pmcid {pmcid}", doc)

    # 2. Unpaywall -> publisher OA PDF
    doi = record.get("doi")
    if doi:
        pdf_url = fetch_unpaywall(doi)
        if pdf_url:
            data = fetch_pdf_bytes(pdf_url)
            if data and _looks_like_pdf(data):
                path = _write_cache(sid, data, cache_dir)
                doc = _safe_pdf_to_doc(pdf_to_doc, path, sid, "unpaywall_pdf")
                if doc and doc.segments:
                    return Retrieval(sid, "unpaywall_pdf", pdf_url, doc)

    # 3. manual drop
    manual = manual_dir / f"{_slug(sid)}.pdf"
    if manual.exists():
        doc = _safe_pdf_to_doc(pdf_to_doc, manual, sid, "manual_pdf")
        if doc and doc.segments:
            return Retrieval(sid, "manual_pdf", str(manual), doc)

    return Retrieval(sid, "unretrieved",
                     "no OA XML, no Unpaywall PDF, no manual drop", None)


def _pmcid_from_raw(record: dict) -> Optional[str]:
    raw = record.get("raw_json")
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(d, dict):
        return d.get("pmcid") or (d.get("ids", {}) or {}).get("pmcid")
    return None


def _slug(study_id: str) -> str:
    """Filesystem-safe stem for a study id (ids look like 'doi:10.1/abc')."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", study_id)


def _looks_like_pdf(data: bytes) -> bool:
    """A real PDF starts with %PDF. Publishers often serve an HTML landing page
    at a 'pdf' URL; those must not be saved and parsed as PDFs."""
    return data[:5].startswith(b"%PDF")


def _safe_pdf_to_doc(pdf_to_doc, path, sid, source):
    """Parse a PDF, but treat any parser failure as a miss (return None) rather
    than letting one corrupt download crash a whole-corpus run."""
    try:
        return pdf_to_doc(path, sid, source)
    except Exception:
        return None


def _write_cache(study_id: str, data: bytes, cache_dir: Path) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_slug(study_id)}.pdf"
    path.write_bytes(data)
    return path


def unretrievable_report(retrievals: list[Retrieval]) -> list[dict]:
    return [{"study_id": r.study_id, "detail": r.detail}
            for r in retrievals if not r.ok]


# --------------------------------------------------------------------------
# live network seams (used on the researcher's machine; blocked in sandbox)
# --------------------------------------------------------------------------

def live_fetch_xml(email: str) -> FetchXml:
    from search.http import RateLimiter, get_json
    limiter = RateLimiter(0.2)

    def fetch(pmcid: str) -> Optional[str]:
        url = f"{EPMC_FULLTEXT}/{pmcid}/fullTextXML"
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            return None

    return fetch


def live_fetch_unpaywall(email: str) -> FetchUnpaywall:
    from search.http import get_json

    def fetch(doi: str) -> Optional[str]:
        try:
            data = get_json(f"{UNPAYWALL}/{doi}", params={"email": email})
        except Exception:
            return None
        if not data:
            return None
        # best_oa_location first, then any oa_location that exposes a PDF url
        best = data.get("best_oa_location") or {}
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]
        for loc in data.get("oa_locations", []) or []:
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]
        return None

    return fetch


def live_fetch_pdf_bytes() -> FetchPdfBytes:
    def fetch(url: str) -> Optional[bytes]:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except Exception:
            return None

    return fetch
