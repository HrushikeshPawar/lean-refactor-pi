"""Commands for starting Lean sessions and inspecting run health."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from arena import lean_health, lean_session
from arena.engine import ROOT


def serve(run_dir: Path, parent_pid: int | None = None, max_slots: int = lean_session.MAX_SLOTS) -> int:
    """Start the Lean session daemon for a run directory."""
    return lean_session.serve(run_dir, parent_pid, max_slots)


def health(run: str, json_output: bool = False) -> int:
    """Show saved Lean health for a run id or run directory."""
    directory = Path(run)
    if not directory.is_dir():
        directory = ROOT / "runs/pi-budget" / run
    report = lean_health.read_health(directory)
    marker = lean_health.tripped(directory)
    ok = report is not None and marker is None
    if json_output:
        print(json.dumps({"run": run, "health": report, "tripped": marker, "ok": ok}))
    else:
        table = Table(title=f"Lean health: {run}")
        table.add_column("Record")
        table.add_column("Value")
        table.add_row("Health", json.dumps(report) if report is not None else "missing")
        table.add_row("Circuit breaker", json.dumps(marker) if marker is not None else "not tripped")
        Console().print(table)
    return 0 if ok else 1
