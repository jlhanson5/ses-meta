"""Persistence for extraction: effects, retrieval status, and CSV export.

Two audit properties:

1. Effect rows are idempotent and never silently overwritten. Each row has a
   deterministic effect_key = hash(study_id + roi + hemisphere + ses_construct +
   ses_timing + effect_type + prompt_hash). Writes are INSERT OR IGNORE on that
   key, so re-running extraction with the same prompt inserts nothing new. A
   changed prompt has a new prompt_hash and therefore new rows, not overwrites.
   Overwriting an existing row requires an explicit caller decision (see
   run.py); there is no silent-clobber path.

2. Retrieval status is recorded for every study, so an unretrieved study is
   visible, not missing.

The effects live in the same records.db as search and screen, referencing
records.id, but this module only creates and writes its OWN tables.
"""
from __future__ import annotations

import csv
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .schema import Effect

SCHEMA = """
CREATE TABLE IF NOT EXISTS effects (
    effect_key   TEXT PRIMARY KEY,
    study_id     TEXT NOT NULL,
    cohort_name  TEXT,
    sample_overlap_group TEXT,
    n            REAL,
    mean_age     REAL,
    age_range    TEXT,
    pct_female   REAL,
    sample_type  TEXT,
    ses_construct TEXT,
    ses_timing   TEXT,
    roi          TEXT NOT NULL,
    hemisphere   TEXT,
    volume_pipeline TEXT,
    icv_adjustment TEXT,
    covariates   TEXT,
    effect_type  TEXT,
    effect_value REAL,
    se_or_ci     TEXT,
    p_value      REAL,
    direction_coded_positive_means_higher_SES_larger_volume INTEGER,
    page_number  TEXT,
    verbatim_quote TEXT,
    extraction_confidence REAL NOT NULL,
    verified     TEXT,          -- 'confirmed' | 'disputed' | NULL (not yet)
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reason TEXT,
    prompt_hash  TEXT,
    model_version TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_effects_study ON effects(study_id);

CREATE TABLE IF NOT EXISTS retrieval_status (
    study_id   TEXT PRIMARY KEY,
    status     TEXT NOT NULL,   -- europepmc_xml | unpaywall_pdf | manual_pdf | unretrieved
    detail     TEXT,
    updated_at TEXT NOT NULL
);
"""

ROW_COLUMNS = [
    "study_id", "cohort_name", "sample_overlap_group", "n", "mean_age",
    "age_range", "pct_female", "sample_type", "ses_construct", "ses_timing",
    "roi", "hemisphere", "volume_pipeline", "icv_adjustment", "covariates",
    "effect_type", "effect_value", "se_or_ci", "p_value",
    "direction_coded_positive_means_higher_SES_larger_volume",
    "page_number", "verbatim_quote", "extraction_confidence",
]


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


def effect_key(eff: Effect, prompt_hash: str) -> str:
    parts = [eff.study_id, eff.roi, eff.hemisphere or "", eff.ses_construct or "",
             eff.ses_timing or "", eff.effect_type or "", prompt_hash]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def effect_exists(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM effects WHERE effect_key=?", (key,)).fetchone() is not None


def save_effect(conn: sqlite3.Connection, eff: Effect, *, prompt_hash: str,
                model_version: str, verified: Optional[str] = None,
                needs_review: bool = False, review_reason: Optional[str] = None) -> str:
    """INSERT OR IGNORE the effect. Returns its key. Never overwrites."""
    key = effect_key(eff, prompt_hash)
    row = eff.to_row()
    cols = ["effect_key"] + ROW_COLUMNS + [
        "verified", "needs_review", "review_reason", "prompt_hash",
        "model_version", "created_at"]
    vals = [key] + [row[c] for c in ROW_COLUMNS] + [
        verified, int(needs_review), review_reason, prompt_hash, model_version, _now()]
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR IGNORE INTO effects ({','.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()
    return key


def set_verification(conn: sqlite3.Connection, key: str, *, verified: str,
                     needs_review: bool, review_reason: Optional[str]) -> None:
    conn.execute(
        "UPDATE effects SET verified=?, needs_review=?, review_reason=? WHERE effect_key=?",
        (verified, int(needs_review), review_reason, key),
    )
    conn.commit()


def record_retrieval(conn: sqlite3.Connection, study_id: str, status: str,
                     detail: str) -> None:
    conn.execute(
        """INSERT INTO retrieval_status (study_id, status, detail, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(study_id) DO UPDATE SET
             status=excluded.status, detail=excluded.detail,
             updated_at=excluded.updated_at""",
        (study_id, status, detail, _now()),
    )
    conn.commit()


def effects_for_study(conn: sqlite3.Connection, study_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM effects WHERE study_id=?", (study_id,)).fetchall()


def all_effects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM effects ORDER BY study_id, roi").fetchall()


def review_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM effects WHERE needs_review=1 ORDER BY study_id").fetchall()


def included_studies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Studies screening marked include, joined to their record metadata."""
    return conn.execute(
        """
        SELECT r.id, r.doi, r.pmid, r.title, r.abstract, r.year, r.journal, r.raw_json
        FROM screen_status s JOIN records r ON r.id = s.record_id
        WHERE s.final_decision = 'include'
        ORDER BY r.id
        """
    ).fetchall()


def export_effects_csv(conn: sqlite3.Connection, out_path: Path) -> int:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = all_effects(conn)
    export_cols = ["study_id"] + ROW_COLUMNS[1:] + [
        "verified", "needs_review", "review_reason", "extraction_confidence"]
    # de-dup column names while preserving order
    seen, cols = set(), []
    for c in export_cols:
        if c not in seen:
            seen.add(c); cols.append(c)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in cols})
    return len(rows)
