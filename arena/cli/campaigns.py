#!/usr/bin/env python3
"""Run a paid comparison campaign: theorem rows x models x N replicates, `--jobs` at a time.

Each row gets one certified kickoff packet shared by all its runs. Nothing is spent unless a
passing Langfuse preflight receipt covers every model (run here, or a fresh one) and every row's
packet certifies with its mandatory sections. `--dry-run` prints the plan and worst-case cost.

    python arena campaign --prefix v6c1 --rows Core.InitsUpdatesComm,fundamental_theorem_of_variational_calculus' \\
        --models deepseek-v4.1-flash --limit-usd 0.10 --replicates 1

`--preset v6-matrix` is the standing comparison: the configured models x the Core and PhysLib rows x 3 replicates at the preset's spend limit.

Arguments after `--` are passed to every run (for example `--no-mcp`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from rich.table import Table

from arena.cli.run import CONFIG, MODELS
from arena.engine import ROOT

RUNS = ROOT / "runs" / "pi-budget"
RECEIPT_MAX_AGE_HOURS = 12.0
# Named campaign configurations (models.yaml); explicit --rows/--models/--replicates/--limit-usd override a preset's values.
PRESETS = CONFIG.get("presets", {})
HELPER_DECL = re.compile(r"(?m)^\s*(?:private\s+|protected\s+)?(?:theorem|lemma)\s+\S+")


MIN_FREE_GB = 8.0  # MemAvailable needed before another run starts (nothing else in flight)
CLEANUP_WAIT_S = 300.0  # longest wait for finished runs' Lean processes to go and memory to come back
EVALUATIONS = ROOT / "runs" / "evaluations"
MAX_LIMIT_USD = 2.0  # keep equal to MAX_LIMIT_USD in packages/arena-pi/extensions/spend.ts
LEAN_UNHEALTHY_EXIT = 75  # keep equal to arena.lean_health.EXIT_CODE


class CampaignAbort(Exception):
    """A pre-spend gate failed; nothing was run."""


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)[:limit].strip("-._") or "row"


def plan(prefix: str, rows: list[str], models: list[str], replicates: int) -> list[dict]:
    """Replicate-major order: every row x model gets replicate k before any gets k+1."""
    if replicates < 1:
        raise ValueError("--replicates must be at least 1")
    if not rows or len(set(rows)) != len(rows) or not models or len(set(models)) != len(models):
        raise ValueError("rows and models must be non-empty and distinct")
    bad = [model for model in models if model not in MODELS]
    if bad:
        raise ValueError(f"unknown models {bad}; choose from {', '.join(MODELS)}")
    specs = [
        {"row": row, "model": model, "replicate": k, "run_id": f"{prefix}-{slug(row)}-{slug(model)}-r{k}"}
        for k in range(1, replicates + 1)
        for row in rows
        for model in models
    ]
    if len({spec["run_id"] for spec in specs}) != len(specs):
        raise ValueError("run IDs collide; use shorter distinct row names or another prefix")
    return specs


def worst_case_usd(specs: list[dict], limit: float) -> float:
    """The planned spend: every run's limit. A run's last call may overshoot its limit."""
    return round(len(specs) * limit, 6)


def command(spec: dict, limit: float, thinking: str, passthrough: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "arena.cli",
        "run",
        "--model",
        spec["model"],
        "--theorem",
        spec["row"],
        "--run-id",
        spec["run_id"],
        "--limit-usd",
        f"{limit:g}",
        "--thinking",
        thinking,
        *passthrough,
    ]


def check_packets(rows: list[str], packet_fn=None) -> dict[str, str]:
    """Row -> sha256 of its certified packet. Any uncertifiable row aborts the campaign."""
    if packet_fn is None:
        from arena.campaign import packet as packet_fn
    hashes, failures = {}, []
    for index, row in enumerate(rows, 1):
        print(
            f"packet {index}/{len(rows)} {row}: building (Lean context; cached rows are quick, new rows take minutes)",
            flush=True,
        )
        started = time.monotonic()
        try:
            text = packet_fn(row)
        except Exception as error:
            failures.append(f"{row}: {error}")
            print(f"packet {index}/{len(rows)} {row}: FAILED after {time.monotonic() - started:.0f}s", flush=True)
            continue
        hashes[row] = hashlib.sha256(text.encode()).hexdigest()
        print(
            f"packet {index}/{len(rows)} {row}: certified in {time.monotonic() - started:.0f}s ({len(text):,} chars)",
            flush=True,
        )
    if failures:
        raise CampaignAbort("packet certification failed: " + "; ".join(failures))
    return hashes


def check_preflight(
    models: list[str],
    skip: bool,
    block_fn=None,
    receipt_fn=None,
    run_fn=None,
    max_age_hours: float = RECEIPT_MAX_AGE_HOURS,
    now_fn=time.time,
) -> str:
    """Return how the gate was satisfied: 'skipped', 'fresh receipt' or 'ran preflight'."""
    if skip:
        return "skipped"
    if block_fn is None or receipt_fn is None:
        from arena.traces import preflight_block, receipt_path

        block_fn, receipt_fn = block_fn or preflight_block, receipt_fn or receipt_path

    def fresh() -> bool:
        path = Path(receipt_fn())
        return path.is_file() and now_fn() - path.stat().st_mtime <= max_age_hours * 3600

    if block_fn(models) is None and fresh():
        return "fresh receipt"
    if run_fn is None:

        def run_fn(models: list[str]) -> int:
            return subprocess.run(
                [sys.executable, "-m", "arena.cli", "preflight", "--models", ",".join(models)], cwd=ROOT
            ).returncode

    code = run_fn(models)
    reason = block_fn(models)
    if code != 0 or reason is not None:
        raise CampaignAbort(f"preflight failed: {reason or 'arena_preflight exited ' + str(code)}")
    return "ran preflight"


def helper_discovery(directory: Path, best_candidate: str | None) -> dict:
    """Model candidates that declare extra theorems/lemmas besides the target (helper discovery)."""
    ledger = []
    with suppress(OSError, ValueError):
        ledger = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines() if line]
    ids = [event["candidate_id"] for event in ledger if event.get("kind") == "candidate"]
    with_helpers, best_has = set(), False
    for _index, event in enumerate(e for e in ledger if e.get("kind") == "candidate"):
        if event.get("origin") != "model":
            continue
        try:
            text = (directory / "proofs" / f"{event['candidate_id']}.lean").read_text()
        except OSError:
            continue
        if len(HELPER_DECL.findall(text)) > 1:  # the target theorem is the first declaration
            with_helpers.add(event["candidate_id"])
            best_has = best_has or best_candidate == f"#{ids.index(event['candidate_id']) + 1}"
    return {"candidates_with_helpers": len(with_helpers), "best_uses_helper": best_has}


def run_row(
    spec: dict,
    summary: dict | None,
    exit_code: int,
    packet_sha256: str | None,
    expected_packet: str,
    directory: Path | None = None,
) -> dict:
    summary = summary or {}
    cost, progress = summary.get("cost") or {}, summary.get("progress") or {}
    best = progress.get("best_verified_candidate")
    return {
        **spec,
        "exit_code": exit_code,
        "packet_matches": packet_sha256 == expected_packet,
        "stop_reason": summary.get("stop_reason"),
        "lean": summary.get("lean"),
        "best_candidate": best.get("candidate") if best else None,
        "best_proxy": best.get("proxy") if best else None,
        "helpers": helper_discovery(directory, best.get("candidate") if best else None) if directory else None,
        "ideas_without_attempts": len(summary.get("ideas_without_attempts") or []),
        "routes": [
            {key: row[key] for key in ("route", "label", "attempts", "best_proxy")}
            for row in summary.get("routes") or []
            if row.get("attempts")
        ],
        "route_progress": summary.get("route_progress"),
        "tool_errors": (summary.get("tools") or {}).get("error_total"),
        "tool_errors_by_tool": (summary.get("tools") or {}).get("errors") or {},
        "cache_reuse_pct": (summary.get("cache") or {}).get("reuse_pct"),
        "bookkeeping_and_rejected_pct": cost.get("bookkeeping_and_rejected_pct"),
        "spent_usd": cost.get("spent_usd"),
        "requests": cost.get("requests"),
        "retries": cost.get("retries"),
    }


def _stats(values: list[float | int | None]) -> dict | None:
    numeric: list[float] = []
    # The explicit narrowing loop keeps `None` out of the numeric collection for ty.
    for value in values:
        if value is not None:
            numeric.append(float(value))  # noqa: PERF401
    if not numeric:
        return None
    return {"min": min(numeric), "median": statistics.median(numeric), "max": max(numeric)}


def aggregate(runs: list[dict], expected: dict[str, str]) -> dict:
    """Group run rows by (row, model); distributions are over replicates."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((run["row"], run["model"]), []).append(run)
    table = []
    for (row, model), items in groups.items():
        n = len(items)
        table.append(
            {
                "row": row,
                "model": model,
                "replicates": n,
                "verified_runs": sum(item["best_proxy"] is not None for item in items),
                "best_proxy": _stats([item["best_proxy"] for item in items]),
                "helper_runs": sum(bool((item["helpers"] or {}).get("candidates_with_helpers")) for item in items),
                "best_uses_helper_runs": sum(bool((item["helpers"] or {}).get("best_uses_helper")) for item in items),
                "ideas_never_attempted": sum(item["ideas_without_attempts"] for item in items),
                "routes_tried": _stats([len(item.get("routes") or []) for item in items]),
                "credited_routes": _stats(
                    [(item.get("route_progress") or {}).get("credited_routes") for item in items]
                ),
                "explored_routes": _stats(
                    [(item.get("route_progress") or {}).get("explored_routes") for item in items]
                ),
                "new_state_share": _stats(
                    [(item.get("route_progress") or {}).get("new_state_share") for item in items]
                ),
                "single_route_runs": sum(len(item.get("routes") or []) <= 1 for item in items),
                "tool_errors": sum(item["tool_errors"] or 0 for item in items),
                "cache_reuse_pct": _stats([item["cache_reuse_pct"] for item in items]),
                "bookkeeping_and_rejected_pct": _stats([item["bookkeeping_and_rejected_pct"] for item in items]),
                "spent_usd": {
                    **(_stats([item["spent_usd"] or 0 for item in items]) or {}),
                    "total": round(sum(item["spent_usd"] or 0 for item in items), 6),
                },
                "stop_reasons": {
                    reason: sum(item["stop_reason"] == reason for item in items)
                    for reason in sorted({str(item["stop_reason"]) for item in items})
                },
                "packet_matches": all(item["packet_matches"] for item in items),
            }
        )
    return {
        "identical_packets": all(item["packet_matches"] for item in runs),
        "expected_packets": expected,
        "groups": table,
        "runs": runs,
        "total_cost_usd": round(sum(item["spent_usd"] or 0 for item in runs), 6),
    }


