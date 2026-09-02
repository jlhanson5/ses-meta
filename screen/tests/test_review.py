from screen import db as sdb
from screen.review import review_loop
from screen.schema import Decision
from screen.tests.conftest import add_record


def _queue(db, doi):
    rid = add_record(db, doi, "t", "a")
    sdb.save_model_decision(db, rid, "A", Decision("include", [], "r", 0.6),
                            model="m", model_version="m", prompt_version="pa",
                            prompt_hash="ha")
    sdb.save_model_decision(db, rid, "B", Decision("exclude", [], "r", 0.7),
                            model="m", model_version="m", prompt_version="pb",
                            prompt_hash="hb")
    sdb.upsert_status(db, rid, "queued", True, "pass_disagreement", "model", False)
    return rid


def _scripted_input(keys):
    it = iter(keys)
    return lambda _prompt: next(it)


def test_keystrokes_write_human_decisions(db):
    r1 = _queue(db, "10.3/a")
    r2 = _queue(db, "10.3/b")
    stats = review_loop(db, prompt_fn=_scripted_input(["i", "e"]), out=lambda *a: None)
    assert stats["reviewed"] == 2
    assert sdb.get_human_decision(db, r1).decision == "include"
    assert sdb.get_human_decision(db, r2).decision == "exclude"
    # both leave the queue
    assert sdb.queued_records(db) == []


def test_quit_stops_and_skips_rest(db):
    _queue(db, "10.3/c")
    _queue(db, "10.3/d")
    stats = review_loop(db, prompt_fn=_scripted_input(["q"]), out=lambda *a: None)
    assert stats["quit"] is True
    assert stats["reviewed"] == 0


def test_skip_leaves_record_queued(db):
    rid = _queue(db, "10.3/e")
    stats = review_loop(db, prompt_fn=_scripted_input(["s"]), out=lambda *a: None)
    assert stats["skipped"] == 1
    assert [r["record_id"] for r in sdb.queued_records(db)] == [rid]


def test_human_resolved_record_leaves_queue(db):
    rid = _queue(db, "10.3/f")
    sdb.save_human_decision(db, rid, "include")
    # a human decision flips status to resolved_by='human', so it is no longer
    # queued and the loop never re-asks it.
    stats = review_loop(db, prompt_fn=_scripted_input([]), out=lambda *a: None)
    assert stats["reviewed"] == 0
    assert sdb.queued_records(db) == []


def test_guard_skips_human_row_even_if_still_flagged_queued(db):
    # defensive: if a human row exists but the status row is somehow still
    # queued+model, the loop must skip it rather than overwrite the human call.
    rid = _queue(db, "10.3/g")
    sdb.save_human_decision(db, rid, "include")
    db.execute("UPDATE screen_status SET routed_to_queue=1, resolved_by='model' "
               "WHERE record_id=?", (rid,))
    db.commit()
    stats = review_loop(db, prompt_fn=_scripted_input([]), out=lambda *a: None)
    assert stats["already_human"] == 1
    assert stats["reviewed"] == 0
