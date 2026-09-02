"""The OpenAlex polite-pool email flows from the environment into the source.

run.py reads OPENALEX_MAILTO and passes it through; unset, the source keeps its
default. We spy on the source constructor to capture the mailto it received.
"""
from pathlib import Path

from search.run import run_search

FIX = Path(__file__).parent / "fixtures"
MIN_QUERIES = FIX / "queries_min.yaml"


def _capture_openalex_mailto(monkeypatch):
    from search.sources import openalex
    seen = {}
    orig_init = openalex.OpenAlex.__init__

    def spy(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        seen["mailto"] = self.mailto

    monkeypatch.setattr(openalex.OpenAlex, "__init__", spy)
    return seen


def _run(tmp_path):
    run_search(since="2026-08-01", until="2026-08-31", queries_path=MIN_QUERIES,
               raw_dir=tmp_path / "raw", db_path=tmp_path / "db.sqlite",
               log_dir=tmp_path)


def test_mailto_from_env_reaches_source(tmp_path, offline_sources, monkeypatch):
    seen = _capture_openalex_mailto(monkeypatch)
    monkeypatch.setenv("OPENALEX_MAILTO", "jamie@pitt.edu")
    _run(tmp_path)
    assert seen["mailto"] == "jamie@pitt.edu"


def test_mailto_defaults_when_env_unset(tmp_path, offline_sources, monkeypatch):
    seen = _capture_openalex_mailto(monkeypatch)
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    _run(tmp_path)
    assert seen["mailto"] == "meta-analysis@example.org"
