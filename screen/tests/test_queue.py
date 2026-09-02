import csv

from screen import db as sdb
from screen.review_queue import build_queue
from screen.schema import Decision
from screen.tests.conftest import add_record


def _seed_queued(db, rid):
    sdb.save_model_decision(db, rid, "A",
                            Decision("include", [], "looks include", 0.6),
                            model="m", model_version="m", prompt_version="pa",
                            prompt_hash="ha")
    sdb.save_model_decision(db, rid, "B",
                            Decision("exclude", ["no_volume_outcome"],
                                     "no volume", 0.7),
                            model="m", model_version="m", prompt_version="pb",
                            prompt_hash="hb")
    sdb.upsert_status(db, rid, "queued", True, "pass_disagreement", "model", False)


def test_queue_has_both_rationales(db, tmp_path):
    rid = add_record(db, "10.1/q", "Income and hippocampus", "some abstract")
    _seed_queued(db, rid)
    out = tmp_path / "q.csv"
    n = build_queue(db, out)
    assert n == 1
    rows = list(csv.DictReader(out.open()))
    row = rows[0]
    assert row["queue_reason"] == "pass_disagreement"
    assert row["pass_a_decision"] == "include"
    assert row["pass_b_decision"] == "exclude"
    assert "no volume" in row["pass_b_reason"]
    assert row["title"] == "Income and hippocampus"


def test_human_resolved_drops_from_queue(db, tmp_path):
    rid = add_record(db, "10.1/r", "t", "a")
    _seed_queued(db, rid)
    sdb.save_human_decision(db, rid, "exclude")
    out = tmp_path / "q.csv"
    assert build_queue(db, out) == 0
