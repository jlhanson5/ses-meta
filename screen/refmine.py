"""Reference mining.

A review or meta-analysis is excluded from the meta-analysis itself but is a
gold seam of citations. For each such record flagged is_refmine_target, resolve
it to an OpenAlex work, pull its referenced_works, fetch those works, and insert
them into the records table as fresh, unscreened records. The next `screen.run`
picks them up automatically, so mined references flow back into the screening
queue with no extra wiring.

Network calls go through an injectable fetcher so this is testable offline. The
default fetcher hits OpenAlex via the shared search.http layer; tests pass a
fixture-backed fake. In this sandbox the OpenAlex domain is blocked, so the live
path runs on Jamie's machine and the offline test proves the logic.

    python -m screen.refmine [--db data/db/records.db]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from search.db import upsert_records
from search.model import Record
from search.sources.openalex import reconstruct_abstract

from . import db as sdb
from .run import DEFAULT_DB

WORKS_ENDPOINT = "https://api.openalex.org/works"

# A fetcher takes an OpenAlex work id or a "doi:..." string and returns the work
# JSON dict, or None if it cannot be resolved.
Fetcher = Callable[[str], Optional[dict]]


def _now_run_id() -> str:
    return "refmine:" + datetime.now(timezone.utc).isoformat()


def _openalex_id_for(conn: sqlite3.Connection, record_id: str) -> Optional[str]:
    """Best handle for resolving the target work: stored OpenAlex id, else DOI."""
    row = conn.execute(
        "SELECT doi, raw_json FROM records WHERE id=?", (record_id,)
    ).fetchone()
    if row is None:
        return None
    if row["raw_json"]:
        try:
            raw = json.loads(row["raw_json"])
            if isinstance(raw, dict) and raw.get("id"):
                return str(raw["id"])           # OpenAlex work URL
        except json.JSONDecodeError:
            pass
    if row["doi"]:
        return f"doi:{row['doi']}"
    return None


def referenced_ids(work: dict) -> list[str]:
    return [str(w) for w in work.get("referenced_works", []) if w]


def work_to_record(work: dict) -> Record:
    ids = work.get("ids", {}) or {}
    pmid = None
    if ids.get("pmid"):
        pmid = str(ids["pmid"]).rsplit("/", 1)[-1]
    authors = "; ".join(
        a.get("author", {}).get("display_name", "")
        for a in work.get("authorships", [])
        if a.get("author", {}).get("display_name")
    ) or None
    venue = (work.get("primary_location") or {}).get("source") or {}
    return Record(
        doi=work.get("doi"),
        pmid=pmid,
        title=work.get("title"),
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=authors,
        year=work.get("publication_year"),
        journal=venue.get("display_name"),
        source="refmine:openalex",
        raw_json=json.dumps({"id": work.get("id")}, ensure_ascii=False),
    )


def mine_target(conn: sqlite3.Connection, record_id: str, fetch: Fetcher,
                run_id: str) -> int:
    """Mine one review/meta. Returns count of new records inserted."""
    handle = _openalex_id_for(conn, record_id)
    if handle is None:
        sdb.mark_mined(conn, record_id, 0)
        return 0
    work = fetch(handle)
    if not work:
        sdb.mark_mined(conn, record_id, 0)
        return 0
    ref_ids = referenced_ids(work)
    records: list[Record] = []
    for rid in ref_ids:
        ref_work = fetch(rid)
        if ref_work:
            records.append(work_to_record(ref_work))
    n_new = upsert_records(conn, records, run_id) if records else 0
    sdb.mark_mined(conn, record_id, len(ref_ids))
    return n_new


def mine_all(conn: sqlite3.Connection, fetch: Fetcher,
             run_id: Optional[str] = None) -> dict:
    run_id = run_id or _now_run_id()
    targets = sdb.refmine_targets(conn)
    total_new = 0
    per_target = {}
    for t in targets:
        n = mine_target(conn, t, fetch, run_id)
        per_target[t] = n
        total_new += n
    return {"targets": len(targets), "new_records": total_new,
            "per_target": per_target, "run_id": run_id}


def _live_fetcher() -> Fetcher:
    """Resolve works against OpenAlex via the shared http layer (live path)."""
    from search.http import RateLimiter, get_json
    limiter = RateLimiter(0.11)
    mailto = None

    def fetch(handle: str) -> Optional[dict]:
        if handle.startswith("doi:"):
            url = f"{WORKS_ENDPOINT}/https://doi.org/{handle[4:]}"
        elif handle.startswith("http"):
            url = handle.replace("https://openalex.org/", f"{WORKS_ENDPOINT}/")
        else:
            url = f"{WORKS_ENDPOINT}/{handle}"
        params = {"mailto": mailto} if mailto else None
        try:
            return get_json(url, params=params, limiter=limiter)
        except Exception:
            return None

    return fetch


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Mine references of included reviews/metas.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args(argv)
    conn = sdb.connect(args.db)
    result = mine_all(conn, _live_fetcher())
    print(f"mined {result['targets']} reviews -> {result['new_records']} new records")
    print("run `python -m screen.run` to screen the newly added references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
