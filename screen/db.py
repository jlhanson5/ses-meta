"""Persistence for screening: decisions, status roll-up, refmine tracking.

Two audit guarantees drive this schema:

1. Model decisions are cache-idempotent. A model row is unique on
   (record_id, pass_name, prompt_hash, model). Re-running the same pass with the
   same prompt inserts nothing (INSERT OR IGNORE) and, because run.py checks for
   the row before calling the model, costs no tokens. Change the prompt -> new
   prompt_hash -> a NEW row, never an overwrite.

2. Human decisions are final. A human row is unique on (record_id). Model runs
   never touch human rows, and the status roll-up always lets a human decision
   win. There is no code path that overwrites a human decision with a model one.

Every model decision carries model, model_version, prompt_version, prompt_hash,
and created_at, so any decision is reproducible and auditable.

These tables live in the SAME records.db as the search layer (they reference
records.id), but this module only ever creates and writes its own tables. It
reads records via a narrow helper and never alters the search schema.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schema import Decision

SCHEMA = """
CREATE TABLE IF NOT EXISTS screen_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id      TEXT NOT NULL,
    reviewer       TEXT NOT NULL,          -- 'model' | 'human'
    pass_name      TEXT NOT NULL,          -- 'A' | 'B' | 'human'
    decision       TEXT NOT NULL,          -- include | exclude | uncertain
    criteria_hit   TEXT NOT NULL,          -- JSON array
    reason         TEXT NOT NULL,
    confidence     REAL,                   -- NULL for human
    model          TEXT,                   -- e.g. 'claude-code:sonnet'
    model_version  TEXT,                   -- resolved version string
    prompt_version TEXT,                   -- e.g. 'screen_pass_a_v1'
    prompt_hash    TEXT,                   -- sha256 of prompt file
    created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_model_decision
    ON screen_decisions(record_id, pass_name, prompt_hash, model)
    WHERE reviewer = 'model';
CREATE UNIQUE INDEX IF NOT EXISTS ux_human_decision
    ON screen_decisions(record_id)
    WHERE reviewer = 'human';
CREATE INDEX IF NOT EXISTS idx_decisions_record
    ON screen_decisions(record_id);

