"""Tests for the curate export/import round-trip and human-decision immutability."""
import csv
import json

from llm.fake import ScriptedClient

from extract import db as edb
from extract.curate import export_csv, import_csv
from extract.reverify import reverify_all
from extract.schema import parse_effect


def _eff(study_id="s1", **over):
    d = {"roi": "hippocampus", "effect_value": 0.2, "effect_type": "r",
         "hemisphere": "left", "ses_construct": "income", "ses_timing": "concurrent",
         "cohort_name": "Springfield Youth Study", "extraction_confidence": 0.6,
         "page_number": "Table 2", "verbatim_quote": "r = 0.2",
         "provenance": {"effect_value": {"page": "Table 2", "quote": "r = 0.2"}}}
    d.update(over)
    return parse_effect(d, study_id=study_id)


def _save(db, **over):
    e = _eff(**over)
    return edb.save_effect(db, e, prompt_hash="h", model_version="m",
                           verified="disputed", needs_review=True,
                           review_reason="disputed: se_or_ci")


def _read(path):
    return list(csv.DictReader(path.open()))


def _write(path, rows, header):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_export_has_key_and_editable_columns(db, tmp_path):
    _save(db)
    out = tmp_path / "edit.csv"
    n = export_csv(db, out)
    assert n == 1
    rows = _read(out)
    assert "effect_key" in rows[0]
    assert "sample_overlap_group" in rows[0]      # cohort assignment folded in
    assert "review_action" in rows[0]


def test_import_applies_edit_and_locks_row(db, tmp_path):
    key = _save(db)
    out = tmp_path / "edit.csv"
    export_csv(db, out)
    rows = _read(out); header = list(rows[0].keys())
    # human supplies the missing CI and assigns the cohort overlap group
    rows[0]["se_or_ci"] = "95% CI, 0.1 to 0.3"
    rows[0]["sample_overlap_group"] = "ABCD"
    rows[0]["review_action"] = "edit"
    _write(out, rows, header)

    res = import_csv(db, out)
    assert res["applied"] == 1
    r = edb.get_effect_row(db, key)
    assert r["se_or_ci"] == "95% CI, 0.1 to 0.3"
    assert r["sample_overlap_group"] == "ABCD"
    assert r["verified"] == "human"
    assert r["human_reviewed"] == 1
    assert r["needs_review"] == 0


def test_import_drop_marks_excluded(db, tmp_path):
    key = _save(db)
    out = tmp_path / "edit.csv"
    export_csv(db, out)
    rows = _read(out); header = list(rows[0].keys())
    rows[0]["review_action"] = "drop"
    _write(out, rows, header)
    import_csv(db, out)
    r = edb.get_effect_row(db, key)
    assert r["excluded"] == 1 and r["human_reviewed"] == 1


def test_blank_action_rows_are_skipped(db, tmp_path):
    key = _save(db)
    out = tmp_path / "edit.csv"
    export_csv(db, out)          # review_action left blank
    res = import_csv(db, out)
    assert res["skipped"] == 1 and res["applied"] == 0
    assert edb.get_effect_row(db, key)["human_reviewed"] == 0


def test_human_reviewed_row_survives_reverify(db, tmp_path):
    key = _save(db)
    out = tmp_path / "edit.csv"; export_csv(db, out)
    rows = _read(out); header = list(rows[0].keys())
    rows[0]["review_action"] = "keep"; rows[0]["se_or_ci"] = "SE 0.05"
    _write(out, rows, header)
    import_csv(db, out)

    # a later reverify that would dispute everything must not touch the human row
    disputer = ScriptedClient(responder=lambda p, s, m: json.dumps(
        {"verdicts": [{"index": i, "verdict": "dispute", "confidence": 0.9}
                      for i in range(10)]}))
    reverify_all(db, disputer)
    r = edb.get_effect_row(db, key)
    assert r["verified"] == "human" and r["needs_review"] == 0
    assert r["se_or_ci"] == "SE 0.05"


def test_migration_adds_columns_to_old_table(tmp_path):
    # simulate a pre-review effects table, then connect() must add the columns.
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE effects (effect_key TEXT PRIMARY KEY, study_id TEXT, "
              "roi TEXT, extraction_confidence REAL, created_at TEXT)")
    c.commit(); c.close()
    conn = edb.connect(p)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(effects)")}
    assert {"human_reviewed", "excluded", "review_notes"} <= cols
