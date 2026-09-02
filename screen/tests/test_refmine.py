from screen import db as sdb
from screen import refmine
from screen.tests.conftest import add_record


TARGET_WORK = {
    "id": "https://openalex.org/WTARGET",
    "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
}
REF_WORKS = {
    "https://openalex.org/W1": {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.9/ref1",
        "title": "Referenced study one",
        "publication_year": 2015,
        "authors": [],
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
        "abstract_inverted_index": {"income": [0], "hippocampus": [1]},
        "primary_location": {"source": {"display_name": "NeuroImage"}},
    },
    "https://openalex.org/W2": {
        "id": "https://openalex.org/W2",
        "doi": "https://doi.org/10.9/ref2",
        "title": "Referenced study two",
        "publication_year": 2018,
        "authorships": [{"author": {"display_name": "Alan Turing"}}],
        "abstract_inverted_index": {"poverty": [0], "amygdala": [1]},
        "primary_location": {"source": {"display_name": "Dev Sci"}},
    },
}


def _fake_fetch(handle):
    if handle == "https://openalex.org/WTARGET":
        return TARGET_WORK
    return REF_WORKS.get(handle)


def test_mine_target_inserts_references(db):
    rid = add_record(db, "10.1/review", "A systematic review",
                     "systematic review of SES and brain",
                     raw={"id": "https://openalex.org/WTARGET"})
    sdb.upsert_status(db, rid, "exclude", False, None, "model", True)

    result = refmine.mine_all(db, _fake_fetch, run_id="refmine:test")
    assert result["targets"] == 1
    assert result["new_records"] == 2

    # the two references are now unscreened records ready for the next run
    unscreened = {r["id"] for r in sdb.unscreened_records(db)}
    assert "doi:10.9/ref1" in unscreened
    assert "doi:10.9/ref2" in unscreened
    # target marked mined -> no longer a target
    assert sdb.refmine_targets(db) == []


def test_mine_target_without_handle_marks_mined_zero(db):
    rid = add_record(db, None, "No-DOI review", "review with no doi or id")
    sdb.upsert_status(db, rid, "exclude", False, None, "model", True)
    result = refmine.mine_all(db, _fake_fetch, run_id="refmine:test")
    assert result["new_records"] == 0
    assert sdb.refmine_targets(db) == []       # marked mined even at zero


def test_referenced_ids_helper():
    assert refmine.referenced_ids(TARGET_WORK) == [
        "https://openalex.org/W1", "https://openalex.org/W2"]
    assert refmine.referenced_ids({"referenced_works": []}) == []
