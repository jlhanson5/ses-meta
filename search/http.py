"""Shared HTTP layer: per-source rate limiting, explicit backoff, and a raw cache.

The cache is the mechanism that makes re-runs cheap: one JSON file per
(run_date, source, query_hash) under /data/raw. If the file exists for the
current run, we load it and never touch the network. Files are immutable once
written.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests


DEFAULT_TIMEOUT = 30
MAX_RETRIES = 5


class RateLimiter:
    """Simple min-interval limiter. One instance per source."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()


def query_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def raw_path(raw_dir: Path, run_date: str, source: str, qhash: str) -> Path:
    return raw_dir / f"{run_date}_{source}_{qhash}.json"


def get_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    limiter: Optional[RateLimiter] = None,
    method: str = "GET",
    data: Any = None,
) -> Any:
    """GET/POST returning parsed JSON, with backoff on 429/5xx.

    Honors Retry-After when present; otherwise exponential backoff with a cap.
    Raises requests.HTTPError on non-retryable 4xx and on exhausted retries.
    """
    backoff = 1.0
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        if limiter:
            limiter.wait()
        try:
            resp = requests.request(
                method, url, params=params, headers=headers, json=data,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:  # network error, retry
            last_exc = exc
            time.sleep(min(backoff, 30))
            backoff *= 2
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(int(retry_after))
            else:
                time.sleep(min(backoff, 30))
                backoff *= 2
            last_exc = requests.HTTPError(f"{resp.status_code} on {url}")
            continue

        resp.raise_for_status()
        return resp.json()

    raise requests.HTTPError(f"exhausted {MAX_RETRIES} retries on {url}") from last_exc


def get_text(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    limiter: Optional[RateLimiter] = None,
) -> str:
    """Same retry policy as get_json but returns raw text (for XML endpoints)."""
    backoff = 1.0
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        if limiter:
            limiter.wait()
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(min(backoff, 30))
            backoff *= 2
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(int(retry_after))
            else:
                time.sleep(min(backoff, 30))
                backoff *= 2
            last_exc = requests.HTTPError(f"{resp.status_code} on {url}")
            continue
        resp.raise_for_status()
        return resp.text
    raise requests.HTTPError(f"exhausted {MAX_RETRIES} retries on {url}") from last_exc


def cached_fetch(
    raw_dir: Path,
    run_date: str,
    source: str,
    qhash: str,
    fetch: Callable[[], Any],
) -> Any:
    """Return cached raw JSON for this (run_date, source, qhash) or fetch + write it.

    `fetch` must return a JSON-serializable object (the full raw API payload).
    The file is written atomically and never overwritten once present.
    """
    path = raw_path(raw_dir, run_date, source, qhash)
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    payload = fetch()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return payload
