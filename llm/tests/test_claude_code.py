"""Gate tests for the Claude Code backend.

No real subprocess: we patch subprocess.run and shutil.which so the test is
free and deterministic. It asserts the command is built correctly and the JSON
envelope is parsed, which is the whole contract of this backend.
"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from llm import claude_code
from llm.claude_code import ClaudeCodeClient
from llm.service import LLMError


def _fake_run(stdout="", returncode=0, stderr=""):
    def run(cmd, capture_output, text, timeout):
        run.last_cmd = cmd
        return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)
    return run


def test_command_construction(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/usr/bin/claude")
    fake = _fake_run(stdout=json.dumps({"result": '{"decision":"include"}'}))
    monkeypatch.setattr(subprocess, "run", fake)

    client = ClaudeCodeClient(bin_path="claude", default_model="sonnet")
    out = client.complete("PROMPT", system="SYS")
    assert out == '{"decision":"include"}'
    cmd = fake.last_cmd
    assert cmd[0] == "claude"
    assert "-p" in cmd and "PROMPT" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--model" in cmd and "sonnet" in cmd
    assert "--append-system-prompt" in cmd and "SYS" in cmd


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: None)
    client = ClaudeCodeClient(bin_path="claude")
    with pytest.raises(LLMError, match="not found"):
        client.complete("x")


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(stdout="", returncode=1, stderr="boom"))
    client = ClaudeCodeClient()
    with pytest.raises(LLMError, match="exited 1"):
        client.complete("x")


def test_plain_text_envelope_passthrough(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(stdout='{"decision":"exclude"}'))
    client = ClaudeCodeClient()
    # stdout is itself valid JSON but not an envelope with result -> returned raw
    assert client.complete("x") == '{"decision":"exclude"}'


def test_error_envelope_raises(monkeypatch):
    monkeypatch.setattr(claude_code.shutil, "which", lambda b: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run",
                        _fake_run(stdout=json.dumps({"is_error": True, "result": "x"})))
    client = ClaudeCodeClient()
    with pytest.raises(LLMError):
        client.complete("x")
