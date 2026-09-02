"""HTTP layer tests: cache short-circuits fetch, backoff retries, limiter waits."""
import time

from search import http


def test_cached_fetch_writes_then_reads(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"hello": "world"}

    p1 = http.cached_fetch(tmp_path, "2026-09-02", "src", "abc123", fetch)
    p2 = http.cached_fetch(tmp_path, "2026-09-02", "src", "abc123", fetch)
    assert p1 == p2 == {"hello": "world"}
    assert calls["n"] == 1  # second call served from disk
    assert (tmp_path / "2026-09-02_src_abc123.json").exists()


def test_query_hash_stable():
    assert http.query_hash("a|b|c") == http.query_hash("a|b|c")
    assert http.query_hash("a") != http.query_hash("b")


def test_rate_limiter_enforces_min_interval():
    lim = http.RateLimiter(0.05)
    lim.wait()
    t0 = time.monotonic()
    lim.wait()
    assert time.monotonic() - t0 >= 0.05


def test_get_json_retries_on_500_then_succeeds(monkeypatch):
    seq = [500, 200]
    payloads = {"ok": True}

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise http.requests.HTTPError(str(self.status_code))

        def json(self):
            return payloads

    def fake_request(method, url, **kwargs):
        return Resp(seq.pop(0))

    monkeypatch.setattr(http.requests, "request", fake_request)
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)  # no real backoff wait
    out = http.get_json("https://example.org", limiter=None)
    assert out == payloads
    assert seq == []  # both responses consumed
