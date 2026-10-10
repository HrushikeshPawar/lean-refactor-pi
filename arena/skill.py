"""The Arena Lean skill: where it lives and its content hash."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "packages/arena-pi/skills/arena-lean"


def skill_hash(directory: Path = SKILL_DIR) -> str:
    """Hash of every file's relative path and bytes, so a run records exactly what the model could read."""
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(directory)).encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def skill_prompt(directory: Path = SKILL_DIR) -> str:
    """SKILL.md without front matter. Pi lists skills only when it has a read tool, and the
    Arena disables built-in tools, so the body goes into the stable system prompt instead."""
    text = (directory / "SKILL.md").read_text()
    body = text.split("---", 2)[2] if text.startswith("---") else text
    return body.strip()
