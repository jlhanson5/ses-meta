"""Injectable fake backends for gate tests and offline runs.

ScriptedClient answers from a table or a callable, records every call, and never
touches the network or a subprocess. It is the backbone of the free, fast gate
tests: same input, same output, zero cost.

Two ways to script it:
  - mapping: {substring_in_prompt: reply_str} -> first substring found wins
  - responder: callable(prompt, system, model) -> reply_str  (full control)

`calls` holds every (prompt, system, model) tuple so a test can assert the cache
prevented a second call.
"""
from __future__ import annotations

from typing import Callable, Optional


class ScriptedClient:
    def __init__(self, mapping: Optional[dict[str, str]] = None,
                 responder: Optional[Callable[[str, Optional[str], Optional[str]], str]] = None,
                 model_version: str = "fake:scripted") -> None:
        if mapping is None and responder is None:
            raise ValueError("provide either a mapping or a responder")
        self.mapping = mapping or {}
        self.responder = responder
        self._model_version = model_version
        self.calls: list[tuple[str, Optional[str], Optional[str]]] = []

    @property
    def model_version(self) -> str:
        return self._model_version

    def complete(self, prompt: str, *, system: Optional[str] = None,
                 model: Optional[str] = None) -> str:
        self.calls.append((prompt, system, model))
        if self.responder is not None:
            return self.responder(prompt, system, model)
        for needle, reply in self.mapping.items():
            if needle in prompt:
                return reply
        raise KeyError("ScriptedClient: no mapping entry matched the prompt")

    @property
    def call_count(self) -> int:
        return len(self.calls)
