"""The LLM contract shared across services.

A client is anything with a `complete(prompt, *, system, model) -> str` method.
`complete_json` wraps a client and enforces that the reply is a single JSON
object, doing minimal repair (strip code fences, trim prose around the braces)
before giving up. Repair is deliberately conservative: if the model did not
return an object, we raise rather than guess, because a screening decision must
never be invented by the parser.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Backend failed to produce a response (nonzero exit, timeout, empty)."""


class JSONError(ValueError):
    """Response was not a single parseable JSON object."""


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: Optional[str] = None,
                 model: Optional[str] = None) -> str:
        ...

    @property
    def model_version(self) -> str:
        """Resolved backend + model string, recorded on every decision."""
        ...


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _extract_object(text: str) -> str:
    """Return the outermost {...} span, tolerating fences and surrounding prose."""
    t = _FENCE.sub("", text.strip())
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise JSONError(f"no JSON object found in reply: {text[:200]!r}")
    return t[start:end + 1]


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a reply expected to be one JSON object. Raises JSONError otherwise."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = json.loads(_extract_object(text))
    if not isinstance(obj, dict):
        raise JSONError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


def complete_json(client: LLMClient, prompt: str, *,
                  system: Optional[str] = None,
                  model: Optional[str] = None) -> dict[str, Any]:
    """Call the client and parse a strict-JSON object reply."""
    raw = client.complete(prompt, system=system, model=model)
    if not raw or not raw.strip():
        raise LLMError("empty response from LLM backend")
    return parse_json_object(raw)
