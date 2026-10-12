"""Commands for starting Lean sessions and inspecting run health."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from arena import lean_health, lean_session
from arena.engine import ROOT


def serve(service_dir: Path | None = None) -> int:
    """Run the shared Lean service in the foreground."""
    return lean_session.serve(service_dir or lean_session.service_dir())


def status(json_output: bool = False) -> int:
    path = lean_session.socket_path()
    reply = lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 2, str(path))
    if not reply or not reply.get("ok"):
        print("no service")
        return 0
    if json_output:
        print(json.dumps(reply, sort_keys=True))
        return 0
    table = Table(title="Lean service")
    table.add_column("Project")
    table.add_column("Workers", justify="right")
    table.add_column("Busy", justify="right")
    table.add_column("GB", justify="right")
    for server in reply.get("servers", []):
        table.add_row(server["project"], str(server["workers"]), str(server["busy"]), str(server["gb"]))
    Console().print(table)
    Console().print(f"Leases: {json.dumps(reply.get('leases', {}), sort_keys=True)}")
    Console().print(f"Holds: {json.dumps(reply.get('holds', {}), sort_keys=True)}")
    return 0


def stop() -> int:
    lean_session.stop_service()
    return 0


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
