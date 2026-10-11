"""The ``arena`` command line and its command tree."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter

from arena import engine
from arena.cli.campaigns import CampaignOptions
from arena.cli.check import CheckOptions
from arena.cli.doctor import DoctorOptions
from arena.cli.experiment import ExperimentOptions
from arena.cli.lean_load import LeanLoadOptions
from arena.cli.protocol import ProtocolOptions
from arena.cli.provision import ProvisionOptions
from arena.cli.run import RunOptions
from arena.cli.text import app as text_app

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

app.command(text_app)


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


@lean_app.command()
def bench(
    rows: Annotated[list[str] | None, Parameter(name="rows", consume_multiple=True)] = None,
    versions: str = "first",
    repeats: int = 5,
    timeout: float = 180,
    out: Path | None = None,
    record: Path | None = None,
    compare: Path | None = None,
    tolerance_p50: float = 0.10,
    tolerance_p95: float = 0.20,
    force: bool = False,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    """Measure Lean speed and compare it with a recorded baseline.

    Run once at the end of every ticket that touches Lean machinery: 08a, 08b, 08c, 08d, 10b, 12. Never in the fast suite. If it fails right after other large Lean work (another workspace, a campaign, a reboot), run it once more: the first run refills the page cache. A figure that fails both runs is a regression.
    """
    from datetime import datetime

    from arena.cli import lean_bench

    requested_rows = rows is not None
    selected_rows = rows or list(lean_bench.BENCHMARK_ROWS)
    selected_out = out or ROOT / "runs/analysis/bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    if not requested_rows:
        available = []
        for name in selected_rows:
            try:
                row = engine.problem(name)
                toolchains = engine.versions(row)
                selected = toolchains if versions == "all" else toolchains[:1]
                if any(engine.workspace(row, v, c).is_dir() for v, c in selected):
                    available.append(name)
                else:
                    print(f"skip {name}: no requested workspace is provisioned")
            except (KeyError, ValueError):
                print(f"skip {name}: benchmark row is unavailable")
        selected_rows = available
    if not selected_rows:
        print("No benchmark rows have provisioned workspaces; skipped.")
        return 0
    try:
        if record is not None and record.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {record}; pass --force")
        baseline = lean_bench.load_baseline(compare) if compare is not None else None
        if baseline is not None and baseline["settings"]["repeats"] != repeats:
            raise ValueError(
                f"baseline repeats ({baseline['settings']['repeats']}) differ from requested repeats ({repeats})"
            )
        measured = lean_bench.measure(selected_rows, versions, repeats, timeout, selected_out)
        old_record = None
        if record is not None:
            old_record = lean_bench.write_baseline(record, measured, force)
        if json_output:
            import json

            print(json.dumps(measured, indent=2))
        else:
            print(measured["measurement_note"])
            lean_bench.print_table(measured)
        if old_record is not None:
            _print_bench_comparison(old_record, {**old_record, **measured})
        for warning in lean_bench.cold_cache_warnings(measured):
            print(warning)
        if baseline is not None:
            regressions = lean_bench.compare(baseline, measured, tolerance_p50, tolerance_p95)
            print(lean_bench.format_report(regressions))
            return 1 if regressions else 0
    except FileNotFoundError as error:
        print(error)
        return 2
    except (OSError, ValueError, RuntimeError) as error:
        print(error)
        return 2
    return 0


def _print_bench_comparison(old: dict, new: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    from arena.cli.lean_bench import _figure_values

    table = Table(title="Recorded baseline compared with new figures")
    for heading in ("Row", "Toolchain", "Figure", "Old", "New"):
        table.add_column(heading)
    for row, toolchains in new.get("rows", {}).items():
        for toolchain, result in toolchains.items():
            prior = old.get("rows", {}).get(row, {}).get(toolchain)
            old_values = {} if prior is None else _figure_values(prior)
            new_values = _figure_values(result)
            for figure in sorted(set(old_values) | set(new_values)):
                before, after = old_values.get(figure), new_values.get(figure)
                table.add_row(
                    row,
                    toolchain,
                    figure,
                    str(before) if before is not None else "-",
                    str(after) if after is not None else "-",
                )
    Console().print(table)


def main() -> None:
    result = app()
    sys.exit(result if isinstance(result, int) else 0)
