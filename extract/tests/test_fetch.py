from extract.fetch import retrieve_one, unretrievable_report
from extract.document import Document, Segment


def _doc(sid, src):
    return Document(sid, src, [Segment("p.1", "text")])


def _fetchers(xml=None, unpaywall=None, pdf=None):
    return dict(
        fetch_xml=lambda pmcid: xml,
        fetch_unpaywall=lambda doi: unpaywall,
        fetch_pdf_bytes=lambda url: pdf,
        pdf_to_doc=lambda path, sid, src: _doc(sid, src),
    )


def test_prefers_europepmc_xml(tmp_path):
    rec = {"id": "s1", "doi": "10.1/x", "pmid": "1",
           "raw_json": '{"pmcid": "PMC1"}'}
    r = retrieve_one(rec, **_fetchers(
        xml="<article><sec><title>Results</title><p>r=0.2</p></sec></article>"))
    assert r.status == "europepmc_xml" and r.ok


def test_falls_back_to_unpaywall_pdf(tmp_path):
    rec = {"id": "s2", "doi": "10.1/y", "pmid": None}
    r = retrieve_one(rec, **_fetchers(xml=None, unpaywall="http://x/y.pdf",
                                      pdf=b"%PDF-1.4 fake"), cache_dir=tmp_path)
    assert r.status == "unpaywall_pdf" and r.ok


def test_falls_back_to_manual_drop(tmp_path):
    manual = tmp_path / "manual"
    manual.mkdir()
    (manual / "s3.pdf").write_bytes(b"%PDF fake")
    rec = {"id": "s3", "doi": None, "pmid": None}
    f = _fetchers(xml=None, unpaywall=None, pdf=None)
    r = retrieve_one(rec, manual_dir=manual, **f)
    assert r.status == "manual_pdf" and r.ok


def test_unretrieved_when_nothing_available(tmp_path):
    rec = {"id": "s4", "doi": None, "pmid": None}
    r = retrieve_one(rec, manual_dir=tmp_path / "none", **_fetchers())
    assert r.status == "unretrieved" and not r.ok
    rep = unretrievable_report([r])
    assert rep == [{"study_id": "s4", "detail": r.detail}]
