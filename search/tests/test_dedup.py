import json

from search.dedup import DedupLog, deduplicate
from search.model import Record


def _dedup(records, tmp_path):
    log_path = tmp_path / "dedup.jsonl"
    with DedupLog(log_path) as log:
        unique = deduplicate(records, log)
    entries = [json.loads(l) for l in log_path.read_text().splitlines()]
    return unique, entries


def test_doi_exact_merge(tmp_path):
    recs = [
        Record(doi="10.1/x", title="A", authors="Smith J", year=2024, source="pubmed"),
        Record(doi="https://doi.org/10.1/X", title="A", authors="Smith J", year=2024, source="openalex"),
    ]
    unique, entries = _dedup(recs, tmp_path)
    assert len(unique) == 1
    assert set(unique[0].sources) == {"pubmed", "openalex"}
    assert entries[0]["reason"] == "doi_exact"


def test_fuzzy_merge_same_author_year_similar_title(tmp_path):
    recs = [
        Record(title="Income-to-needs and subcortical brain volume in adolescents",
               authors="Garcia M", year=2023, source="pubmed"),
        Record(title="Income to needs and subcortical brain volumes in adolescents",
               authors="Maria Garcia", year=2023, source="semanticscholar"),
    ]
    unique, entries = _dedup(recs, tmp_path)
    assert len(unique) == 1
    assert entries[0]["reason"] == "fuzzy_title_author_year"
    assert entries[0]["score"] >= 92


def test_no_merge_different_year(tmp_path):
    recs = [
        Record(title="Same exact title here", authors="Lee H", year=2020, source="a"),
        Record(title="Same exact title here", authors="Lee H", year=2021, source="b"),
    ]
    unique, entries = _dedup(recs, tmp_path)
    assert len(unique) == 2
    assert entries == []


def test_no_merge_different_author(tmp_path):
    recs = [
        Record(title="Same exact title here", authors="Lee H", year=2020, source="a"),
        Record(title="Same exact title here", authors="Kim S", year=2020, source="b"),
    ]
    unique, _ = _dedup(recs, tmp_path)
    assert len(unique) == 2


def test_conflicting_dois_do_not_fuzzy_merge(tmp_path):
    # two different DOIs never collapse even with identical metadata
    recs = [
        Record(doi="10.1/aaa", title="T", authors="Ng T", year=2025, source="a"),
        Record(doi="10.1/bbb", title="T", authors="Ng T", year=2025, source="b"),
    ]
    unique, _ = _dedup(recs, tmp_path)
    assert len(unique) == 2
