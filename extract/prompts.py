"""Load, hash, and render the extraction and verification prompts.

Same discipline as screening: prompts are versioned files, never inline strings,
and every extracted row records the prompt_hash that produced it. Rendering uses
str.replace, not str.format, because study text and quotes are full of literal
braces.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

EXTRACT = "extract_v1"
VERIFY = "verify_v1"


@dataclass(frozen=True)
class Prompt:
    version: str
    template: str
    prompt_hash: str

    def render(self, **fields: str) -> str:
        body = self.template
        for key, val in fields.items():
            body = body.replace("{" + key + "}", val)
        return body


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / f"{name}.md"
    data = path.read_bytes()
    return Prompt(version=name, template=data.decode("utf-8"),
                  prompt_hash=hashlib.sha256(data).hexdigest())
