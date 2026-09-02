"""Shared fixtures for screen tests."""
import json

import pytest

from search.db import connect as connect_records, upsert_records
from search.model import Record

from screen import db as sdb


@pytest.fixture
def db(tmp_path):
    """A records.db with both search and screen tables, empty of records."""
    path = tmp_path / "records.db"
    conn = connect_records(path)      # records + runs
    sdb.connect(path)                   # screen tables in the same file
    return conn


def add_record(conn, doi, title, abstract, *, year=2020, journal="J",
               raw=None, run_id="test-run"):
    rec = Record(doi=doi, title=title, abstract=abstract, authors="Smith J",
                 year=year, journal=journal, source="test",
                 raw_json=json.dumps(raw) if raw is not None else None)
    upsert_records(conn, [rec], run_id)
    return rec.id
