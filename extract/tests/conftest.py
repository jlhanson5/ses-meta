"""Shared fixtures for extract tests."""
import json

import pytest

from search.db import connect as connect_records, upsert_records
from search.model import Record
from screen.db import connect as sconnect, upsert_status

from extract import db as edb


@pytest.fixture
def db(tmp_path):
    """records + screen + effects tables in one file."""
    path = tmp_path / "records.db"
    conn = connect_records(path)
    sconnect(path)
    edb.connect(path)
    return conn


def add_included_study(conn, sid_doi, title="t", abstract="a", raw=None,
                       year=2020):
    rec = Record(doi=sid_doi, title=title, abstract=abstract, authors="Smith J",
                 year=year, journal="J", source="test",
                 raw_json=json.dumps(raw) if raw is not None else None)
    upsert_records(conn, [rec], "test-run")
    upsert_status(conn, rec.id, "include", False, None, "model", False)
    return rec.id
