"""Cross-source deduplication.

Order of resolution:
  1. Exact DOI match (normalized). Highest confidence.
  2. Fuzzy fallback for records without a shared DOI: normalized-title similarity
     >= threshold AND same publication year AND same first-author last name.

Every merge decision is appended to /logs/dedup.jsonl with the reason, the two
record ids, and (for fuzzy) the similarity score. That log is the audit trail the
site and the frozen snapshot can cite.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from .model import Record, first_author_last, normalize_title

TITLE_THRESHOLD = 92  # token_sort_ratio 0..100


def _merge_two(keep: Record, other: Record) -> Record:
    """Fold `other` into `keep`, preferring non-empty existing fields.

    DOI/PMID are filled from whichever record has them. Sources accumulate.
    """
    keep.doi = keep.doi or other.doi
    keep.pmid = keep.pmid or other.pmid
    keep.title = keep.title or other.title
    keep.abstract = keep.abstract or other.abstract
    keep.authors = keep.authors or other.authors
    keep.year = keep.year or other.year
    keep.journal = keep.journal or other.journal
    for s in other.sources:
        if s not in keep.sources:
            keep.sources.append(s)
    return keep


class DedupLog:
    """Append-only JSONL merge log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def write(self, reason: str, kept_id: str, dropped_id: str,
              kept_sources: list[str], dropped_sources: list[str],
              score: Optional[float] = None, detail: Optional[dict] = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "kept_id": kept_id,
            "dropped_id": dropped_id,
            "kept_sources": kept_sources,
            "dropped_sources": dropped_sources,
            "score": score,
        }
        if detail:
            entry["detail"] = detail
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "DedupLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def deduplicate(records: list[Record], log: DedupLog) -> list[Record]:
    """Return the unique set, merging duplicates and logging each merge.

    Deterministic: input order fixes which record is kept (the first seen wins as
    the survivor; later matches fold into it).
    """
    by_doi: dict[str, Record] = {}
    # (year, first_author_last) -> list of surviving records without a doi match yet
    fuzzy_index: dict[tuple, list[Record]] = {}
    survivors: list[Record] = []

    for rec in records:
        # -- 1. DOI exact ------------------------------------------------------
        if rec.doi and rec.doi in by_doi:
            keep = by_doi[rec.doi]
            log.write("doi_exact", keep.id, rec.id,
                      list(keep.sources), list(rec.sources),
                      detail={"doi": rec.doi})
            _merge_two(keep, rec)
            continue

        # -- 2. fuzzy fallback (only when no DOI collision) --------------------
        matched = None
        if not rec.doi:
            key = (rec.year, first_author_last(rec.authors))
            nt = normalize_title(rec.title)
            for cand in fuzzy_index.get(key, []):
                score = fuzz.token_sort_ratio(nt, normalize_title(cand.title))
                if score >= TITLE_THRESHOLD:
                    matched = cand
                    log.write("fuzzy_title_author_year", cand.id, rec.id,
                              list(cand.sources), list(rec.sources),
                              score=float(score),
                              detail={"year": rec.year,
                                      "first_author": key[1],
                                      "title_a": cand.title,
                                      "title_b": rec.title})
                    _merge_two(cand, rec)
                    break
        if matched is not None:
            continue

        # -- new survivor ------------------------------------------------------
        survivors.append(rec)
        if rec.doi:
            by_doi[rec.doi] = rec
        else:
            key = (rec.year, first_author_last(rec.authors))
            fuzzy_index.setdefault(key, []).append(rec)

    return survivors
