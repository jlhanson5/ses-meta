"""Build the human review queue as a CSV.

The queue is derived state: it is rebuilt from screen_status + screen_decisions
every time, so it always reflects the current database and never drifts. A record
already resolved by a human drops out of the queue. Each row carries enough for a
human to decide without opening the database: title, abstract, both model
rationales, and why it queued.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from . import db as sdb

DEFAULT_QUEUE = Path(__file__).resolve().parent / "review_queue.csv"

FIELDS = [
    "record_id", "queue_reason", "year", "journal", "title", "abstract",
    "pass_a_decision", "pass_a_confidence", "pass_a_reason", "pass_a_criteria",
    "pass_b_decision", "pass_b_confidence", "pass_b_reason", "pass_b_criteria",
]


def _pass_row(conn: sqlite3.Connection, record_id: str, pass_name: str) -> dict:
    row = conn.execute(
        """
        SELECT decision, confidence, reason, criteria_hit
        FROM screen_decisions
        WHERE reviewer='model' AND record_id=? AND pass_name=?
        ORDER BY created_at DESC LIMIT 1
        """,
        (record_id, pass_name),
    ).fetchone()
    if not row:
        return {"decision": "", "confidence": "", "reason": "", "criteria": ""}
    return {
        "decision": row["decision"],
        "confidence": row["confidence"],
        "reason": row["reason"],
        "criteria": ", ".join(json.loads(row["criteria_hit"])),
    }


def build_queue(conn: sqlite3.Connection, out_path: Path = DEFAULT_QUEUE) -> int:
    """Write review_queue.csv from current DB state. Returns the row count."""
    out_path = Path(out_path)
    queued = sdb.queued_records(conn)
    rows_written = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for q in queued:
            rid = q["record_id"]
            rec = sdb.record_by_id(conn, rid)
            if rec is None:
                continue
            a = _pass_row(conn, rid, "A")
            b = _pass_row(conn, rid, "B")
            writer.writerow({
                "record_id": rid,
                "queue_reason": q["queue_reason"],
                "year": rec["year"],
                "journal": rec["journal"],
                "title": rec["title"],
                "abstract": rec["abstract"],
                "pass_a_decision": a["decision"],
                "pass_a_confidence": a["confidence"],
                "pass_a_reason": a["reason"],
                "pass_a_criteria": a["criteria"],
                "pass_b_decision": b["decision"],
                "pass_b_confidence": b["confidence"],
                "pass_b_reason": b["reason"],
                "pass_b_criteria": b["criteria"],
            })
            rows_written += 1
    return rows_written
