from extract.resolve import resolve_pmcids, _norm_doi


RECORDS = [
    {"id": "doi:10.1/a", "pmid": "111", "doi": "10.1/a"},
    {"id": "doi:10.1/b", "pmid": "222", "doi": "10.1/b"},
    {"id": "doi:10.1/c", "pmid": None, "doi": "10.1/c"},   # DOI-only
    {"id": "doi:10.1/d", "pmid": "444", "doi": "10.1/d"},   # not in PMC
]


def _fake_fetch(ids):
    # converter echoes pmid/doi and returns pmcid only for those in PMC
    table = {
        "111": {"pmid": "111", "doi": "10.1/a", "pmcid": "PMC111"},
        "222": {"pmid": "222", "doi": "10.1/b", "pmcid": "PMC222"},
        "10.1/c": {"doi": "10.1/c", "pmcid": "PMC333"},
        "444": {"pmid": "444", "errmsg": "invalid article id"},
    }
    return {"status": "ok", "records": [table[i] for i in ids if i in table]}


def test_resolves_pmid_and_doi():
    got = resolve_pmcids(RECORDS, _fake_fetch)
    assert got["doi:10.1/a"] == "PMC111"
    assert got["doi:10.1/b"] == "PMC222"
    assert got["doi:10.1/c"] == "PMC333"      # resolved via DOI


def test_absent_when_not_in_pmc():
    got = resolve_pmcids(RECORDS, _fake_fetch)
    assert "doi:10.1/d" not in got            # no pmcid returned -> not mapped


def test_batching_calls_in_chunks():
    calls = []

    def counting_fetch(ids):
        calls.append(list(ids))
        return {"records": []}

    resolve_pmcids(RECORDS, counting_fetch, chunk=2)
    assert all(len(c) <= 2 for c in calls)


def test_pmids_and_dois_sent_in_separate_requests():
    # a request must be single-type: PMIDs together, DOIs together, never mixed.
    calls = []

    def spy(ids):
        calls.append(list(ids))
        return {"records": []}

    resolve_pmcids(RECORDS, spy, chunk=50)
    for c in calls:
        looks_doi = ["/" in i for i in c]
        assert all(looks_doi) or not any(looks_doi), f"mixed-type batch: {c}"


def test_norm_doi():
    assert _norm_doi("https://doi.org/10.1/X") == "10.1/x"
    assert _norm_doi("doi:10.1/Y") == "10.1/y"
    assert _norm_doi(None) is None


def test_converter_url_keeps_commas_literal():
    from extract.resolve import build_converter_url
    url = build_converter_url(["111", "222", "333"], "ses-meta", "me@x.edu")
    assert "ids=111,222,333" in url          # literal commas, not %2C
    assert "%2C" not in url


def test_per_id_fallback_when_batch_returns_nothing():
    # simulate NCBI: any multi-id request returns nothing (the comma bug); only
    # single-id requests resolve. resolve_pmcids must still recover all via fallback.
    table = {"111": "PMC1", "222": "PMC2", "333": "PMC3"}

    def fetch(ids):
        if len(ids) != 1:
            return {"records": []}            # batch fails
        i = ids[0]
        return {"records": [{"pmid": i, "pmcid": table[i]}]} if i in table else {"records": []}

    recs = [{"id": f"s{i}", "pmid": p, "doi": None}
            for i, p in enumerate(["111", "222", "333"])]
    got = resolve_pmcids(recs, fetch, chunk=50)
    assert got == {"s0": "PMC1", "s1": "PMC2", "s2": "PMC3"}


def test_batch_used_when_it_works_no_needless_fallback():
    calls = []

    def fetch(ids):
        calls.append(list(ids))
        return {"records": [{"pmid": i, "pmcid": f"PMC{i}"} for i in ids]}

    recs = [{"id": f"s{i}", "pmid": str(i), "doi": None} for i in range(3)]
    got = resolve_pmcids(recs, fetch, chunk=50)
    assert len(got) == 3
    assert calls == [["0", "1", "2"]]         # one batch, no per-id fallback
