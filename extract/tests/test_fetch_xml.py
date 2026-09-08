"""Tests for live_fetch_xml: Europe PMC first, NCBI EFetch fallback, no crash.

No real network: search.http.get_text is patched. These assert the fallback
order and that a throttled/absent Europe PMC XML is recovered from EFetch rather
than silently becoming a miss.
"""
import search.http as http
from extract.fetch import live_fetch_xml, EFETCH, EPMC_FULLTEXT

XML = ("<article><sec><title>Results</title><p>"
       + "Higher family income was associated with larger hippocampal volume "
         "across the sample, and a comparable association was seen for amygdala "
         "volume; full statistics are reported in the tables below. " * 2
       + "</p></sec></article>")


def test_uses_europepmc_when_available(monkeypatch):
    calls = []

    def fake_get_text(url, **kw):
        calls.append(url)
        if EPMC_FULLTEXT in url:
            return XML
        raise AssertionError("should not reach EFetch")

    monkeypatch.setattr(http, "get_text", fake_get_text)
    out = live_fetch_xml("me@x.edu")("PMC123")
    assert out == XML
    assert EFETCH not in " ".join(calls)


def test_falls_back_to_efetch_when_europepmc_fails(monkeypatch):
    calls = []

    def fake_get_text(url, **kw):
        calls.append(url)
        if EPMC_FULLTEXT in url:
            raise Exception("403 not in OA subset")
        if url == EFETCH:
            return XML
        return None

    monkeypatch.setattr(http, "get_text", fake_get_text)
    out = live_fetch_xml("me@x.edu")("PMC123")
    assert out == XML
    assert any(u == EFETCH for u in calls)          # fallback was tried


def test_efetch_receives_numeric_id(monkeypatch):
    seen = {}

    def fake_get_text(url, **kw):
        if EPMC_FULLTEXT in url:
            raise Exception("miss")
        seen["params"] = kw.get("params")
        return XML

    monkeypatch.setattr(http, "get_text", fake_get_text)
    live_fetch_xml("me@x.edu")("PMC4241384")
    assert seen["params"]["id"] == "4241384"        # 'PMC' prefix stripped


def test_returns_none_when_both_fail(monkeypatch):
    def fake_get_text(url, **kw):
        raise Exception("down")

    monkeypatch.setattr(http, "get_text", fake_get_text)
    assert live_fetch_xml("me@x.edu")("PMC123") is None


def test_rejects_too_short_body(monkeypatch):
    # an error stub or empty page must not be accepted as XML
    def fake_get_text(url, **kw):
        return "<html>nope</html>"

    monkeypatch.setattr(http, "get_text", fake_get_text)
    assert live_fetch_xml("me@x.edu")("PMC123") is None