CREATE TABLE IF NOT EXISTS screen_status (
    record_id         TEXT PRIMARY KEY,
    final_decision    TEXT NOT NULL,       -- include | exclude | queued
    routed_to_queue   INTEGER NOT NULL,    -- 0/1
    queue_reason      TEXT,
    resolved_by       TEXT,                -- 'model' | 'human'
    is_refmine_target INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screen_refmine (
    record_id  TEXT PRIMARY KEY,           -- the review/meta that was mined
    mined_at   TEXT NOT NULL,
    n_refs     INTEGER NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# model decisions (cache-idempotent)
# --------------------------------------------------------------------------

def get_model_decision(conn: sqlite3.Connection, record_id: str, pass_name: str,
                       prompt_hash: str, model: str) -> Optional[Decision]:
    """Return a cached model decision if one exists (the cache lookup)."""
    row = conn.execute(
        """
        SELECT decision, criteria_hit, reason, confidence
        FROM screen_decisions
        WHERE reviewer='model' AND record_id=? AND pass_name=?
              AND prompt_hash=? AND model=?
        """,
        (record_id, pass_name, prompt_hash, model),
    ).fetchone()
    if not row:
        return None
    return Decision(
        decision=row["decision"],
        criteria_hit=json.loads(row["criteria_hit"]),
        reason=row["reason"],
        confidence=row["confidence"] if row["confidence"] is not None else 0.0,
    )


def save_model_decision(conn: sqlite3.Connection, record_id: str, pass_name: str,
                        decision: Decision, *, model: str, model_version: str,
                        prompt_version: str, prompt_hash: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO screen_decisions
            (record_id, reviewer, pass_name, decision, criteria_hit, reason,
             confidence, model, model_version, prompt_version, prompt_hash,
             created_at)
        VALUES (?, 'model', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (record_id, pass_name, decision.decision,
         json.dumps(decision.criteria_hit), decision.reason, decision.confidence,
         model, model_version, prompt_version, prompt_hash, _now()),
    )
    conn.commit()


# --------------------------------------------------------------------------
# human decisions (final, never overwritten by a model run)
# --------------------------------------------------------------------------

def get_human_decision(conn: sqlite3.Connection, record_id: str) -> Optional[Decision]:
    row = conn.execute(
        "SELECT decision, criteria_hit, reason FROM screen_decisions "
        "WHERE reviewer='human' AND record_id=?",
        (record_id,),
    ).fetchone()
    if not row:
        return None
    return Decision(decision=row["decision"],
                    criteria_hit=json.loads(row["criteria_hit"]),
                    reason=row["reason"], confidence=1.0)


def save_human_decision(conn: sqlite3.Connection, record_id: str,
                        decision: str, reason: str = "") -> None:
    """Write a final human decision. Refuses to overwrite an existing one."""
    existing = get_human_decision(conn, record_id)
    if existing is not None:
        raise ValueError(
            f"human decision already exists for {record_id} "
            f"({existing.decision}); refusing to overwrite"
        )
    conn.execute(
        """
        INSERT INTO screen_decisions
            (record_id, reviewer, pass_name, decision, criteria_hit, reason,
             confidence, model, model_version, prompt_version, prompt_hash,
             created_at)
        VALUES (?, 'human', 'human', ?, '[]', ?, NULL, NULL, NULL, NULL, NULL, ?)
        """,
        (record_id, decision, reason, _now()),
    )
    # human decision is authoritative in the roll-up
    conn.execute(
        """
        INSERT INTO screen_status
            (record_id, final_decision, routed_to_queue, queue_reason,
             resolved_by, is_refmine_target, updated_at)
        VALUES (?, ?, 0, NULL, 'human',
                COALESCE((SELECT is_refmine_target FROM screen_status
                          WHERE record_id=?), 0), ?)
        ON CONFLICT(record_id) DO UPDATE SET
            final_decision=excluded.final_decision,
            routed_to_queue=0, queue_reason=NULL, resolved_by='human',
            updated_at=excluded.updated_at
        """,
        (record_id, decision, record_id, _now()),
    )
    conn.commit()


# --------------------------------------------------------------------------
# status roll-up
# --------------------------------------------------------------------------

def upsert_status(conn: sqlite3.Connection, record_id: str, final: str,
                  routed_to_queue: bool, queue_reason: Optional[str],
                  resolved_by: str, is_refmine_target: bool) -> None:
    """Write the model roll-up, but never clobber a human resolution."""
    human = conn.execute(
        "SELECT 1 FROM screen_status WHERE record_id=? AND resolved_by='human'",
        (record_id,),
    ).fetchone()
    if human:
        return  # human decision stands
    conn.execute(
        """
        INSERT INTO screen_status
            (record_id, final_decision, routed_to_queue, queue_reason,
             resolved_by, is_refmine_target, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(record_id) DO UPDATE SET
            final_decision=excluded.final_decision,
            routed_to_queue=excluded.routed_to_queue,
            queue_reason=excluded.queue_reason,
            resolved_by=excluded.resolved_by,
            is_refmine_target=excluded.is_refmine_target,
            updated_at=excluded.updated_at
        """,
        (record_id, final, int(routed_to_queue), queue_reason, resolved_by,
         int(is_refmine_target), _now()),
    )
    conn.commit()


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT final_decision, COUNT(*) n FROM screen_status GROUP BY final_decision"
    ).fetchall()
    return {r["final_decision"]: r["n"] for r in rows}


def queued_records(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT record_id, queue_reason FROM screen_status "
        "WHERE routed_to_queue=1 AND resolved_by != 'human' ORDER BY record_id"
    ).fetchall()


def refmine_targets(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT s.record_id FROM screen_status s
        LEFT JOIN screen_refmine m ON m.record_id = s.record_id
        WHERE s.is_refmine_target=1 AND m.record_id IS NULL
        ORDER BY s.record_id
        """
    ).fetchall()
    return [r["record_id"] for r in rows]


def mark_mined(conn: sqlite3.Connection, record_id: str, n_refs: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO screen_refmine (record_id, mined_at, n_refs) "
        "VALUES (?, ?, ?)",
        (record_id, _now(), n_refs),
    )
    conn.commit()


# --------------------------------------------------------------------------
# reading records to screen (narrow read into the search schema)
# --------------------------------------------------------------------------

def unscreened_records(conn: sqlite3.Connection, limit: Optional[int] = None,
                       random_sample: bool = False) -> list[sqlite3.Row]:
    """Records with no status row yet. Optionally a random sample of them."""
    order = "RANDOM()" if random_sample else "r.id"
    q = f"""
        SELECT r.id, r.title, r.abstract, r.year, r.journal
        FROM records r
        LEFT JOIN screen_status s ON s.record_id = r.id
        WHERE s.record_id IS NULL
        ORDER BY {order}
    """
    if limit is not None:
        q += " LIMIT ?"
        return conn.execute(q, (limit,)).fetchall()
    return conn.execute(q).fetchall()


def record_by_id(conn: sqlite3.Connection, record_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT id, title, abstract, year, journal FROM records WHERE id=?",
        (record_id,),
    ).fetchone()
