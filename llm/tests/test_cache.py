"""Gate tests for the response cache and CachedClient."""
from llm.cache import ResponseCache, CachedClient, cache_key
from llm.fake import ScriptedClient


def test_cache_key_stable_and_sensitive():
    k1 = cache_key("m", "sys", "prompt")
    k2 = cache_key("m", "sys", "prompt")
    k3 = cache_key("m", "sys", "prompt2")
    assert k1 == k2
    assert k1 != k3


def test_cache_put_get(tmp_path):
    cache = ResponseCache(tmp_path / "c.db")
    cache.put("k", "m", "resp")
    assert cache.get("k") == "resp"
    assert cache.get("missing") is None


def test_cached_client_serves_second_call_from_cache(tmp_path):
    inner = ScriptedClient(mapping={"p": "answer"})
    cache = ResponseCache(tmp_path / "c.db")
    client = CachedClient(inner, cache)

    a = client.complete("prompt p")
    b = client.complete("prompt p")
    assert a == b == "answer"
    assert inner.call_count == 1          # second call hit the cache
    assert client.hits == 1 and client.misses == 1
