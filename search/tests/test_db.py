from search.db import (
    connect, record_run, total_records, upsert_records, last_run_date,
)
from search.model import Record


def test_schema_has_required_columns(tmp_path):
    conn = connect(tmp_path / "records.db")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}
    assert {"id", "doi", "pmid", "title", "abstract", "authors", "year",
            "journal", "source", "first_seen_run", "raw_json"} <= cols
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    assert {"run_id", "timestamp", "query_hash", "n_new", "n_total"} <= rcols


def test_upsert_is_idempotent_and_counts_new(tmp_path):
    conn = connect(tmp_path / "records.db")
    recs = [
        Record(doi="10.1/a", title="A", authors="Smith J", year=2024, source="pubmed"),
        Record(doi="10.1/b", title="B", authors="Doe A", year=2023, source="openalex"),
    ]
    assert upsert_records(conn, recs, "run-1") == 2
    assert total_records(conn) == 2
    # re-insert same records -> zero new, no duplicate rows
    assert upsert_records(conn, recs, "run-2") == 0
    assert total_records(conn) == 2


def test_first_seen_run_is_preserved_across_reruns(tmp_path):
    conn = connect(tmp_path / "records.db")
    rec = Record(doi="10.1/a", title="A", authors="Smith J", year=2024, source="pubmed")
    upsert_records(conn, [rec], "run-1")
    upsert_records(conn, [rec], "run-2")
    seen = conn.execute("SELECT first_seen_run FROM records WHERE id=?",
                        (rec.id,)).fetchone()[0]
    assert seen == "run-1"


def test_new_record_in_later_run_gets_that_run(tmp_path):
    conn = connect(tmp_path / "records.db")
    upsert_records(conn, [Record(doi="10.1/a", title="A", source="pubmed")], "run-1")
    upsert_records(conn, [Record(doi="10.1/b", title="B", source="pubmed")], "run-2")
    rows = dict(conn.execute("SELECT id, first_seen_run FROM records"))
    assert rows["doi:10.1/a"] == "run-1"
    assert rows["doi:10.1/b"] == "run-2"


def test_last_run_date_tracks_latest(tmp_path):
    conn = connect(tmp_path / "records.db")
    record_run(conn, "r1", "2026-08-01T00:00:00+00:00", "h", 1, 1)
    record_run(conn, "r2", "2026-08-15T00:00:00+00:00", "h", 2, 3)
    assert last_run_date(conn) == "2026-08-15"
