"""Full-text as locatable segments.

Extraction needs provenance: every number ties back to a page (for PDFs) or a
section/table locator (for XML with no pages). So full text is represented not
as one blob but as an ordered list of Segments, each with a locator label and
its text. The extraction prompt is fed the segments with their locators, so the
model can cite where a value came from and the verifier can re-read that span.

Parsers:
  from_pdf(path)  -> one segment per page, locator "p.<n>"
  from_jats(xml)  -> one segment per section/table, locator "<section title>"

Both are best-effort and dependency-light. PDF parsing uses pypdf if present;
if it is not installed the caller gets a clear error rather than a silent empty
document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    locator: str        # "p.4" or "Results" or "Table 2"
    text: str


@dataclass
class Document:
    study_id: str
    source: str         # "europepmc_xml" | "unpaywall_pdf" | "manual_pdf"
    segments: list[Segment]

    def render(self, max_chars_per_segment: int = 8000) -> str:
        """Flatten to a single locator-tagged string for the model."""
        parts = []
        for s in self.segments:
            body = s.text.strip()
            if len(body) > max_chars_per_segment:
                body = body[:max_chars_per_segment] + " [truncated]"
            parts.append(f"[[{s.locator}]]\n{body}")
        return "\n\n".join(parts)

    def locators(self) -> list[str]:
        return [s.locator for s in self.segments]


def from_tagged(text: str, study_id: str, source: str = "tagged") -> Document:
    """Parse locator-tagged text ("[[loc]]\\nbody" blocks) back into a Document."""
    segments: list[Segment] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block.startswith("[["):
            continue
        head, _, body = block.partition("]]")
        loc = head[2:].strip()
        segments.append(Segment(locator=loc or "section", text=body.strip()))
    return Document(study_id=study_id, source=source, segments=segments)


def from_pdf(path: Path, study_id: str, source: str = "manual_pdf") -> Document:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "pypdf is required to read PDFs (pip install pypdf)."
        ) from exc
    reader = PdfReader(str(path))
    segments = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            segments.append(Segment(locator=f"p.{i}", text=text))
    return Document(study_id=study_id, source=source, segments=segments)


_TAG = re.compile(r"<[^>]+>")


def _strip_tags(xml_fragment: str) -> str:
    text = _TAG.sub(" ", xml_fragment)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def from_jats(xml: str, study_id: str, source: str = "europepmc_xml") -> Document:
    """Very small JATS/XML sectioniser.

    Splits on <sec> boundaries, labels each by its <title>, and pulls <table-wrap>
    blocks out as their own 'Table N' segments so table cells keep a locator.
    This is intentionally simple: it gives the model locatable spans, not a full
    XML parse.
    """
    segments: list[Segment] = []

    for i, tw in enumerate(re.findall(r"<table-wrap\b.*?</table-wrap>", xml, re.S), 1):
        cap = re.search(r"<caption\b.*?</caption>", tw, re.S)
        label = f"Table {i}"
        m = re.search(r"<label>(.*?)</label>", tw, re.S)
        if m:
            label = _strip_tags(m.group(1)) or label
        body = _strip_tags(tw)
        segments.append(Segment(locator=label, text=body))

    secs = re.findall(r"<sec\b.*?</sec>", xml, re.S)
    if not secs:
        body = _strip_tags(xml)
        if body:
            segments.append(Segment(locator="fulltext", text=body))
    for sec in secs:
        title_m = re.search(r"<title>(.*?)</title>", sec, re.S)
        title = _strip_tags(title_m.group(1)) if title_m else "section"
        body = _strip_tags(re.sub(r"<table-wrap\b.*?</table-wrap>", " ", sec, flags=re.S))
        if body:
            segments.append(Segment(locator=title or "section", text=body))

    return Document(study_id=study_id, source=source, segments=segments)
