import pytest

from screen import db as sdb
from screen.schema import Decision
from screen.tests.conftest import add_record


def _dec(decision="exclude", conf=0.9, hits=None):
    return Decision(decision=decision, criteria_hit=hits or [], reason="r",
                    confidence=conf)


def test_model_decision_is_cache_idempotent(db):
    rid = add_record(db, "10.1/a", "t", "a")
    for _ in range(3):
        sdb.save_model_decision(db, rid, "A", _dec(), model="m",
                                model_version="m", prompt_version="p",
                                prompt_hash="h1")
    n = db.execute("SELECT COUNT(*) FROM screen_decisions "
                   "WHERE reviewer='model'").fetchone()[0]
    assert n == 1


def test_get_model_decision_roundtrip(db):
    rid = add_record(db, "10.1/b", "t", "a")
    sdb.save_model_decision(db, rid, "A", _dec("include", 0.8), model="m",
                            model_version="m", prompt_version="p", prompt_hash="h1")
    got = sdb.get_model_decision(db, rid, "A", "h1", "m")
    assert got is not None and got.decision == "include"
    # different prompt hash is a cache miss
    assert sdb.get_model_decision(db, rid, "A", "h2", "m") is None


def test_new_prompt_hash_adds_row_not_overwrite(db):
    rid = add_record(db, "10.1/c", "t", "a")
    sdb.save_model_decision(db, rid, "A", _dec(), model="m", model_version="m",
                            prompt_version="p1", prompt_hash="h1")
    sdb.save_model_decision(db, rid, "A", _dec("include"), model="m",
                            model_version="m", prompt_version="p2", prompt_hash="h2")
    n = db.execute("SELECT COUNT(*) FROM screen_decisions").fetchone()[0]
    assert n == 2


def test_human_decision_final_and_no_overwrite(db):
    rid = add_record(db, "10.1/d", "t", "a")
    sdb.save_human_decision(db, rid, "include", "looks good")
    assert sdb.get_human_decision(db, rid).decision == "include"
    with pytest.raises(ValueError, match="refusing to overwrite"):
        sdb.save_human_decision(db, rid, "exclude")


def test_model_run_never_clobbers_human(db):
    rid = add_record(db, "10.1/e", "t", "a")
    sdb.save_human_decision(db, rid, "include")
    # a later model roll-up tries to mark it excluded
    sdb.upsert_status(db, rid, "exclude", False, None, "model", False)
    row = db.execute("SELECT final_decision, resolved_by FROM screen_status "
                     "WHERE record_id=?", (rid,)).fetchone()
    assert row["final_decision"] == "include" and row["resolved_by"] == "human"


def test_unscreened_excludes_records_with_status(db):
    r1 = add_record(db, "10.1/f", "t1", "a1")
    r2 = add_record(db, "10.1/g", "t2", "a2")
    sdb.upsert_status(db, r1, "exclude", False, None, "model", False)
    remaining = [r["id"] for r in sdb.unscreened_records(db)]
    assert r2 in remaining and r1 not in remaining


def test_refmine_targets_and_mark_mined(db):
    rid = add_record(db, "10.1/h", "review", "systematic review")
    sdb.upsert_status(db, rid, "exclude", False, None, "model", True)
    assert sdb.refmine_targets(db) == [rid]
    sdb.mark_mined(db, rid, 12)
    assert sdb.refmine_targets(db) == []      # mined targets drop out
