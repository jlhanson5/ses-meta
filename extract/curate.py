"""Human review editor: export effects to an editable CSV, import decisions back.

The auto-generated review_queue.csv is read-only and gets overwritten each run,
so it is not where human decisions live. This is the round-trip:

    python -m extract.curate export   ->  extract/review_edit.csv
    (open in Excel, correct fields, assign sample_overlap_group, mark
     review_action per row: keep / edit / drop; add notes)
    python -m extract.curate import extract/review_edit.csv

Import writes your changes to the effects table as human decisions:
verified='human', human_reviewed=1, needs_review cleared. A human-reviewed row
is never re-verified or overwritten by a later model run (immutable, like a
human screening decision). review_action='drop' marks a row excluded from the
analysis dataset without deleting it.

Cohort assignment is folded in: sample_overlap_group is an editable column, so
you assign overlap groups for the unrecognized cohorts in the same pass.

Rows are matched back by effect_key; do not edit that column. Rows with a blank
review_action are treated as not-yet-reviewed and left untouched, so you can
review in several sittings.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Optional

from . import db as edb
from .run import DEFAULT_DB
from .schema import ENUMS

DEFAULT_FILE = Path(__file__).resolve().parent / "review_edit.csv"

# context columns (read-only for the human) + the edit control columns
CONTEXT = ["effect_key", "study_id", "verified", "needs_review", "review_reason"]
CONTROL = ["review_action", "notes"]
NUMERIC = ("n", "mean_age", "pct_female", "effect_value")


def export_csv(conn: sqlite3.Connection, out_path: Path = DEFAULT_FILE) -> int:
    """Write every effect to an editable CSV, flagged rows first."""
    out_path = Path(out_path)
    rows = conn.execute(
        "SELECT * FROM effects ORDER BY needs_review DESC, study_id, roi").fetchall()
    header = CONTEXT + edb.EDITABLE_FIELDS + CONTROL
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            row = {c: r[c] for c in CONTEXT}
            for c in edb.EDITABLE_FIELDS:
                row[c] = r[c]
            row["review_action"] = ""      # human fills: keep / edit / drop
            row["notes"] = ""
            w.writerow(row)
    return len(rows)


def _coerce(field: str, value: str):
    v = (value or "").strip()
    if v == "":
        return None
    if field in NUMERIC:
        try:
            return float(v)
        except ValueError:
            return None
    if field in ENUMS:
        lv = v.lower()
        return lv if lv in ENUMS[field] else None
    return v                                 # p_value, strings, se_or_ci as-is


def import_csv(conn: sqlite3.Connection, in_path: Path) -> dict:
    in_path = Path(in_path)
    applied = dropped = skipped = unmatched = 0
    with in_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            action = (row.get("review_action") or "").strip().lower()
            if action not in ("keep", "edit", "drop"):
                skipped += 1
                continue
            key = (row.get("effect_key") or "").strip()
            current = edb.get_effect_row(conn, key)
            if current is None:
                unmatched += 1
                continue
            notes = (row.get("notes") or "").strip() or None
            if action == "drop":
                edb.apply_human_edits(conn, key, {}, excluded=True, notes=notes)
                dropped += 1
                continue
            # keep or edit: apply any changed editable field
            updates = {}
            for f in edb.EDITABLE_FIELDS:
                new = _coerce(f, row.get(f, ""))
                if new != current[f]:
                    updates[f] = new
            edb.apply_human_edits(conn, key, updates, excluded=False, notes=notes)
            applied += 1
    return {"applied": applied, "dropped": dropped, "skipped": skipped,
            "unmatched": unmatched}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Export/import the review editor CSV.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export"); ex.add_argument("--db", type=Path, default=DEFAULT_DB)
    ex.add_argument("--out", type=Path, default=DEFAULT_FILE)
    im = sub.add_parser("import"); im.add_argument("file", type=Path)
    im.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)

    conn = edb.connect(args.db)
    if args.cmd == "export":
        n = export_csv(conn, args.out)
        print(f"exported {n} effects -> {args.out}")
        print("edit in Excel, set review_action per row (keep/edit/drop), then:")
        print(f"  python -m extract.curate import {args.out}")
    else:
        res = import_csv(conn, args.file)
        edb.export_effects_csv(conn, Path("data/effects.csv"))
        print(f"applied {res['applied']}, dropped {res['dropped']}, "
              f"skipped(blank) {res['skipped']}, unmatched {res['unmatched']}")
        print("data/effects.csv refreshed with human decisions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