def render(report: dict) -> str:
    def span(stats: dict | None, fmt: str = "{:g}") -> str:
        return "none" if not stats else "/".join(fmt.format(stats[key]) for key in ("min", "median", "max"))

    lines = [
        f"campaign: {len(report['runs'])} runs, spent ${report['total_cost_usd']:.4f}; "
        f"identical packets: {report['identical_packets']}"
    ]
    for g in report["groups"]:
        lines += [
            f"{g['row']} | {g['model']} | n={g['replicates']} (verified {g['verified_runs']})",
            f"  best-verified proxy min/median/max: {span(g['best_proxy'])}",
            f"  helper discovery: {g['helper_runs']} runs declared helpers, {g['best_uses_helper_runs']} in the best candidate",
            f"  routes tried per run min/median/max: {span(g['routes_tried'])}; runs with a single route: {g['single_route_runs']}",
            f"  route depth credited/explored min/median/max: {span(g['credited_routes'])} / {span(g['explored_routes'])}; "
            f"new-goal-state share: {span(g['new_state_share'], '{:.2f}')}",
            f"  ideas never attempted: {g['ideas_never_attempted']}; tool errors: {g['tool_errors']}",
            f"  cache reuse %: {span(g['cache_reuse_pct'])}; bookkeeping+rejected %: {span(g['bookkeeping_and_rejected_pct'])}",
            f"  spend per problem min/median/max: {span(g['spent_usd'], '${:.4f}')} (total ${g['spent_usd']['total']:.4f})",
            f"  stop reasons: {g['stop_reasons']}",
        ]
    skipped = lean_unhealthy_rows(report["runs"])
    if skipped:
        lines.append(
            f"LEAN UNHEALTHY: {len(skipped)} run(s) stopped lean_unhealthy (skipped or cut short): "
            + ", ".join(f"{run['run_id']} (${run['spent_usd'] or 0:.4f})" for run in skipped)
        )
    unreachable = provider_unreachable_rows(report["runs"])
    if unreachable:
        lines.append(
            f"PROVIDER UNREACHABLE (rerun): {len(unreachable)} run(s): "
            + ", ".join(f"{run['run_id']} (${run['spent_usd'] or 0:.4f})" for run in unreachable)
        )
    alarmed = [run for run in report["runs"] if (run.get("lean") or {}).get("alarm") and run not in skipped]
    if alarmed:
        lines.append("LEAN ALARM (timeout rate above 20%): " + ", ".join(run["run_id"] for run in alarmed))
    return "\n".join(lines) + "\n"


