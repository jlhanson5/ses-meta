"""Shared source interface.

Every source module exposes a class with the same contract:

    run(query: str, date_from: str, date_to: str) -> list[Record]

`date_from` / `date_to` are ISO dates (YYYY-MM-DD), inclusive. `query` is a
single expanded boolean query string (see search.queries). Sources are
responsible for their own rate limiting and for writing their raw payload to the
cache via http.cached_fetch.
"""
from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from ..model import Record


class Source(abc.ABC):
    #: short, stable tag stored in the DB `source` column
    name: str = "base"

    def __init__(self, raw_dir: Path, run_date: str, api_key: Optional[str] = None,
                 mailto: str = "meta-analysis@example.org") -> None:
        self.raw_dir = raw_dir
        self.run_date = run_date
        self.api_key = api_key
        self.mailto = mailto

    @abc.abstractmethod
    def run(self, query: str, date_from: str, date_to: str) -> list[Record]:
        """Execute one query over [date_from, date_to] and return normalized records."""
        raise NotImplementedError

    @staticmethod
    def _year(value) -> Optional[int]:
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return None
