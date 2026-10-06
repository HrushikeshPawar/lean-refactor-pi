#!/usr/bin/env python3
"""The Arena Lean skill: where it lives, its content hash, and how its references are derived."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "packages/arena-pi/skills/arena-lean"
VENDORED = ROOT / "vendor/lean4-skills/plugins/lean4/skills/lean4/references"
# Reference files derived (copied verbatim) from the vendored lean4 skill.
DERIVED = ("proof-golfing", "proof-golfing-patterns", "proof-simplification",
           "performance-optimization", "profiling-workflows", "tactics-reference",
           "tactic-patterns", "simp-reference", "grind-tactic", "calc-patterns",
           "compilation-errors", "lean-lsp-server")


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


def sync() -> None:
    """Refresh derived references from the vendored skill and record the source commit."""
    target = SKILL_DIR / "references"
    target.mkdir(parents=True, exist_ok=True)
    for name in DERIVED:
        shutil.copyfile(VENDORED / f"{name}.md", target / f"{name}.md")
    commit = subprocess.run(["git", "-C", str(ROOT / "vendor/lean4-skills"), "rev-parse", "HEAD"],
                            text=True, capture_output=True, check=True).stdout.strip()
    (SKILL_DIR / "PROVENANCE.md").write_text(
        "# Provenance\n\n`SKILL.md` is written for the Arena. Files in `references/` are copied verbatim from "
        f"the vendored lean4 skill at commit `{commit}`:\n\n" + "".join(f"- {name}.md\n" for name in DERIVED))


if __name__ == "__main__":
    if sys.argv[1:] == ["sync"]:
        sync()
    print(skill_hash())
