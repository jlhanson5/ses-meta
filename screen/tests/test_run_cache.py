"""End-to-end screening through the orchestrator with a scripted client.

Proves: two passes per record, correct routing into include/exclude/queued, the
parse-error path becoming uncertain (never a silent drop), and the cache making
a re-run cost zero model calls.
"""
import json

from llm.fake import ScriptedClient

from screen import db as sdb
from screen.run import screen_records
from screen.tests.conftest import add_record


def _responder(prompt, system, model):
    skeptical = "pass B" in prompt or "skeptical" in prompt

    def j(decision, hits, conf):
        return json.dumps({"decision": decision, "criteria_hit": hits,
                           "reason": "r", "confidence": conf})

    if "GARBAGE" in prompt:
        return "this is not json"
    if "ANIMALMARK" in prompt:
        return j("exclude", ["animal"], 0.96)
    if "DISAGREEMARK" in prompt:
        return j("exclude", [], 0.9) if skeptical else j("include", [], 0.9)
    if "INCLUDEMARK" in prompt:
        return j("include", [], 0.9)
    return j("uncertain", [], 0.5)


def _seed(db):
    add_record(db, "10.2/inc", "INCLUDEMARK income hippocampal volume", "assoc")
    add_record(db, "10.2/ani", "ANIMALMARK rats", "rat study")
    add_record(db, "10.2/dis", "DISAGREEMARK borderline", "subcortical")
    add_record(db, "10.2/gar", "GARBAGE title", "abstract")


def test_full_run_routing_and_counts(db):
    _seed(db)
    client = ScriptedClient(responder=_responder)
    report = screen_records(db, client)

    assert report.screened == 4
    assert report.llm_calls == 8            # 2 passes x 4 records
    assert report.cached == 0

    counts = sdb.status_counts(db)
    assert counts.get("include") == 1
    assert counts.get("exclude") == 1
    assert counts.get("queued") == 2        # disagreement + parse-error uncertain


def test_parse_error_becomes_queued_not_dropped(db):
    add_record(db, "10.2/gar", "GARBAGE title", "abstract")
    client = ScriptedClient(responder=_responder)
    screen_records(db, client)
    row = db.execute("SELECT final_decision, queue_reason FROM screen_status "
                     "WHERE record_id='doi:10.2/gar'").fetchone()
    assert row["final_decision"] == "queued"
    assert row["queue_reason"] == "model_uncertain"


def test_rerun_screens_nothing_because_status_exists(db):
    # once screened, records carry a status row and are not re-visited at all:
    # the cheapest possible re-run, zero model calls.
    _seed(db)
    client = ScriptedClient(responder=_responder)
    screen_records(db, client)
    calls_after_first = client.call_count

    report2 = screen_records(db, client)
    assert report2.screened == 0
    assert report2.llm_calls == 0
    assert client.call_count == calls_after_first


def test_decision_cache_serves_without_model_calls(db):
    # if a record is re-visited (status cleared, e.g. after a refmine re-add),
    # the (record_id, pass, prompt_hash, model) cache answers with zero calls.
    _seed(db)
    client = ScriptedClient(responder=_responder)
    screen_records(db, client)
    calls_after_first = client.call_count

    db.execute("DELETE FROM screen_status")
    db.commit()
    report2 = screen_records(db, client)
    assert report2.screened == 4
    assert report2.llm_calls == 0
    assert report2.cached == 8
    assert client.call_count == calls_after_first     # no new model calls


def test_no_abstract_routes_to_queue_without_model_calls(db):
    # a title-only record must never be model-excluded: it goes to the queue and
    # spends zero calls.
    add_record(db, "10.4/na", "SES and hippocampal volume (title only)", "")
    client = ScriptedClient(responder=_responder)
    report = screen_records(db, client)

    assert report.no_abstract == 1
    assert report.llm_calls == 0
    assert client.call_count == 0
    row = db.execute("SELECT final_decision, queue_reason, resolved_by "
                     "FROM screen_status WHERE record_id='doi:10.4/na'").fetchone()
    assert row["final_decision"] == "queued"
    assert row["queue_reason"] == "no_abstract"
    assert row["resolved_by"] != "human"


def test_whitespace_abstract_treated_as_missing(db):
    add_record(db, "10.4/ws", "title", "   \n  ")
    client = ScriptedClient(responder=_responder)
    report = screen_records(db, client)
    assert report.no_abstract == 1
    assert report.llm_calls == 0


def test_leaked_tag_is_normalized_in_stored_decision(db):
    # model emits an off-schema tag; the stored decision must carry the canonical one
    def responder(prompt, system, model):
        return json.dumps({"decision": "exclude", "criteria_hit": ["not_a_study"],
                           "reason": "editorial", "confidence": 0.95})
    add_record(db, "10.4/leak", "some editorial", "not a real study")
    screen_records(db, ScriptedClient(responder=responder))
    row = db.execute("SELECT criteria_hit FROM screen_decisions "
                     "WHERE record_id='doi:10.4/leak' AND pass_name='A'").fetchone()
    assert json.loads(row["criteria_hit"]) == ["wrong_pub_type"]


def test_progress_callback_fires_per_record(db):
    _seed(db)
    events = []
    screen_records(db, ScriptedClient(responder=_responder),
                   on_progress=events.append)
    assert len(events) == 4
    assert [e["index"] for e in events] == [1, 2, 3, 4]
    assert all(e["total"] == 4 for e in events)
