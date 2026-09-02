"""Content-addressed response cache.

Key = sha256(model_version | system | prompt). A hit means the exact same call
was made before, so re-runs cost nothing. This is a generic raw-call cache owned
by the LLM service. The screen layer has its own higher-level idempotency (a
decision row per record_id + prompt_hash), so in practice a re-run is skipped
before it ever reaches here; this cache is the second line and lets other future
consumers share the benefit.

Stored in its own SQLite file so the service stays self-contained and never
reaches into another service's database.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key         TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    response    TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""


def cache_key(model_version: str, system: Optional[str], prompt: str) -> str:
    h = hashlib.sha256()
    h.update((model_version or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((system or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()


class ResponseCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def get(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT response FROM llm_cache WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def put(self, key: str, model: str, response: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO llm_cache (key, model, response, created_at) "
            "VALUES (?, ?, ?, ?)",
            (key, model, response, time.time()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class CachedClient:
    """Wrap any LLMClient so identical calls return the cached string."""

    def __init__(self, client, cache: ResponseCache) -> None:
        self.client = client
        self.cache = cache
        self.hits = 0
        self.misses = 0

    @property
    def model_version(self) -> str:
        return self.client.model_version

    def complete(self, prompt: str, *, system=None, model=None) -> str:
        key = cache_key(self.model_version, system, prompt)
        cached = self.cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        resp = self.client.complete(prompt, system=system, model=model)
        self.cache.put(key, self.model_version, resp)
        return resp
