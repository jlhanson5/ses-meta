"""Self-contained LLM service.

Every part of this project that needs a model call goes through this contract,
never through a hosted API. The default backend shells out to the local Claude
Code CLI (see claude_code.ClaudeCodeClient). Tests and offline runs inject a
fake (fake.ScriptedClient). Nothing here imports an HTTP LLM SDK on purpose:
the build standard routes inference through local Claude Code.

Public contract:
    LLMClient            protocol: complete(prompt, *, system, model) -> str
    complete_json(...)   parse a strict-JSON reply into a dict, with repair
    LLMError, JSONError  failure types
    ResponseCache        content-addressed cache so repeat calls cost nothing
"""
from .service import (
    LLMClient,
    LLMError,
    JSONError,
    complete_json,
)
from .cache import ResponseCache
from .claude_code import ClaudeCodeClient
from .fake import ScriptedClient

__all__ = [
    "LLMClient",
    "LLMError",
    "JSONError",
    "complete_json",
    "ResponseCache",
    "ClaudeCodeClient",
    "ScriptedClient",
]