def lean_unhealthy_rows(runs: list[dict]) -> list[dict]:
    return [
        run for run in runs if run.get("stop_reason") == "lean_unhealthy" or run.get("exit_code") == LEAN_UNHEALTHY_EXIT
    ]


def provider_unreachable_rows(runs: list[dict]) -> list[dict]:
    return [run for run in runs if run.get("stop_reason") == "provider_unreachable"]


# ---- housekeeping between runs --------------------------------------------------------------------------------------


def mem_available_gb() -> float | None:
    with suppress(OSError, ValueError):
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    return None


def read_session_info(directory: Path) -> dict:
    """Legacy run directories do not own or record the machine-wide Lean service."""
    return {}


def proc_comm(pid: int) -> str | None:
    with suppress(OSError):
        return Path(f"/proc/{pid}/comm").read_text().strip()
    return None


def proc_cmdline(pid: int) -> str:
    with suppress(OSError):
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    return ""


def proc_alive(pid: int) -> bool:
    """Exists and is not a zombie."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def recorded_pids(directory: Path) -> tuple[list[int], list[int]]:
    """(pids, pgids) the run's session record names: the daemon, its workers and their process groups."""
    info = read_session_info(directory)
    pids, pgids = [], []
    for key, bucket in (("pid", pids), ("pids", pids), ("pgids", pgids)):
        value = info.get(key)
        for item in value if isinstance(value, list) else [value]:
            if item is not None:
                with suppress(TypeError, ValueError):
                    bucket.append(int(item))
    return sorted(set(pids)), sorted(set(pgids))


