"""The orchestrator's plan, read-only.

Runs before the idea log (arena/ideas.py) saved the orchestrator's plan as versioned `plan` ledger rows. The `plan`
tool and its stale notices are gone; the viewer still reads those rows so old runs stay readable.
"""

from __future__ import annotations

from pathlib import Path

from arena import orchestration

STATUSES = ("open", "running", "done", "failed")


def plan_rows(directory: Path) -> list[dict]:
    """Every saved plan version, oldest first. Row: {type, version, actor_id, best, steps, warnings}."""
    return [row for row in orchestration._history(directory) if row.get("type") == "plan"]
