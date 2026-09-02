"""End-to-end pipeline over fixtures: parse -> dedup -> db, run twice.

Proves requirement 6 (re-running the same window creates no duplicate rows) and
that the raw cache prevents a second network hit. Uses the single-triple
queries_min.yaml so per-source counts equal the fixture sizes exactly.
"""
from pathlib import Path

from search.run import run_search

FIX = Path(__file__).parent / "fixtures"
MIN_QUERIES = FIX / "queries_min.yaml"


def test_full_pipeline_counts_and_idempotency(tmp_path, offline_sources):
    raw = tmp_path / "raw"
    db = tmp_path / "records.db"

    # --- run 1 ---
    s1 = run_search(since="2026-08-01", until="2026-08-31",
                    queries_path=MIN_QUERIES, raw_dir=raw, db_path=db, log_dir=tmp_path)

    assert s1["per_source"] == {
        "pubmed": 3, "europepmc": 2, "openalex": 2, "semanticscholar": 2,
    }
    assert s1["n_raw"] == 9
    assert s1["n_merged"] == 4          # A x2 doi, B x1 doi, C x1 fuzzy
    assert s1["n_unique_this_run"] == 5
    assert s1["n_new"] == 5
    assert s1["n_total"] == 5

    fetch_calls_after_run1 = dict(offline_sources)
    assert all(v == 1 for v in fetch_calls_after_run1.values())

    # --- run 2, identical window ---
    s2 = run_search(since="2026-08-01", until="2026-08-31",
                    queries_path=MIN_QUERIES, raw_dir=raw, db_path=db, log_dir=tmp_path)

    assert s2["n_new"] == 0             # nothing new
    assert s2["n_total"] == 5           # no duplicate rows

    # cache prevented any new network hit (fetch counts unchanged)
    assert dict(offline_sources) == fetch_calls_after_run1


def test_raw_files_written_one_per_source(tmp_path, offline_sources):
    raw = tmp_path / "raw"
    db = tmp_path / "records.db"
    run_search(since="2026-08-01", until="2026-08-31",
               queries_path=MIN_QUERIES, raw_dir=raw, db_path=db, log_dir=tmp_path)
    files = sorted(p.name for p in raw.glob("*.json"))
    # one triple -> one query -> one raw JSON per source
    assert len(files) == 4
    assert any("pubmed" in f for f in files)
    assert any("europepmc" in f for f in files)
    assert any("openalex" in f for f in files)
    assert any("semanticscholar" in f for f in files)


def test_runs_row_recorded(tmp_path, offline_sources):
    import sqlite3
    raw = tmp_path / "raw"
    db = tmp_path / "records.db"
    run_search(since="2026-08-01", until="2026-08-31",
               queries_path=MIN_QUERIES, raw_dir=raw, db_path=db, log_dir=tmp_path)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT n_new, n_total FROM runs").fetchone()
    assert row == (5, 5)
