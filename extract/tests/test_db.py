import csv

from extract import db as edb
from extract.schema import parse_effect
from extract.tests.conftest import add_included_study


def _eff(study_id="s1", **over):
    d = {"roi": "hippocampus", "effect_value": 0.2, "effect_type": "r",
         "hemisphere": "left", "ses_construct": "income", "ses_timing": "concurrent",
         "extraction_confidence": 0.95, "page_number": "Table 2",
         "verbatim_quote": "r = 0.2",
         "provenance": {"effect_value": {"page": "Table 2", "quote": "r = 0.2"}}}
    d.update(over)
    return parse_effect(d, study_id=study_id)


def test_effect_write_is_idempotent(db):
    e = _eff()
    for _ in range(3):
        edb.save_effect(db, e, prompt_hash="h1", model_version="m")
    n = db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    assert n == 1


def test_changed_prompt_hash_creates_new_row(db):
    e = _eff()
    edb.save_effect(db, e, prompt_hash="h1", model_version="m")
    edb.save_effect(db, e, prompt_hash="h2", model_version="m")
    assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 2


def test_distinct_effects_distinct_rows(db):
    edb.save_effect(db, _eff(hemisphere="left"), prompt_hash="h", model_version="m")
    edb.save_effect(db, _eff(hemisphere="right"), prompt_hash="h", model_version="m")
    assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 2


def test_retrieval_status_upsert(db):
    edb.record_retrieval(db, "s1", "unretrieved", "nothing")
    edb.record_retrieval(db, "s1", "europepmc_xml", "pmc")
    row = db.execute("SELECT status, detail FROM retrieval_status WHERE study_id='s1'").fetchone()
    assert row["status"] == "europepmc_xml"


def test_included_studies_reads_screen_include(db):
    rid = add_included_study(db, "10.1/inc")
    ids = [r["id"] for r in edb.included_studies(db)]
    assert rid in ids


def test_export_effects_csv(db, tmp_path):
    edb.save_effect(db, _eff(), prompt_hash="h", model_version="m")
    out = tmp_path / "effects.csv"
    n = edb.export_effects_csv(db, out)
    assert n == 1
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["roi"] == "hippocampus"
    assert rows[0]["effect_value"] == "0.2"
