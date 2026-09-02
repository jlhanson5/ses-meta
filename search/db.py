"""SQLite persistence.

Schema (exactly as specified):
  records(id, doi, pmid, title, abstract, authors, year, journal, source,
          first_seen_run, raw_json)
  runs(run_id, timestamp, query_hash, n_new, n_total)

Idempotency contract: `id` is a deterministic content key (see model.compute_id),
so INSERT OR IGNORE means re-running the same window inserts nothing new and
never overwrites an existing row's first_seen_run. n_new is computed by diffing
incoming ids against ids already present, so the count is exact even though the
insert is a no-op for known rows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .model import Record

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id             TEXT PRIMARY KEY,
    doi            TEXT,
    pmid           TEXT,
    title          TEXT,
    abstract       TEXT,
    authors        TEXT,
    year           INTEGER,
    journal        TEXT,
    source         TEXT,
    first_seen_run TEXT NOT NULL,
    raw_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_doi  ON records(doi);
CREATE INDEX IF NOT EXISTS idx_records_pmid ON records(pmid);
CREATE INDEX IF NOT EXISTS idx_records_run  ON records(first_seen_run);

CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    timestamp  TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    n_new      INTEGER NOT NULL,
    n_total    INTEGER NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def existing_ids(conn: sqlite3.Connection, ids: Iterable[str]) -> set[str]:
    ids = list(ids)
    if not ids:
        return set()
    found: set[str] = set()
    # chunk to stay under SQLite's variable limit
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"SELECT id FROM records WHERE id IN ({','.join('?' * len(chunk))})"
        found.update(r[0] for r in conn.execute(q, chunk))
    return found


def upsert_records(conn: sqlite3.Connection, records: list[Record],
                   run_id: str) -> int:
    """Insert new records, ignore known ones. Return the count of genuinely new rows."""
    incoming = {r.id: r for r in records}          # de-dup within batch by id
    already = existing_ids(conn, incoming.keys())
    new_ids = [rid for rid in incoming if rid not in already]

    rows = [incoming[rid].to_row(run_id) for rid in new_ids]
    conn.executemany(
        """
        INSERT OR IGNORE INTO records
            (id, doi, pmid, title, abstract, authors, year, journal,
             source, first_seen_run, raw_json)
        VALUES
            (:id, :doi, :pmid, :title, :abstract, :authors, :year, :journal,
             :source, :first_seen_run, :raw_json)
        """,
        rows,
    )
    conn.commit()
    return len(new_ids)


def total_records(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]


def record_run(conn: sqlite3.Connection, run_id: str, timestamp: str,
               query_hash: str, n_new: int, n_total: int) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO runs (run_id, timestamp, query_hash, n_new, n_total)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, timestamp, query_hash, n_new, n_total),
    )
    conn.commit()


def last_run_date(conn: sqlite3.Connection) -> str | None:
    """ISO date of the most recent run, or None. Used for incremental --since default."""
    row = conn.execute(
        "SELECT timestamp FROM runs ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return row[0][:10]
