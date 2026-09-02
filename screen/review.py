"""Terminal review command for the human queue.

Walks every queued record, shows title, abstract, and both model rationales,
and takes a single keystroke:

    i = include    e = exclude    u = uncertain (leave queued)
    s = skip for now              q = quit

Human decisions are written with reviewer='human' and are final: the status
roll-up switches to resolved_by='human' and no later model run will change it.
If a record already has a human decision, it is skipped with a note rather than
re-asked, so a decision is never overwritten.

    python -m screen.review [--db data/db/records.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from . import db as sdb
from .run import DEFAULT_DB

_KEYMAP = {"i": "include", "e": "exclude", "u": "uncertain"}


def _fmt_pass(conn: sqlite3.Connection, rid: str, pass_name: str) -> str:
    row = conn.execute(
        """SELECT decision, confidence, reason, criteria_hit
           FROM screen_decisions
           WHERE reviewer='model' AND record_id=? AND pass_name=?
           ORDER BY created_at DESC LIMIT 1""",
        (rid, pass_name),
    ).fetchone()
    if not row:
        return f"  pass {pass_name}: (no model decision)"
    crit = ", ".join(json.loads(row["criteria_hit"])) or "-"
    conf = row["confidence"]
    conf_s = f"{conf:.2f}" if conf is not None else "-"
    return (f"  pass {pass_name}: {row['decision']:9s} conf={conf_s}  "
            f"[{crit}]\n           {row['reason']}")


def review_loop(conn: sqlite3.Connection,
                prompt_fn: Callable[[str], str] = input,
                out=print) -> dict:
    """Drive the review. prompt_fn/out are injectable so tests can script it."""
    queued = sdb.queued_records(conn)
    stats = {"reviewed": 0, "skipped": 0, "already_human": 0, "quit": False}
    for q in queued:
        rid = q["record_id"]
        if sdb.get_human_decision(conn, rid) is not None:
            stats["already_human"] += 1
            continue
        rec = sdb.record_by_id(conn, rid)
        if rec is None:
            continue
        out("=" * 72)
        out(f"{rid}   ({rec['year']}, {rec['journal']})   queued: {q['queue_reason']}")
        out(f"TITLE: {rec['title']}")
        out(f"ABSTRACT: {rec['abstract']}")
        out(_fmt_pass(conn, rid, "A"))
        out(_fmt_pass(conn, rid, "B"))
        while True:
            key = prompt_fn("[i]nclude [e]xclude [u]ncertain [s]kip [q]uit > ").strip().lower()
            if key == "q":
                stats["quit"] = True
                return stats
            if key == "s":
                stats["skipped"] += 1
                break
            if key in _KEYMAP:
                sdb.save_human_decision(conn, rid, _KEYMAP[key],
                                        reason="human review")
                stats["reviewed"] += 1
                break
            out("  unrecognized key")
    return stats


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Human review of the screening queue.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)
    conn = sdb.connect(args.db)
    stats = review_loop(conn)
    print(f"\nreviewed {stats['reviewed']}, skipped {stats['skipped']}, "
          f"already-human {stats['already_human']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
