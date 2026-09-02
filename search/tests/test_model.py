from search.model import (
    Record, compute_id, first_author_last, normalize_doi, normalize_title,
)


def test_normalize_doi_strips_resolver_and_lowercases():
    assert normalize_doi("https://doi.org/10.1000/AAA") == "10.1000/aaa"
    assert normalize_doi("doi:10.1000/aaa") == "10.1000/aaa"
    assert normalize_doi("  10.1000/AAA  ") == "10.1000/aaa"
    assert normalize_doi("") is None
    assert normalize_doi(None) is None


def test_normalize_title_folds_accents_and_punct():
    a = normalize_title("Hippocampal Volume & Poverty: A Cohort")
    b = normalize_title("hippocampal volume  poverty a cohort")
    assert a == b == "hippocampal volume poverty a cohort"


def test_first_author_last_variants():
    assert first_author_last("Smith J; Doe A") == "smith"
    assert first_author_last("John Smith") == "smith"
    assert first_author_last("Smith, John") == "smith"
    assert first_author_last("Garcia M") == "garcia"
    assert first_author_last("") == ""


def test_compute_id_prefers_doi_and_is_deterministic():
    i1 = compute_id("10.1000/aaa", "T", "Smith J", 2024)
    i2 = compute_id("https://doi.org/10.1000/AAA", "different", "Other", 1999)
    assert i1 == i2 == "doi:10.1000/aaa"


def test_compute_id_falls_back_to_hash_without_doi():
    i1 = compute_id(None, "Income to needs", "Garcia M", 2023)
    i2 = compute_id(None, "income to needs", "garcia", 2023)
    assert i1 == i2
    assert i1.startswith("k:")


def test_record_accumulates_source_tag():
    r = Record(title="t", source="pubmed")
    assert r.sources == ["pubmed"]
    row = r.to_row("run-1")
    assert row["first_seen_run"] == "run-1"
    assert row["source"] == "pubmed"
