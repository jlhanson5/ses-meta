"""Prompt loading, hashing, and rendering.

Prompts live as versioned files in screen/prompts/, never as inline strings, so a
decision can be tied to the exact prompt text that produced it. The prompt_hash
recorded on every model decision is sha256 of the file bytes: change the file,
change the hash, and re-screening produces new rows rather than overwriting old
ones.

Rendering fills {title} and {abstract} by simple replacement (not str.format)
because abstracts contain literal braces often enough that format() is a hazard.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# The two independent passes screened per record. Different framings on purpose:
# A argues for inclusion, B argues for exclusion. Agreement is signal.
PASSES = {
    "A": "screen_pass_a_v1.md",
    "B": "screen_pass_b_v1.md",
}


@dataclass(frozen=True)
class Prompt:
    version: str          # e.g. "screen_pass_a_v1"
    template: str
    prompt_hash: str      # sha256 of the file bytes

    def render(self, title: str, abstract: str) -> str:
        body = self.template.replace("{title}", title or "(no title)")
        body = body.replace("{abstract}", abstract or "(no abstract provided)")
        return body


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_prompt(pass_name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    if pass_name not in PASSES:
        raise KeyError(f"unknown pass {pass_name!r}; known: {sorted(PASSES)}")
    path = prompts_dir / PASSES[pass_name]
    data = path.read_bytes()
    version = path.stem
    return Prompt(version=version, template=data.decode("utf-8"),
                  prompt_hash=_hash_bytes(data))


def load_all(prompts_dir: Path = PROMPTS_DIR) -> dict[str, Prompt]:
    return {name: load_prompt(name, prompts_dir) for name in PASSES}
