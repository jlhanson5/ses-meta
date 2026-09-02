# llm/ — the LLM service

One place for model calls. Every service that needs inference imports this
contract; none of them call a hosted API. The default backend shells out to the
local Claude Code CLI.

## Why local Claude Code, not an SDK

The engineering standard routes inference through local Claude Code rather than a
hosted endpoint. A thin subprocess wrapper around the `claude` CLI is the whole
job, so no HTTP LLM dependency is added. An SDK was considered and rejected: it
would pull the project toward a hosted API, which the standard forbids by
default.

## Contract

```python
from llm import ClaudeCodeClient, complete_json

client = ClaudeCodeClient(default_model="sonnet")
obj = complete_json(client, "...prompt...")   # -> dict, strict JSON object
```

A client is anything with `complete(prompt, *, system, model) -> str` and a
`model_version` property. `complete_json` parses a strict-JSON object reply and
repairs the harmless (code fences, prose around the braces); it raises rather
than invent an object.

## Backends

- `ClaudeCodeClient` (`claude_code.py`): calls
  `claude -p <prompt> --output-format json [--model m] [--append-system-prompt s]`
  and returns the envelope's `result`. Config via env: `CLAUDE_BIN`,
  `CLAUDE_MODEL`, `CLAUDE_TIMEOUT`. `available()` reports whether the CLI is on
  PATH. Uses the best model by default; no silent downgrade.
- `ScriptedClient` (`fake.py`): answers from a mapping or a callable, records
  every call, touches nothing external. Backbone of the free gate tests.

## Caching

`ResponseCache` + `CachedClient` (`cache.py`) key on
`sha256(model_version | system | prompt)` in a self-contained SQLite file, so an
identical call returns the stored string. The screen layer also caches at the
decision level, so in practice a repeat call is skipped before it reaches here;
this is the second line and lets future consumers share it.

## Tests

`tests/` covers JSON parsing and repair, the fake client, the CLI command
construction and envelope parsing (subprocess patched, no real calls), and the
cache. All free and deterministic.

## No binary in this sandbox

There is no `claude` CLI here and the network is blocked, so live model calls run
on Jamie's machine. Tests and the screening demo use the fake and a labeled
simulation.
