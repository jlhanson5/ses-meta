"""Shared test fixtures.

The `offline_sources` fixture patches each source's `_fetch` to return a canned
payload loaded from tests/fixtures, so the full pipeline (cache -> parse -> dedup
-> db) runs with zero network. It also counts fetch calls so idempotency tests
can assert the cache prevented a second network hit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict:
    with (FIX / name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIX


@pytest.fixture
def pubmed_payload() -> dict:
    return {"esearch": load_json("pubmed.json")["esearch"],
            "efetch_xml": load_text("pubmed_efetch.xml")}


@pytest.fixture
def offline_sources(monkeypatch, pubmed_payload):
    """Patch all four source `_fetch` methods to return fixtures. Returns a call counter."""
    from search.sources import pubmed, europepmc, openalex, semanticscholar

    calls = {"pubmed": 0, "europepmc": 0, "openalex": 0, "semanticscholar": 0}

    def mk(name, payload):
        def _fetch(self, query, date_from, date_to):
            calls[name] += 1
            return payload
        return _fetch

    monkeypatch.setattr(pubmed.PubMed, "_fetch", mk("pubmed", pubmed_payload))
    monkeypatch.setattr(europepmc.EuropePMC, "_fetch", mk("europepmc", load_json("europepmc.json")))
    monkeypatch.setattr(openalex.OpenAlex, "_fetch", mk("openalex", load_json("openalex.json")))
    monkeypatch.setattr(semanticscholar.SemanticScholar, "_fetch",
                        mk("semanticscholar", load_json("semanticscholar.json")))
    return calls
