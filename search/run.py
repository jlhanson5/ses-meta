"""Search orchestrator and CLI.

    python -m search.run --since 2026-08-01
    python -m search.run                # incremental from the last run (or 30d back)

Flow: build query set -> for each source, run every query over the window
(cached) -> union -> deduplicate (logged) -> idempotent upsert -> record the run.
Reports records-per-source, duplicates merged, and the final unique count.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .db import connect, last_run_date, record_run, total_records, upsert_records
from .dedup import DedupLog, deduplicate
from .model import Record
from .queries import build_queries, format_for, load_spec, query_set_hash
from .sources import SOURCES

# Repo-root-relative paths. This file is <root>/search/run.py.
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "db" / "records.db"
LOG_DIR = ROOT / "logs"
DEDUP_LOG = LOG_DIR / "dedup.jsonl"

DEFAULT_WINDOW_DAYS = 30

# env var name per source (keys are read from the environment ONLY)
API_KEY_ENV = {
    "pubmed": "NCBI_API_KEY",
    "semanticscholar": "S2_API_KEY",
}


def _setup_logging(log_dir: Path = LOG_DIR) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("search")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_dir / "search.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def resolve_window(conn, since: str | None, until: str | None) -> tuple[str, str]:
    """Return (date_from, date_to) ISO strings.

    Precedence for date_from: explicit --since > last run date > today-30d.
    date_to defaults to today.
    """
    date_to = until or date.today().isoformat()
    if since:
        return since, date_to
    prev = last_run_date(conn)
    if prev:
        return prev, date_to
    return (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat(), date_to


def run_search(
    since: str | None = None,
    until: str | None = None,
    only_sources: list[str] | None = None,
    queries_path: Path | None = None,
    raw_dir: Path = RAW_DIR,
    db_path: Path = DB_PATH,
    log_dir: Path = LOG_DIR,
    logger: logging.Logger | None = None,
) -> dict:
    """Execute one search pass. Returns a summary dict."""
    logger = logger or _setup_logging(log_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dedup_log_path = log_dir / "dedup.jsonl"

    conn = connect(db_path)
    date_from, date_to = resolve_window(conn, since, until)

    spec = load_spec(queries_path) if queries_path else load_spec()
    queries = build_queries(spec)
    qset_hash = query_set_hash(queries)

    now = datetime.now(timezone.utc)
    run_date = now.date().isoformat()
    run_id = f"{now.isoformat()}_{qset_hash}"

    source_names = only_sources or list(SOURCES.keys())
    logger.info("run %s window %s..%s | %d queries x %d sources",
                run_id, date_from, date_to, len(queries), len(source_names))

    all_records: list[Record] = []
    per_source: dict[str, int] = {}

    for name in source_names:
        cls = SOURCES[name]
        api_key = os.environ.get(API_KEY_ENV.get(name, ""), None)
        src = cls(raw_dir=raw_dir, run_date=run_date, api_key=api_key)
        count = 0
        for q in queries:
            qstr = format_for(name, q)
            try:
                recs = src.run(qstr, date_from, date_to)
            except Exception as exc:  # one bad query must not sink the run
                logger.warning("%s query %s failed: %s", name, q.id, exc)
                continue
            count += len(recs)
            all_records.extend(recs)
        per_source[name] = count
        logger.info("source %-15s fetched %d records (pre-dedup)", name, count)

    n_raw = len(all_records)
    with DedupLog(dedup_log_path) as dlog:
        unique = deduplicate(all_records, dlog)
    n_merged = n_raw - len(unique)
    logger.info("dedup: %d raw -> %d unique (%d merged)", n_raw, len(unique), n_merged)

    n_new = upsert_records(conn, unique, run_id)
    n_total = total_records(conn)
    record_run(conn, run_id, now.isoformat(), qset_hash, n_new, n_total)
    conn.close()

    logger.info("run %s complete: n_new=%d n_total=%d", run_id, n_new, n_total)
    return {
        "run_id": run_id,
        "window": [date_from, date_to],
        "per_source": per_source,
        "n_raw": n_raw,
        "n_merged": n_merged,
        "n_unique_this_run": len(unique),
        "n_new": n_new,
        "n_total": n_total,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="search.run",
                                description="SES x subcortical-volume literature search")
    p.add_argument("--since", metavar="YYYY-MM-DD",
                   help="start of window. Default: last run date, else 30 days back.")
    p.add_argument("--until", metavar="YYYY-MM-DD",
                   help="end of window. Default: today.")
    p.add_argument("--sources", nargs="+", choices=list(SOURCES.keys()),
                   help="subset of sources to query. Default: all four.")
    p.add_argument("--queries", type=Path, help="path to an alternate queries.yaml")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_search(
        since=args.since,
        until=args.until,
        only_sources=args.sources,
        queries_path=args.queries,
    )
    print("\n=== search summary ===")
    for name, n in summary["per_source"].items():
        print(f"  {name:15s} {n}")
    print(f"  duplicates merged : {summary['n_merged']}")
    print(f"  unique this run   : {summary['n_unique_this_run']}")
    print(f"  new to database   : {summary['n_new']}")
    print(f"  total in database : {summary['n_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
