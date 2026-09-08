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
    assert len(calls) == 2                     # 3 sendable ids (+1 pmid) -> 2 chunks
    assert all(len(c) <= 2 for c in calls)


def test_norm_doi():
    assert _norm_doi("https://doi.org/10.1/X") == "10.1/x"
    assert _norm_doi("doi:10.1/Y") == "10.1/y"
    assert _norm_doi(None) is None