def ours(pid: int, directory: Path, comm_fn=proc_comm, cmdline_fn=proc_cmdline) -> bool:
    """A recorded pid may have been reused: only Lean/lake or a run-scoped process qualifies."""
    comm = comm_fn(pid)
    if comm is None:
        return False
    if comm in ("lean", "lake"):
        return True
    return (
        comm.startswith("python") and str(directory) in cmdline_fn(pid) and "arena.lean_session" not in cmdline_fn(pid)
    )


def lingering(directory: Path, comm_fn=proc_comm, cmdline_fn=proc_cmdline, alive_fn=proc_alive) -> list[int]:
    """Recorded Lean/lake/daemon pids of a finished run that are still alive."""
    pids, _ = recorded_pids(directory)
    return [pid for pid in pids if alive_fn(pid) and ours(pid, directory, comm_fn, cmdline_fn)]


def reap_run(
    directory: Path,
    *,
    comm_fn=proc_comm,
    cmdline_fn=proc_cmdline,
    alive_fn=proc_alive,
    kill_fn=os.kill,
    killpg_fn=os.killpg,
    sleep_fn=time.sleep,
    grace: float = 5.0,
) -> int:
    """Make sure the run's session daemon and every recorded Lean/lake process are gone. Only exact recorded PIDs
    and PGIDs are signalled, and only when /proc says they are still Lean, lake or that run's daemon. Returns how
    many leftovers it had to signal (0 for a run that cleaned up after itself)."""
    pids, pgids = recorded_pids(directory)

    def mine(pid: int) -> bool:
        return alive_fn(pid) and ours(pid, directory, comm_fn, cmdline_fn)

    live = [pid for pid in pids if mine(pid)]
    # A process group goes only when its leader is itself one of ours (the daemon and each worker lead their own).
    groups = [pgid for pgid in pgids if mine(pgid)]
    found = len(live) or len(groups)
    for number in (signal.SIGTERM, signal.SIGKILL):
        if not live and not groups:
            break
        for pgid in groups:
            with suppress(ProcessLookupError, PermissionError):
                killpg_fn(pgid, number)
        for pid in live:
            if mine(pid):
                with suppress(ProcessLookupError, PermissionError):
                    kill_fn(pid, number)
        if number == signal.SIGTERM:
            sleep_fn(grace)
            live, groups = [pid for pid in live if mine(pid)], [pgid for pgid in groups if mine(pgid)]
    return found


def sweep_candidate_dirs(root: Path, newer_than: float) -> int:
    """Remove temporary cold-compile directories (`arena-*`) a finished run left behind. Only called when no run is
    in flight, and only for directories created since the campaign started, so nothing else's is touched."""
    removed = 0
    with suppress(OSError):
        for item in root.glob("arena-*"):
            with suppress(OSError):
                if item.is_dir() and item.stat().st_mtime >= newer_than:
                    shutil.rmtree(item)
                    removed += 1
    return removed


