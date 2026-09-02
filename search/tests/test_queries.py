from pathlib import Path

from search.queries import (
    Query, build_queries, format_for, load_spec, query_set_hash,
)

REQUIRED_BRAIN = {"hippocamp*", "amygdala", "subcortical volume",
                  "FreeSurfer", "FSL FIRST", "voxel-based morphometry"}
REQUIRED_SES = {"socioeconomic status", "poverty", "income", "income-to-needs",
                "parental education", "neighborhood disadvantage",
                "material deprivation", "area deprivation index", "social class",
                "financial hardship"}


def test_default_spec_contains_all_required_terms():
    spec = load_spec()
    assert REQUIRED_BRAIN.issubset(set(spec["brain"]))
    assert REQUIRED_SES.issubset(set(spec["ses"]))
    assert spec["method"]  # non-empty method axis


def test_build_queries_is_full_cross_product():
    spec = load_spec()
    queries = build_queries(spec)
    assert len(queries) == len(spec["brain"]) * len(spec["ses"]) * len(spec["method"])


def test_query_set_hash_stable_and_order_independent():
    spec = load_spec()
    q = build_queries(spec)
    assert query_set_hash(q) == query_set_hash(list(reversed(q)))


def test_pubmed_dialect_tags_and_wildcard():
    q = Query("hippocamp*", "poverty", "structural MRI")
    s = format_for("pubmed", q)
    assert s == 'hippocamp*[tiab] AND "poverty"[tiab] AND "structural MRI"[tiab]'
    # wildcard term must NOT be quoted (quotes disable truncation)
    assert '"hippocamp*"' not in s


def test_europepmc_dialect_boolean_no_field_tag():
    q = Query("amygdala", "income", "gray matter volume")
    s = format_for("europepmc", q)
    assert s == '"amygdala" AND "income" AND "gray matter volume"'


def test_keyword_dialect_strips_wildcard():
    q = Query("hippocamp*", "poverty", "structural MRI")
    for src in ("openalex", "semanticscholar"):
        s = format_for(src, q)
        assert s == "hippocamp poverty structural MRI"
        assert "*" not in s


def test_min_spec_loads(fixtures_dir: Path):
    spec = load_spec(fixtures_dir / "queries_min.yaml")
    assert build_queries(spec) == [Query("hippocamp*", "poverty", "structural MRI")]
