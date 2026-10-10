"""The Arena Lean skill: where it lives and its content hash."""

from __future__ import annotations

import hashlib
from pathlib import Path

from arena.text import render

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "agent-text/skill"


def skill_hash() -> str:
    """Hash the rendered text the model reads, rather than template metadata."""
    return hashlib.sha256(skill_prompt().encode()).hexdigest()


def skill_prompt() -> str:
    """SKILL.md without front matter. Pi lists skills only when it has a read tool, and the
    Arena disables built-in tools, so the body goes into the stable system prompt instead."""
    rendered = render("skill/SKILL")
    body = rendered.split("---", 2)[2] if rendered.startswith("---") else rendered
    return body.strip()