class Housekeeping:
    """Cleanup after every run and a wait before the next: nothing of a finished run may still be using Lean or
    memory when another starts (the SharedDrive is NTFS/FUSE; stray Lean imports slow every later check)."""

    def __init__(
        self,
        min_free_gb: float = MIN_FREE_GB,
        max_wait: float = CLEANUP_WAIT_S,
        started: float | None = None,
        evaluations: Path = EVALUATIONS,
        *,
        mem_fn=mem_available_gb,
        reap_fn=reap_run,
        lingering_fn=lingering,
        sweep_fn=sweep_candidate_dirs,
        sleep_fn=time.sleep,
        now_fn=time.monotonic,
        log=print,
    ):
        self.min_free_gb, self.max_wait, self.evaluations = min_free_gb, max_wait, evaluations
        self.started = time.time() if started is None else started
        self.mem_fn, self.reap_fn, self.lingering_fn, self.sweep_fn = mem_fn, reap_fn, lingering_fn, sweep_fn
        self.sleep_fn, self.now_fn, self.log = sleep_fn, now_fn, log
        self.lock = threading.Lock()
        self.in_flight = 0
        self.finished: list[Path] = []

    def say(self, message: str) -> None:
        self.log(f"{time.strftime('%H:%M:%S')} {message}", flush=True) if self.log is print else self.log(message)

    def before_run(self, run_id: str) -> None:
        """Wait (printing progress, at most `max_wait`) until no Lean process of a finished run remains and, when
        nothing else is running, MemAvailable is at least `min_free_gb`."""
        deadline = self.now_fn() + self.max_wait
        last = None
        while True:
            with self.lock:
                alone = self.in_flight == 0
                finished = list(self.finished)
            stray = [pid for directory in finished for pid in self.lingering_fn(directory)]
            free = self.mem_fn()
            low = alone and free is not None and free < self.min_free_gb
            shown = "?" if free is None else f"{free:.1f}"
            if not stray and not low:
                break
            if self.now_fn() >= deadline:
                self.say(
                    f"cleanup: starting {run_id} anyway after {self.max_wait:.0f}s "
                    f"(Lean pids left {stray}, MemAvailable {shown} GB)"
                )
                break
            state = (tuple(stray), low)
            if state != last:
                self.say(
                    f"waiting before {run_id}: {len(stray)} Lean process(es) of finished runs still alive, "
                    f"MemAvailable {shown} GB (need {self.min_free_gb:g})"
                )
                last = state
            self.sleep_fn(5)
        with self.lock:
            self.in_flight += 1

    def after_run(self, run_id: str, directory: Path) -> None:
        reaped = self.reap_fn(directory)
        with self.lock:
            self.in_flight -= 1
            self.finished.append(directory)
            idle = self.in_flight == 0
        swept = self.sweep_fn(self.evaluations, self.started) if idle else 0
        free = self.mem_fn()
        self.say(
            f"cleanup {run_id}: reaped {reaped}"
            + (f", removed {swept} temporary dir(s)" if swept else "")
            + f", MemAvailable {'?' if free is None else f'{free:.1f}'} GB"
        )


def execute(
    spec: dict,
    limit: float,
    thinking: str,
    passthrough: list[str],
    logs: Path,
    expected: str,
    run_fn=subprocess.run,
    summary_fn=None,
    housekeeping: Housekeeping | None = None,
) -> dict:
    if summary_fn is None:
        from arena.summary import build_summary as summary_fn
    directory = RUNS / spec["run_id"]
    if housekeeping:
        housekeeping.before_run(spec["run_id"])
    print(f"{time.strftime('%H:%M:%S')} start  {spec['run_id']}", flush=True)
    try:
        with (logs / f"{spec['run_id']}.log").open("w") as log:
            proc = run_fn(
                command(spec, limit, thinking, passthrough), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True
            )
    finally:
        if housekeeping:
            housekeeping.after_run(spec["run_id"], directory)
    print(f"{time.strftime('%H:%M:%S')} done   {spec['run_id']} (exit {proc.returncode})", flush=True)
    if proc.returncode == LEAN_UNHEALTHY_EXIT:
        print(
            f"{time.strftime('%H:%M:%S')} skipped {spec['run_id']}: Lean unhealthy, no model spend; "
            f"continuing with the next row",
            flush=True,
        )
    config_path = directory / "run-config.json"
    packet_sha = json.loads(config_path.read_text()).get("packet_sha256") if config_path.exists() else None
    summary = summary_fn(directory) if directory.exists() else None
    return run_row(spec, summary, proc.returncode, packet_sha, expected, directory if directory.exists() else None)


