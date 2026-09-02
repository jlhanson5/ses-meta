"""Default backend: shell out to the local Claude Code CLI.

Why a subprocess and not an SDK: the build standard routes inference through
local Claude Code, not a hosted API. A thin subprocess wrapper is the whole job,
so no dependency is added. The CLI is invoked in headless mode:

    claude -p "<prompt>" --output-format json [--append-system-prompt <sys>] [--model <m>]

`--output-format json` makes the CLI emit an envelope with a `result` field
holding the model's text. We parse that envelope, then hand `result` back to the
caller (screen parses the screening JSON out of it).

Config via env:
    CLAUDE_BIN     path to the CLI (default "claude")
    CLAUDE_MODEL   default model when a call does not name one
    CLAUDE_TIMEOUT seconds before we give up on a call (default 120)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from .service import LLMError


class ClaudeCodeClient:
    def __init__(self, bin_path: Optional[str] = None,
                 default_model: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        self.bin_path = bin_path or os.environ.get("CLAUDE_BIN", "claude")
        self.default_model = default_model or os.environ.get("CLAUDE_MODEL")
        self.timeout = timeout or float(os.environ.get("CLAUDE_TIMEOUT", "120"))
        self._resolved_version: Optional[str] = None

    def available(self) -> bool:
        return shutil.which(self.bin_path) is not None

    @property
    def model_version(self) -> str:
        m = self.default_model or "default"
        return f"claude-code:{m}"

    def _build_cmd(self, prompt: str, system: Optional[str],
                   model: Optional[str]) -> list[str]:
        cmd = [self.bin_path, "-p", prompt, "--output-format", "json"]
        chosen = model or self.default_model
        if chosen:
            cmd += ["--model", chosen]
        if system:
            cmd += ["--append-system-prompt", system]
        return cmd

    def complete(self, prompt: str, *, system: Optional[str] = None,
                 model: Optional[str] = None) -> str:
        if not self.available():
            raise LLMError(
                f"claude CLI not found at {self.bin_path!r}. Install Claude Code "
                f"or set CLAUDE_BIN. This backend does not call a hosted API."
            )
        cmd = self._build_cmd(prompt, system, model)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude call timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise LLMError(
                f"claude exited {proc.returncode}: {proc.stderr.strip()[:300]}"
            )
        return self._parse_envelope(proc.stdout)

    def _parse_envelope(self, stdout: str) -> str:
        """Pull the model text out of the CLI's JSON envelope.

        With --output-format json the CLI wraps the reply as {"result": "...",
        "model": "..."}. We return `result`. Fallbacks keep this from being
        brittle: non-JSON stdout is plain-text mode and returned as-is; a JSON
        dict with no envelope text field is treated as the model's raw answer
        and returned unchanged so the caller can parse it.
        """
        stdout = stdout.strip()
        if not stdout:
            raise LLMError("claude returned empty stdout")
        try:
            env = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout                      # plain-text mode
        if isinstance(env, dict):
            if env.get("is_error"):
                raise LLMError(f"claude reported error: {str(env)[:300]}")
            for key in ("result", "text", "content"):
                val = env.get(key)
                if isinstance(val, str) and val:
                    self._resolved_version = env.get("model") or self._resolved_version
                    return val
            return stdout                      # dict is the raw answer itself
        return stdout                          # list/scalar JSON: return raw
