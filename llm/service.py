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
    """Return the first balanced {...} object, ignoring any trailing data.

    A brace-depth scan (string-aware) finds where the first object closes, so a
    reply that appends a second object or trailing prose after the JSON still
    parses. Taking first-brace-to-last-brace would swallow that trailing data
    and fail, which is the bug this replaces.
    """
    t = _FENCE.sub("", text.strip())
    start = t.find("{")
    if start == -1:
        raise JSONError(f"no JSON object found in reply: {text[:200]!r}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return t[start:i + 1]
    raise JSONError(f"no balanced JSON object in reply: {text[:200]!r}")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a reply expected to be one JSON object. Raises JSONError otherwise.

    Every decode failure is raised as JSONError (never a bare JSONDecodeError),
    so a caller's `except JSONError` reliably catches a malformed reply and can
    route the record to review instead of crashing the run.
    """
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            obj = json.loads(_extract_object(text))
        except json.JSONDecodeError as exc:
            raise JSONError(
                f"unparseable JSON reply ({exc}); text={text[:200]!r}"
            ) from exc
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