@dataclass(frozen=True)
class CampaignOptions:
    prefix: str
    preset: str | None = None
    rows: str | None = None
    models: str | None = None
    replicates: int | None = None
    limit_usd: float | None = None
    jobs: int | None = None
    thinking: str = CONFIG["thinking"]["default"]
    min_free_gb: float = MIN_FREE_GB
    cleanup_wait: float = CLEANUP_WAIT_S
    skip_preflight: bool = False
    dry_run: bool = False
    json: bool = False


def cli_execute(options: CampaignOptions, passthrough: tuple[str, ...] = ()) -> int:
    """Execute a typed campaign request, preserving extra run options after ``--``."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(line_buffering=True)
    args = SimpleNamespace(**asdict(options))
    passthrough_tokens = list(passthrough)
    if args.preset is not None and args.preset not in PRESETS:
        print(f"unknown preset {args.preset!r}; choose from {', '.join(sorted(PRESETS))}", file=sys.stderr)
        return 2
    preset = PRESETS[args.preset] if args.preset else {}
    for name, default in (("rows", None), ("models", None), ("replicates", 3), ("limit_usd", 0.5), ("jobs", 1)):
        if getattr(args, name) is None:
            value = preset.get("cap" if name == "limit_usd" else name, default)
            setattr(args, name, ",".join(value) if isinstance(value, list) else value)
    if not args.rows or not args.models:
        print("--rows and --models are required unless --preset supplies them", file=sys.stderr)
        return 2
    if not 0 < args.limit_usd <= MAX_LIMIT_USD:
        print(f"--limit-usd must be above 0 and at most {MAX_LIMIT_USD:g}", file=sys.stderr)
        return 2
    if args.jobs < 1:
        print("--jobs must be at least 1", file=sys.stderr)
        return 2
    rows, models = [r for r in args.rows.split(",") if r], [m for m in args.models.split(",") if m]
    try:
        specs = plan(args.prefix, rows, models, args.replicates)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    print(
        f"{len(specs)} runs ({len(rows)} rows x {len(models)} models x {args.replicates} replicates, {args.jobs} at a time); "
        f"limit ${args.limit_usd:g} each; planned spend ${worst_case_usd(specs, args.limit_usd):.2f}"
    )
    for spec in specs:
        planned = command(spec, args.limit_usd, args.thinking, passthrough_tokens)
        print("  arena run " + shlex.join(planned[4:]))
    if args.dry_run:
        return 0
    clashes = [spec["run_id"] for spec in specs if (RUNS / spec["run_id"]).exists()]
    if clashes:
        print(f"run IDs already exist: {', '.join(clashes)}", file=sys.stderr)
        return 2
    try:
        expected = check_packets(rows)
        print("preflight:", check_preflight(models, args.skip_preflight))
    except CampaignAbort as error:
        print(f"aborted before any paid run: {error}", file=sys.stderr)
        return 1
    out = RUNS / f"{args.prefix}-campaign"
    out.mkdir(parents=True)
    housekeeping = Housekeeping(args.min_free_gb, args.cleanup_wait)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        runs = list(
            pool.map(
                lambda spec: execute(
                    spec,
                    args.limit_usd,
                    args.thinking,
                    passthrough_tokens,
                    out,
                    expected[spec["row"]],
                    housekeeping=housekeeping,
                ),
                specs,
            )
        )
    report = {
        "limit_usd": args.limit_usd,
        "prefix": args.prefix,
        **aggregate(runs, expected),
        "lean_unhealthy_runs": [run["run_id"] for run in lean_unhealthy_rows(runs)],
        "provider_unreachable_runs": [run["run_id"] for run in provider_unreachable_rows(runs)],
    }
    (out / "campaign.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "campaign.txt").write_text(render(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        table = Table(title=f"Campaign {args.prefix}")
        table.add_column("Row")
        table.add_column("Model")
        table.add_column("Runs")
        table.add_column("Verified")
        table.add_column("Spend")
        for group in report["groups"]:
            table.add_row(
                group["row"],
                group["model"],
                str(group["replicates"]),
                str(group["verified_runs"]),
                f"${group['spent_usd']['total']:.4f}",
            )
        Console().print(table)
    if not report["identical_packets"]:
        print("Packets differ between runs; the comparison is not valid.", file=sys.stderr)
        return 1
    return 0
