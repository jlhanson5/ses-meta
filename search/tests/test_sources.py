"""Parse-level tests for each source (no network).

Each test feeds a fixture payload straight into the source's `_parse` and checks
the normalized records. The HTTP layer itself is covered by test_idempotency
(cache) and test_http.
"""
from pathlib import Path

import pytest

from search.sources import EuropePMC, OpenAlex, PubMed, SemanticScholar
from search.sources.openalex import reconstruct_abstract

from .conftest import load_json, load_text


def make(cls, tmp_path):
    return cls(raw_dir=tmp_path, run_date="2026-09-02")


def test_pubmed_parse(tmp_path):
    src = make(PubMed, tmp_path)
    payload = {"efetch_xml": load_text("pubmed_efetch.xml")}
    recs = src._parse(payload)
    assert len(recs) == 3
    a = [r for r in recs if r.pmid == "30000001"][0]
    assert a.doi == "10.1000/aaa"
    assert a.year == 2024
    assert a.authors.startswith("Smith J")
    assert a.journal == "Developmental Cognitive Neuroscience"
    # paper C has no DOI
    c = [r for r in recs if r.pmid == "30000003"][0]
    assert c.doi is None


def test_europepmc_parse(tmp_path):
    src = make(EuropePMC, tmp_path)
    recs = src._parse(load_json("europepmc.json"))
    assert len(recs) == 2
    a = [r for r in recs if r.doi == "10.1000/aaa"][0]
    assert a.pmid == "30000001"
    assert a.year == 2024
    assert "Smith John" in a.authors


def test_openalex_parse_and_abstract(tmp_path):
    src = make(OpenAlex, tmp_path)
    recs = src._parse(load_json("openalex.json"))
    assert len(recs) == 2
    a = [r for r in recs if r.doi == "10.1000/aaa"][0]
    assert a.pmid == "30000001"          # extracted from ids.pmid URL
    assert a.abstract.startswith("Hippocampal volume")
    assert a.journal == "Developmental Cognitive Neuroscience"


def test_semanticscholar_parse(tmp_path):
    src = make(SemanticScholar, tmp_path)
    recs = src._parse(load_json("semanticscholar.json"))
    assert len(recs) == 2
    b = [r for r in recs if r.doi == "10.1000/bbb"][0]
    assert b.pmid == "30000002"
    c = [r for r in recs if r.doi is None][0]
    assert c.year == 2023
    assert "Garcia" in c.authors


def test_reconstruct_abstract_orders_by_position():
    inv = {"world": [1], "hello": [0]}
    assert reconstruct_abstract(inv) == "hello world"
    assert reconstruct_abstract(None) is None
