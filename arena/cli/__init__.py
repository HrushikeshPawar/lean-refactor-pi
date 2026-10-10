"""The ``arena`` command line and its command tree."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter

from arena.cli.campaigns import CampaignOptions
from arena.cli.check import CheckOptions
from arena.cli.doctor import DoctorOptions
from arena.cli.experiment import ExperimentOptions
from arena.cli.lean_load import LeanLoadOptions
from arena.cli.protocol import ProtocolOptions
from arena.cli.provision import ProvisionOptions
from arena.cli.run import RunOptions

ROOT = Path(__file__).resolve().parents[2]
app = App(name="arena", help="Lean Refactor Arena harness.", result_action="return_value")
_DEFAULT_DOCTOR_OPTIONS = DoctorOptions()
_DEFAULT_PROVISION_OPTIONS = ProvisionOptions()
_DEFAULT_LEAN_LOAD_OPTIONS = LeanLoadOptions()


def load_env(path: Path = ROOT / ".env") -> list[str]:
    """Export unset ``KEY=value`` entries from ``path`` without printing their values."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    exported = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            exported.append(key)
    return exported


@app.command()
def run(options: Annotated[RunOptions, Parameter(name="*")]) -> int:
    load_env()
    from arena.cli.run import execute

    return execute(options)


@app.command()
def campaign(
    options: Annotated[CampaignOptions, Parameter(name="*")],
    *passthrough: Annotated[str, Parameter(allow_leading_hyphen=True)],
) -> int:
    load_env()
    from arena.cli.campaigns import cli_execute

    return cli_execute(options, passthrough)


@app.command()
def certify(
    rows: str | None = None,
    tolerance: float = 0.05,
    output: Path | None = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
    require_all: bool = False,
) -> int:
    from arena.cli.certify import execute

    return execute(rows, tolerance, output, json_output, require_all)


@app.command()
def check(options: Annotated[CheckOptions, Parameter(name="*")]) -> int:
    from arena.cli.check import execute

    return execute(options)


@app.command(name="eval")
def eval_(
    name: str,
    proof_file: Path,
    mode: Literal["fast", "full"] = "fast",
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    from arena.cli.evaluate import execute

    return execute(name, proof_file, mode, json_output)


@app.command()
def merge(run_id: str, parent_pid: int | None = None, once: bool = False) -> int:
    from arena.cli.merge import execute

    return execute(run_id, parent_pid, once)


@app.command()
def package(
    *run_ids: str,
    name: str,
    commit: str = "HEAD",
    template: Path | None = None,
    discover: bool = False,
) -> int:
    from arena.cli.package import execute

    return execute(list(run_ids), name, commit, template, discover)


@app.command()
def preflight(
    theorem: str = "Core.InitsUpdatesComm",
    models: str | None = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    from arena.cli.preflight import execute

    return execute(theorem, models, json_output)


@app.command()
def serve(
    *run_ids: str,
    match: str | None = None,
    port: int = 8765,
    no_langfuse: bool = False,
    langfuse_ttl: float = 45.0,
) -> int:
    from arena.cli.serve import execute

    return execute(list(run_ids), match, port, no_langfuse, langfuse_ttl)


@app.command()
def provision(options: Annotated[ProvisionOptions, Parameter(name="*")] = _DEFAULT_PROVISION_OPTIONS) -> int:
    from arena.cli.provision import cli_execute

    return cli_execute(options)


@app.command()
def experiment(
    options: Annotated[ExperimentOptions, Parameter(name="*")],
    *passthrough: Annotated[str, Parameter(allow_leading_hyphen=True)],
) -> int:
    from arena.cli.experiment import cli_execute

    return cli_execute(options, passthrough)


@app.command(show=False)
def protocol(options: Annotated[ProtocolOptions, Parameter(name="*")]) -> int:
    from arena.cli.protocol import execute

    return execute(options)


@app.command()
def doctor(options: Annotated[DoctorOptions, Parameter(name="*")] = _DEFAULT_DOCTOR_OPTIONS) -> int:
    from arena.cli.doctor import execute

    return execute(options)


@app.command()
def smoke(*rows: str) -> int:
    from arena.cli.smoke import execute

    return execute(list(rows))


graph_app = App(name="graph", help="Export graph data.")
app.command(graph_app)


@graph_app.command(name="export")
def graph_export(run_id: str, output: Path | None = None) -> int:
    from arena.cli.graph import execute

    return execute(run_id, output)


lean_app = App(name="lean", help="Manage Lean sessions.")
app.command(lean_app)


@lean_app.command(name="serve")
def serve_lean(run_dir: Path, parent_pid: int | None = None, max_slots: int = 4) -> int:
    from arena.cli.lean import serve

    return serve(run_dir, parent_pid, max_slots)


@lean_app.command()
def health(run: str, json_output: Annotated[bool, Parameter(name="json")] = False) -> int:
    from arena.cli.lean import health as show_health

    return show_health(run, json_output)


@lean_app.command(name="load-test")
def load_test(
    options: Annotated[LeanLoadOptions, Parameter(name="*")] = _DEFAULT_LEAN_LOAD_OPTIONS,
) -> int:
    from arena.cli.lean_load import cli_execute

    return cli_execute(options)


def main() -> None:
    result = app()
    sys.exit(result if isinstance(result, int) else 0)
