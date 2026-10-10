"""The one place that imports organizer code from the vendored submodules.

arena-space (the leaderboard Space) supplies the published reference denominators and the per-problem score;
lean-refactor supplies the official token counter. Both are loaded by path, never installed.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
ARENA_SPACE = ROOT / "vendor/arena-space"
CHECKER = ROOT / "vendor/lean-refactor/lean_refactor/cc_agent/tools/check_proof.py"


def _on_path(directory: Path) -> None:
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def benchmark() -> ModuleType:
    """arena-space's `benchmark` module: `original_length` and `original_heartbeats` per row."""
    _on_path(ARENA_SPACE)
    import benchmark as module

    return module


def leaderboard() -> type:
    """arena-space's `Leaderboard` class, whose `problem_score` is the official per-row score."""
    _on_path(ARENA_SPACE)
    from leaderboard import Leaderboard

    return Leaderboard


@cache
def checker() -> ModuleType:
    """lean-refactor's `check_proof` module, loaded once. It imports its sibling `heartbeat` module."""
    _on_path(CHECKER.parent)
    spec = importlib.util.spec_from_file_location("pinned_check_proof", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Pinned proof utility is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
