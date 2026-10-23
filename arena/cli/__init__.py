"""The ``arena`` command line and its command tree."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Parameter
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

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

    return cli_execute(options, (*passthrough, *_RUN_ARGS))


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
def golf(theorem: str, proof: Path, out: Path, seconds: float = 600.0) -> int:
    """One bounded greedy golf pass over a loose proof: fast-mode search, then a full cold check before writing."""
    load_env()
    from arena.cli.golf import execute

    return execute(theorem, proof, out, seconds)


@app.command()
def merge(run_id: str, parent_pid: int | None = None, once: bool = False) -> int:
    from arena.cli.merge import execute

    return execute(run_id, parent_pid, once)


@app.command()
def submit(
    *,
    name: str,
    runs: Annotated[list[str], Parameter(name="runs", consume_multiple=True, negative=())],
    previous: str | None = None,
    max_cold: int = 5,
    hybrids: bool = True,
    max_hybrids: int = 20,
    ceiling_usd: float = 3.0,
    discover: bool = False,
    archive: bool = False,
    overwrite: bool = False,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    """Prepare a competition submission under `runs/submission/<name>/`.

    Prepares files only. The owner uploads. Nothing in this command contacts a network service.

    Upload sequence, from the submission checklist:
    1. Check that proofs.jsonl and provenance.json agree and that per-problem spend stays within
       the chosen track's limit. The closed-track maximum is $3.00 per problem, summed over every
       contributing run and reported when a row exceeds it.
    2. The owner uploads proofs.jsonl under Submit → Proofs and chooses the track. A first
       successful submission claims the username and shows a key once; later submissions replace
       the current leaderboard entry.
    3. Compare the official worker's theorem-by-theorem result with the local proxy. A subset
       upload is allowed, but unsubmitted benchmark rows score zero in the overall average.
    4. Upload the code archive when Submit → Code opens on November 1, 2026, and submit the
       technical report to OpenReview by November 8, 2026.

    Cross-run step hybrids are enabled by default. Use --no-hybrids for single-run selection,
    or --max-hybrids to limit cold-checked hybrids per row (default 20).
    """
    from rich.console import Console

    from arena.submit import SubmitError, build_submission

    console = Console(stderr=True)

    def on_progress(event: dict) -> None:
        if event.get("phase") == "cold":
            console.print(f"{event.get('row')}: cold-checking {event.get('candidate')}")
        elif event.get("phase") == "fail":
            console.print(
                f"[red]{event.get('row')} {event.get('candidate')}: {'; '.join(event.get('reasons') or [])}[/red]"
            )

    try:
        result = build_submission(
            name,
            runs,
            previous=previous,
            max_cold=max_cold,
            hybrids=hybrids,
            max_hybrids=max_hybrids,
            ceiling_usd=ceiling_usd,
            discover=discover,
            archive=archive,
            overwrite=overwrite,
            progress=on_progress,
        )
    except SubmitError as error:
        print(f"submit: {error}", file=sys.stderr)
        return 2
    if json_output:
        print(
            json.dumps(
                {
                    "code": result.code,
                    "directory": str(result.directory),
                    "worse": result.worse,
                    "missing": result.missing,
                    "blocked": result.blocked,
                },
                ensure_ascii=False,
            )
        )
    elif result.code == 0:
        print(result.directory)
        if previous is not None:
            for row in result.worse:
                console.print(f"[red]{row} got worse[/red]")
            print(f"{len(result.worse)} row(s) got worse")
    else:
        print(f"blocked: {result.directory / 'blocked.json'}", file=sys.stderr)
    return result.code


@app.command()
def submission(baseline: Path, out: Path, cold: bool = False) -> int:
    """Build a submission directory: baseline rows replaced by better cold-verified runs."""
    from arena.submission import cli_execute

    return cli_execute(baseline, out, cold)


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

index_app = App(name="index", help="Build and inspect offline declaration indexes.")
app.command(index_app)


@index_app.command(name="build")
def index_build(
    row: str,
    version: str | None = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    from arena import index

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(pulse_style="cyan"),
            TimeElapsedColumn(),
            transient=True,
            console=Console(stderr=True),
        ) as progress:
            task = progress.add_task(f"Indexing {row} declarations", total=None)
            result = index.build_index(row, version)
            progress.update(task, description="Declaration index ready")
            progress.stop_task(task)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"index FAILED: {error}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        cached = " cached" if result["cached"] else ""
        print(
            f"{result['path']}  {result['declarations']} declarations  {result['bytes']} bytes  "
            f"{result['seconds']:.3f}s{cached}"
        )
    return 0


@index_app.command(name="status")
def index_status(
    row: str | None = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    from arena import index

    rows = [engine.problem(row)] if row else [json.loads(line) for line in engine.BENCHMARK.read_text().splitlines()]
    items = []
    for item in rows:
        for version, _commit in engine.versions(item):
            path = index.index_path(item["name"], version)
            exists = path is not None
            items.append(
                {
                    "row": item["name"],
                    "version": version,
                    "present": exists,
                    "path": str(path) if exists else None,
                    "bytes": path.stat().st_size if exists else None,
                    "age_seconds": max(0.0, time.time() - path.stat().st_mtime) if exists else None,
                }
            )
    if json_output:
        print(json.dumps({"items": items}, ensure_ascii=False, sort_keys=True))
    else:
        for item in items:
            state = "present" if item["present"] else "missing"
            detail = f"{item['path']}  {item['bytes']} bytes  {item['age_seconds']:.0f}s old" if item["present"] else ""
            print(f"{item['row']} {item['version']}: {state} {detail}".rstrip())
    return 0


@graph_app.command(name="export")
def graph_export(run_id: str, output: Path | None = None) -> int:
    from arena.cli.graph import execute

    return execute(run_id, output)


lean_app = App(name="lean", help="Manage Lean sessions.")
app.command(lean_app)

app.command(text_app)


@lean_app.command(name="serve")
def serve_lean(service_dir: Path | None = None) -> int:
    from arena.cli.lean import serve

    return serve(service_dir)


@lean_app.command()
def status(json_output: Annotated[bool, Parameter(name="json")] = False) -> int:
    from arena.cli.lean import status as show_status

    return show_status(json_output)


@lean_app.command()
def stop() -> int:
    from arena.cli.lean import stop as stop_service

    return stop_service()


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


@lean_app.command(name="repl-build")
def repl_build(
    toolchain: Annotated[list[str] | None, Parameter(name="toolchain", consume_multiple=True)] = None,
    clean: bool = False,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    """Build the tagged Lean REPL for every toolchain used by the benchmark rows."""
    import shutil

    from arena import lean_repl

    if toolchain is None:
        names = []
        for line in engine.BENCHMARK.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            names.extend(version for version, _commit in engine.versions(row))
        toolchain = list(dict.fromkeys(names))
    results = []
    for version in toolchain:
        if clean:
            shutil.rmtree(lean_repl.pickle_dir(version), ignore_errors=True)
        binary = lean_repl.build(version, log=lambda _line: None)
        metadata_path = lean_repl.repl_dir(version) / "build.json"
        metadata = json.loads(metadata_path.read_text())
        if version == "v4.29.1" and metadata.get("ok") and binary.is_file():
            metadata["smoke"] = lean_repl.smoke(version)
            metadata["ok"] = bool(metadata["smoke"].get("ok"))
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        results.append(metadata)
    if json_output:
        print(json.dumps(results, indent=2))
    else:
        from rich.console import Console

        console = Console()
        for result in results:
            seconds = result.get("seconds")
            elapsed = f" ({seconds}s)" if seconds is not None else ""
            note = f"; smoke={result['smoke']}" if result.get("smoke") else ""
            console.print(f"{result['toolchain']}: {'ok' if result['ok'] else 'failed'}{elapsed}{note}")
    return 0


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
    full: bool = False,
    engine_choice: Annotated[Literal["lsp", "repl", "both"] | None, Parameter(name="engine")] = None,
    trial: Literal["header-snapshot"] | None = None,
    json_output: Annotated[bool, Parameter(name="json")] = False,
) -> int:
    """Measure Lean speed and compare it with a recorded baseline.

    The quick gate (`--compare` alone: Core, Putnam and CSLib on their first toolchain, about 6 minutes) runs at the end
    of every Lean ticket. The full gate (`--full --compare`: every row and toolchain the baseline holds, ArkLib's four
    included, about 25 minutes) runs after 08d and 12, and whenever the quick gate fails.

    Run once at the end of every ticket that touches Lean machinery: 08a, 08b, 08c, 08d, 10b, 12. Never in the fast suite. If it fails right after other large Lean work (another workspace, a campaign, a reboot), run it once more: the first run refills the page cache. A figure that fails both runs is a regression. The table shows each row's CPU clock and temperature while its checks ran: a hot laptop runs every long check slower by about as much as its clock fell.
    """
    from datetime import datetime

    from arena import lean_repl
    from arena.cli import lean_bench

    if trial == "header-snapshot":
        results = []
        for line in engine.BENCHMARK.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["source"].lower() not in ("physlib", "cslib"):
                continue
            for version, commit in engine.versions(row):
                if engine.toolchain_key(version) < engine.toolchain_key("v4.32.0"):
                    continue
                try:
                    project = engine.workspace(row, version, commit)
                except FileNotFoundError:
                    continue
                built = engine.candidate_file(row, row["src"], version, commit)
                result = lean_repl.header_snapshot_trial(project, built["text"][: built["head"]], timeout)
                results.append({"row": row["name"], "toolchain": version, **result})
        if json_output:
            print(json.dumps(results, indent=2))
        else:
            for result in results:
                status = result if result.get("available") else "not available"
                print(f"{result['row']} {result['toolchain']}: {status}")
        return 0
    if engine_choice is not None and not full and compare is None:
        try:
            comparison = lean_repl.compare_engines(engine_choice or "both", timeout)
        except (OSError, ValueError, RuntimeError) as error:
            print(error)
            return 2
        if json_output:
            print(json.dumps(comparison, indent=2))
        else:
            print(json.dumps(comparison, indent=2))
            print(f"REPL adoption: {'yes' if comparison['adopt'] else 'no'}")
        return 0

    chosen: str | dict[str, list[str]] = versions
    if full:
        if compare is None:
            print("--full measures the toolchains the baseline holds: pass --compare <baseline>")
            return 2
        try:
            chosen = lean_bench.baseline_versions(lean_bench.load_baseline(compare))
        except ValueError as error:
            print(error)
            return 2
    requested_rows = rows is not None
    selected_rows = rows or list(chosen if isinstance(chosen, dict) else lean_bench.QUICK_ROWS)
    selected_out = out or ROOT / "runs/analysis/bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    if not requested_rows:
        available = []
        for name in selected_rows:
            try:
                row = engine.problem(name)
                toolchains = engine.versions(row)
                if isinstance(chosen, dict):
                    selected = [pair for pair in toolchains if pair[0] in chosen.get(name, [])]
                else:
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
        measured = lean_bench.measure(selected_rows, chosen, repeats, timeout, selected_out)
        old_record = None
        if record is not None:
            old_record = lean_bench.write_baseline(record, measured, force)
        if json_output:
            print(json.dumps(measured, indent=2))
        else:
            print(measured["measurement_note"])
            lean_bench.print_table(measured)
        if old_record is not None:
            _print_bench_comparison(old_record, {**old_record, **measured})
        for warning in lean_bench.cold_cache_warnings(measured):
            print(warning)
        if baseline is not None:
            for warning in lean_bench.cpu_speed_warnings(baseline, measured):
                print(warning)
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


@app.command()
def replay(
    run: str,
    *,
    turn: int | None = None,
    node: str | None = None,
    raw: bool = False,
    json_output: Annotated[bool, Parameter(name="json")] = False,
    render: str | None = None,
) -> int:
    """Show what one turn of a journaled run sent to the model."""
    if render is not None and render != "v7":
        print("replay --render accepts only: v7", file=sys.stderr)
        return 2
    if turn is not None and node is not None:
        print("replay accepts --turn or --node, not both", file=sys.stderr)
        return 2
    # --raw is the stored payload bytes. --render v7 rebuilds later surfaces, so the two views are not combined.
    if raw and render is not None:
        print("replay --raw is the exact payload and --render v7 is a re-render; pass only one", file=sys.stderr)
        return 2
    from arena.replay import (
        ReplayError,
        format_index,
        index_rows,
        load_run,
        node_turn,
        raw_payload,
        render_turn,
        rerender_v7,
    )
    from arena.traces import JournalError

    try:
        loaded = load_run(run)
        if node is not None:
            number = node_turn(loaded, node)
        elif turn is not None:
            number = turn
        else:
            print(json.dumps({"turns": index_rows(loaded)}) if json_output else format_index(loaded))
            return 0
        if raw:
            data = raw_payload(loaded, number)
            if json_output:
                body = data.decode()
                print(json.dumps({"turn": number, "sections": [{"title": "Payload", "text": body}]}))
            else:
                sys.stdout.buffer.write(data)
            return 0
        sections = rerender_v7(loaded, number) if render == "v7" else render_turn(loaded, number)
        if json_output:
            payload = {"turn": number, "sections": [{"title": title, "text": text} for title, text in sections]}
            print(json.dumps(payload))
            return 0
        from rich.panel import Panel
        from rich.text import Text

        console = Console(highlight=False)
        for title, text in sections:
            console.print(Panel(Text(text), title=Text(title)))
        return 0
    except (ReplayError, JournalError) as error:
        print(error, file=sys.stderr)
        return 1


# `arena campaign ... -- <run options>`: cyclopts 5 does not hand tokens after `--` to the variadic parameter when
# the options come from a flattened dataclass, so main() cuts them off before parsing.
_RUN_ARGS: list[str] = []


def split_run_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if argv[:1] == ["campaign"] and "--" in argv:
        cut = argv.index("--")
        return argv[:cut], argv[cut + 1 :]
    return argv, []


def main() -> None:
    argv, _RUN_ARGS[:] = split_run_args(sys.argv[1:])
    result = app(argv)
    sys.exit(result if isinstance(result, int) else 0)
