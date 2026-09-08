"""Build extract/review_queue.csv for human spot-check.

One row per effect that needs review (disputed by verification, or below the
confidence floor, or an unrecognized cohort). The row is laid out for a
side-by-side check: the extracted value next to its locator and verbatim quote,
plus the verifier's reason, so a human can confirm against the paper fast.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

DEFAULT_QUEUE = Path(__file__).resolve().parent / "review_queue.csv"

FIELDS = [
    "study_id", "roi", "hemisphere", "ses_construct", "effect_type",
    "effect_value", "se_or_ci", "p_value", "n",
    "page_number", "verbatim_quote",
    "cohort_name", "sample_overlap_group",
    "extraction_confidence", "verified", "review_reason",
]


def build_queue(conn: sqlite3.Connection, out_path: Path = DEFAULT_QUEUE) -> int:
    out_path = Path(out_path)
    rows = conn.execute(
        "SELECT * FROM effects WHERE needs_review=1 ORDER BY study_id, roi").fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FIELDS})
    return len(rows)
