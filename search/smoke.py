"""Smoke test for the search layer.

Two modes:

  python -m search.smoke --offline
      Runs the full parse -> dedup -> db pipeline against the bundled fixtures
      with no network. Proves wiring end to end and prints the required report.
      Use this in CI and anywhere the source APIs are unreachable.

  python -m search.smoke --live --days 30
      Runs the real orchestrator over the last N days against all four APIs.
      Requires network access to the source domains and (optionally)
      NCBI_API_KEY / S2_API_KEY in the environment.

Both print: records per source, duplicates merged, final unique count.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

FIX = Path(__file__).parent / "tests" / "fixtures"


def _print_report(per_source: dict, n_merged: int, n_unique: int,
                  n_new: int | None = None, n_total: int | None = None) -> None:
    print("\n=== smoke report ===")
    for name, n in per_source.items():
        print(f"  {name:15s} {n}")
    print(f"  duplicates merged : {n_merged}")
    print(f"  final unique      : {n_unique}")
    if n_new is not None:
        print(f"  new to database   : {n_new}")
    if n_total is not None:
        print(f"  total in database : {n_total}")


def run_offline() -> dict:
    """Parse fixtures through each source, dedup, persist to a temp DB."""
    from .db import connect, record_run, total_records, upsert_records
    from .dedup import DedupLog, deduplicate
    from .sources import EuropePMC, OpenAlex, PubMed, SemanticScholar

    def load_json(name: str) -> dict:
        return json.loads((FIX / name).read_text(encoding="utf-8"))

    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    raw = tmp / "raw"
    raw.mkdir()

    pm = PubMed(raw_dir=raw, run_date="offline")
    ep = EuropePMC(raw_dir=raw, run_date="offline")
    oa = OpenAlex(raw_dir=raw, run_date="offline")
    s2 = SemanticScholar(raw_dir=raw, run_date="offline")

    pm_recs = pm._parse({"efetch_xml": (FIX / "pubmed_efetch.xml").read_text()})
    ep_recs = ep._parse(load_json("europepmc.json"))
    oa_recs = oa._parse(load_json("openalex.json"))
    s2_recs = s2._parse(load_json("semanticscholar.json"))

    per_source = {
        "pubmed": len(pm_recs), "europepmc": len(ep_recs),
        "openalex": len(oa_recs), "semanticscholar": len(s2_recs),
    }
    all_recs = pm_recs + ep_recs + oa_recs + s2_recs

    with DedupLog(tmp / "dedup.jsonl") as log:
        unique = deduplicate(all_recs, log)
    n_merged = len(all_recs) - len(unique)

    conn = connect(tmp / "records.db")
    n_new = upsert_records(conn, unique, "offline-run")
    n_total = total_records(conn)
    record_run(conn, "offline-run", "offline", "offline", n_new, n_total)
    conn.close()

    _print_report(per_source, n_merged, len(unique), n_new, n_total)
    return {"per_source": per_source, "n_merged": n_merged,
            "n_unique": len(unique), "n_new": n_new, "n_total": n_total}


def run_live(days: int) -> dict:
    from .run import run_search
    since = (date.today() - timedelta(days=days)).isoformat()
    summary = run_search(since=since)
    _print_report(summary["per_source"], summary["n_merged"],
                  summary["n_unique_this_run"], summary["n_new"], summary["n_total"])
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="search.smoke")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="run against fixtures, no network")
    mode.add_argument("--live", action="store_true", help="run against real APIs")
    p.add_argument("--days", type=int, default=30, help="live window size (default 30)")
    args = p.parse_args(argv)
    if args.offline:
        run_offline()
    else:
        run_live(args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
