from pathlib import Path

from search.queries import (
    Query, build_queries, format_for, load_spec, query_set_hash,
)

REQUIRED_BRAIN = {"hippocamp*", "amygdala"}
REQUIRED_SES = {"socioeconomic status", "poverty", "income", "income-to-needs",
                "parental education", "neighborhood disadvantage",
                "neighborhood deprivation", "material deprivation",
                "area deprivation index", "social class", "financial hardship",
                "social benefits", "welfare receipt"}


def test_default_spec_contains_all_required_terms():
    spec = load_spec()
    assert REQUIRED_BRAIN.issubset(set(spec["brain"]))
    assert REQUIRED_SES.issubset(set(spec["ses"]))


def test_default_spec_is_region_and_ses_only():
    # the outcome axis is the two regions only; no method axis
    spec = load_spec()
    assert set(spec["brain"]) == REQUIRED_BRAIN
    assert not spec.get("method")


def test_build_queries_cross_product():
    spec = load_spec()
    queries = build_queries(spec)
    methods = spec.get("method") or [""]
    assert len(queries) == len(spec["brain"]) * len(spec["ses"]) * len(methods)


def test_region_and_ses_queries_have_two_terms():
    spec = load_spec()
    for q in build_queries(spec):
        assert len(q.terms) == 2                    # region AND ses, no method


def test_query_set_hash_stable_and_order_independent():
    spec = load_spec()
    q = build_queries(spec)
    assert query_set_hash(q) == query_set_hash(list(reversed(q)))


def test_two_term_pubmed_dialect():
    q = Query("hippocamp*", "poverty")               # no method
    s = format_for("pubmed", q)
    assert s == 'hippocamp*[tiab] AND "poverty"[tiab]'
    assert '"hippocamp*"' not in s


def test_two_term_keyword_dialect():
    q = Query("amygdala", "income")
    assert format_for("openalex", q) == "amygdala income"


# --- backward compatibility: a spec WITH a method block still works ---

def test_three_term_pubmed_dialect_still_supported():
    q = Query("hippocamp*", "poverty", "structural MRI")
    s = format_for("pubmed", q)
    assert s == 'hippocamp*[tiab] AND "poverty"[tiab] AND "structural MRI"[tiab]'
    assert '"hippocamp*"' not in s


def test_three_term_europepmc_dialect_still_supported():
    q = Query("amygdala", "income", "gray matter volume")
    s = format_for("europepmc", q)
    assert s == '"amygdala" AND "income" AND "gray matter volume"'


def test_three_term_keyword_strips_wildcard():
    q = Query("hippocamp*", "poverty", "structural MRI")
    for src in ("openalex", "semanticscholar"):
        s = format_for(src, q)
        assert s == "hippocamp poverty structural MRI"
        assert "*" not in s


def test_min_spec_with_method_loads(fixtures_dir: Path):
    spec = load_spec(fixtures_dir / "queries_min.yaml")
    assert build_queries(spec) == [Query("hippocamp*", "poverty", "structural MRI")]
