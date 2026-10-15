#!/usr/bin/env python3
"""Run a paid comparison campaign: theorem rows x models x N replicates, `--jobs` at a time.

Each row gets one certified kickoff packet shared by all its runs. Nothing is spent unless a
passing Langfuse preflight receipt covers every model (run here, or a fresh one) and every row's
packet certifies with its mandatory sections. `--dry-run` prints the plan and worst-case cost.

    python arena campaign --prefix v6c1 --rows Core.InitsUpdatesComm,fundamental_theorem_of_variational_calculus' \\
        --models deepseek-v4.1-flash --limit-usd 0.10 --replicates 1

`--preset v6-matrix` is the standing comparison: the configured models x the Core and PhysLib rows x 3 replicates at the preset's spend limit.

Arguments after `--` are passed to every run.
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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rich.console import Console
from rich.table import Table

from arena import codex_limits, engine, lean_session, scheduler
from arena import models as model_config
from arena.cli import live
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
MAX_LIMIT_USD = 2.5  # keep equal to MAX_LIMIT_USD in packages/arena-pi/extensions/spend.ts
LEAN_UNHEALTHY_EXIT = 75  # keep equal to arena.lean_health.EXIT_CODE


class CampaignAbort(Exception):
    """A pre-spend gate failed; nothing was run."""


class NotLaunched(Exception):
    """The operator stopped the campaign before this run was launched."""


def stamped(message: str) -> str:
    return f"{time.strftime('%H:%M:%S')} {message}"


class Progress:
    """Where campaign progress goes: the live view when one is up, else the plain lines (unchanged for pipes, tests
    and `--plain`). Each method falls back to its plain line when the view is off or has just failed."""

    def __init__(self, board: live.CampaignDisplay | None = None):
        self.board = board

    def event(self, message: str) -> None:
        """A timestamped event line (start, cleanup, done)."""
        if not (self.board and self.board.log(message)):
            print(stamped(message), flush=True)

    def note(self, message: str) -> None:
        if not (self.board and self.board.log(message, stamp=False)):
            print(message, flush=True)

    def step_begin(self, key: str, label: str, detail: str, plain: str | None, **match) -> None:
        if not (self.board and self.board.step_begin(key, label, detail, **match)) and plain is not None:
            print(plain, flush=True)

    def step_end(self, key: str, ok: bool, detail: str, plain: str | None) -> None:
        if not (self.board and self.board.step_end(key, ok, detail)) and plain is not None:
            print(plain, flush=True)

    @property
    def showing(self) -> bool:
        return self.board is not None and self.board.active

    def plain(self, message: str) -> None:
        """A line only the plain output has (the live view shows the same thing as a step or on the board)."""
        if not self.showing:
            print(message, flush=True)

    def close(self) -> None:
        """Stop the live view (last frame drawn, cursor back); later output is plain."""
        board, self.board = self.board, None
        if board is not None:
            board.stop()


class StopControl:
    """Operator stop while runs are in flight (Ctrl+C, SIGTERM or SIGHUP). The first launches nothing more and sends
    each running `arena run` one SIGINT, which it treats as a clean stop: Pi is asked to stop, cost.json and
    summary.json are written. The second sends another, on which each run kills its Pi's process group at once and
    still writes its summary. Any further one kills each run's own process group (its exact PGID: runs are started
    in their own session, so the terminal's Ctrl+C reaches only the campaign)."""

    SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

    def __init__(self, progress: Progress | None = None, kill_fn=os.killpg):
        self.progress = progress or Progress()
        self.kill_fn = kill_fn
        self.requests = 0
        self.event = threading.Event()
        self.children: dict[int, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.previous: dict[int, object] = {}

    @property
    def requested(self) -> bool:
        return self.event.is_set()

    def install(self) -> None:
        for number in self.SIGNALS:
            with suppress(ValueError):  # not the main thread: nothing to install
                self.previous[number] = signal.signal(number, self.handle)

    def restore(self) -> None:
        for number, handler in self.previous.items():
            with suppress(ValueError, TypeError):
                signal.signal(number, handler)  # ty: ignore[invalid-argument-type]
        self.previous.clear()

    def track(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.children[process.pid] = process
        if self.requested:  # the stop came while it was being launched
            with suppress(OSError):
                process.send_signal(signal.SIGINT)

    def untrack(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.children.pop(process.pid, None)

    def running(self) -> list[subprocess.Popen]:
        with self.lock:
            children = list(self.children.values())
        return [process for process in children if process.poll() is None]

    def handle(self, _signum=None, _frame=None) -> None:
        self.requests += 1
        self.event.set()
        running = self.running()
        if self.requests == 1:
            message = (
                f"stop requested: no new runs; asking {len(running)} running run(s) to stop cleanly and write their "
                "summaries (Ctrl+C again to force)"
            )
        elif self.requests == 2:
            message = f"forcing: {len(running)} run(s) kill their Pi now (Ctrl+C again kills the runs themselves)"
        else:
            message = f"killing {len(running)} run(s) by process group"
        if self.progress.board is not None:
            self.progress.board.set_notice(message)
        self.progress.event(message)
        for process in running:
            with suppress(OSError):
                if self.requests <= 2:
                    process.send_signal(signal.SIGINT)
                elif process.poll() is None:
                    self.kill_fn(process.pid, signal.SIGKILL)


def run_child(command: list[str], stop: StopControl | None = None, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` for one `arena run`, in its own session so only the campaign sees the terminal's Ctrl+C and
    decides what each run gets (see StopControl)."""
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True, **kwargs) as process:
        if stop is not None:
            stop.track(process)
        try:
            code = process.wait()
        finally:
            if stop is not None:
                stop.untrack(process)
    return subprocess.CompletedProcess(command, code)


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)[:limit].strip("-._") or "row"


def plan(prefix: str, rows: list[str], models: list[str], replicates: int, group_of=None) -> list[dict]:
    """Plan row-major specs, optionally grouping rows by a stable cache key."""
    if replicates < 1:
        raise ValueError("--replicates must be at least 1")
    if not rows or len(set(rows)) != len(rows) or not models or len(set(models)) != len(models):
        raise ValueError("rows and models must be non-empty and distinct")
    bad = [model for model in models if model not in MODELS]
    if bad:
        raise ValueError(f"unknown models {bad}; choose from {', '.join(MODELS)}")
    ordered_rows = rows if group_of is None else scheduler.plan_order(rows, group_of)
    specs = [
        {"row": row, "model": model, "replicate": k, "run_id": f"{prefix}-{slug(row)}-{slug(model)}-r{k}"}
        for row in ordered_rows
        for k in range(1, replicates + 1)
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


def check_packets(rows: list[str], packet_fn=None, progress: Progress | None = None) -> dict[str, str]:
    """Row -> sha256 of its certified packet. Any uncertifiable row aborts the campaign."""
    if packet_fn is None:
        from arena.campaign import packet as packet_fn
    progress = progress or Progress()
    hashes, failures = {}, []
    for index, row in enumerate(rows, 1):
        name, key = f"packet {index}/{len(rows)} {row}", f"packet:{row}"
        progress.step_begin(
            key,
            name,
            "building (Lean context; cached rows are quick, new rows take minutes)",
            f"{name}: building (Lean context; cached rows are quick, new rows take minutes)",
            status="building",
            row=row,
        )
        started = time.monotonic()
        try:
            text = packet_fn(row)
        except Exception as error:
            failures.append(f"{row}: {error}")
            progress.step_end(key, False, str(error), f"{name}: FAILED after {time.monotonic() - started:.0f}s")
            continue
        hashes[row] = hashlib.sha256(text.encode()).hexdigest()
        progress.step_end(
            key,
            True,
            f"certified ({len(text):,} chars)",
            f"{name}: certified in {time.monotonic() - started:.0f}s ({len(text):,} chars)",
        )
    if failures:
        raise CampaignAbort("packet certification failed: " + "; ".join(failures))
    return hashes


def check_indexes(rows: list[str], path_fn=None) -> None:
    """Every row needs its measure-version declaration index; search reads nothing else."""
    if path_fn is None:
        from arena.index import index_path as path_fn
    missing = [row for row in rows if path_fn(row) is None]
    if missing:
        raise CampaignAbort(
            f"declaration index missing for {', '.join(missing)}; build it with: "
            + "; ".join(f"uv run arena index build {row}" for row in missing)
        )


def check_preflight(
    models: list[str],
    skip: bool,
    block_fn=None,
    receipt_fn=None,
    run_fn=None,
    max_age_hours: float = RECEIPT_MAX_AGE_HOURS,
    now_fn=time.time,
    progress: Progress | None = None,
) -> str:
    """Return how the gate was satisfied: 'skipped', 'fresh receipt' or 'ran preflight'. With a live view each
    model is a check step and the preflight's own output is captured into the view's log."""
    progress = progress or Progress()
    for model in models:
        progress.step_begin(
            f"preflight:{model}",
            f"preflight {model}",
            "receipt or one cheap traced request",
            None,
            status="preflight",
            model=model,
        )
    try:
        how = _preflight_gate(models, skip, block_fn, receipt_fn, run_fn, max_age_hours, now_fn, progress)
    except CampaignAbort as error:
        for model in models:
            progress.step_end(f"preflight:{model}", False, str(error), None)
        raise
    for model in models:
        progress.step_end(f"preflight:{model}", True, how, None)
    return how


def _preflight_gate(models, skip, block_fn, receipt_fn, run_fn, max_age_hours, now_fn, progress: Progress) -> str:
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
            preflight = [sys.executable, "-m", "arena.cli", "preflight", "--models", ",".join(models)]
            if not progress.showing:
                return subprocess.run(preflight, cwd=ROOT).returncode
            # A child writing to the terminal would tear the live view: its lines go through the view instead.
            with subprocess.Popen(
                preflight,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ) as process:
                assert process.stdout is not None
                for line in process.stdout:
                    progress.note(line.rstrip("\n"))
                return process.wait()

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


def requeue_specs(specs: list[dict], results: list[dict | None]) -> list[dict]:
    """One retry spec for each run that stopped Lean-unhealthy without spending on the model."""
    return [
        {**spec, "run_id": f"{spec['run_id']}-retry"}
        for spec, row in zip(specs, results, strict=True)
        if row is not None
        and not row.get("spent_usd")
        and (row.get("exit_code") == LEAN_UNHEALTHY_EXIT or row.get("stop_reason") == "lean_unhealthy")
    ]


# ---- subscription models and their fallback ------------------------------------------------------------------------

# Providers billed through a usage-capped subscription (Pi's built-in openai login), not per token.
SUBSCRIPTION_PROVIDERS = ("openai",)
CODEX_MAX_PCT = 90.0
# A row moved to the fallback model starts at $0 with this limit, whatever the subscription model's limit was.
FALLBACK_LIMIT_USD = 0.5


def on_subscription(model: str) -> bool:
    return model_config.provider(model) in SUBSCRIPTION_PROVIDERS


def fallback_spec(spec: dict, fallback: str, limit: float = FALLBACK_LIMIT_USD) -> dict:
    """The same row and replicate on the fallback model, under its own run id and its own spend limit."""
    run_id = spec["run_id"].replace(f"-{slug(spec['model'])}-", f"-{slug(fallback)}-", 1)
    if run_id == spec["run_id"]:
        run_id = f"{run_id}-{slug(fallback)}"
    return {**spec, "model": fallback, "run_id": run_id, "limit_usd": limit}


def subscription_room(max_pct: float, limits_fn=codex_limits.read_limits) -> tuple[bool, str]:
    """Whether the subscription has room for one more run: both windows below max_pct. No reading means no room."""
    limits = limits_fn()
    if limits is None:
        return False, "Codex limits unavailable"
    reading = f"Codex 5h {limits.five_hour_pct:.0f}%, weekly {limits.weekly_pct:.0f}%"
    return limits.five_hour_pct < max_pct and limits.weekly_pct < max_pct, reading


def usage_limit_specs(
    specs: list[dict], results: list[dict | None], fallback: str | None, limit: float = FALLBACK_LIMIT_USD
) -> list[dict]:
    """The fallback run for each subscription run the provider stopped for a spent usage window."""
    if not fallback:
        return []
    return [
        fallback_spec(spec, fallback, limit)
        for spec, row in zip(specs, results, strict=True)
        if row is not None and row.get("stop_reason") == "usage_limit" and spec["model"] != fallback
    ]


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


def service_gb(status_fn=None) -> float:
    """Return memory held by shared Lean workers, or zero when the service is unavailable."""
    status = (
        status_fn()
        if status_fn is not None
        else lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 5)
    )
    if not status or not status.get("ok"):
        return 0.0
    return sum(float(server.get("gb", 0.0)) for server in status.get("servers", []))


def close_idle_servers(request_fn=None) -> list[str]:
    """Close every Lean project no live run names; [] when the service is unavailable."""
    reply = (request_fn or lean_session.request)({"op": "close_idle", "protocol": lean_session.PROTOCOL}, 30)
    return list(reply.get("closed", [])) if reply and reply.get("ok") else []


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
    """A recorded pid may have been reused: only Lean or lake qualifies. Runs own no Python helper any more (the
    Lean service is machine-wide and never a run's to stop)."""
    del directory, cmdline_fn
    return comm_fn(pid) in ("lean", "lake")


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
        service_gb_fn=service_gb,
        close_idle_fn=close_idle_servers,
        reap_fn=reap_run,
        lingering_fn=lingering,
        sweep_fn=sweep_candidate_dirs,
        sleep_fn=time.sleep,
        now_fn=time.monotonic,
        log=print,
    ):
        self.min_free_gb, self.max_wait, self.evaluations = min_free_gb, max_wait, evaluations
        self.started = time.time() if started is None else started
        self.mem_fn, self.service_gb_fn, self.close_idle_fn = mem_fn, service_gb_fn, close_idle_fn
        self.reap_fn, self.lingering_fn, self.sweep_fn = reap_fn, lingering_fn, sweep_fn
        self.sleep_fn, self.now_fn, self.log = sleep_fn, now_fn, log
        self.lock = threading.Lock()
        self.in_flight = 0
        self.finished: list[Path] = []
        self.cancel: threading.Event | None = None  # set: stop waiting (the operator stopped the campaign)

    def say(self, message: str) -> None:
        self.log(f"{time.strftime('%H:%M:%S')} {message}", flush=True) if self.log is print else self.log(message)

    def before_run(self, run_id: str) -> None:
        """Wait (printing progress) until no Lean process of a finished run remains and MemAvailable is at least
        `min_free_gb`. Alone, idle Lean service memory counts as free (closing it makes room) and the wait ends after
        `max_wait`; beside a live run only real MemAvailable counts and the wait has no deadline, because that run
        finishing is what frees memory (v7-check3 lost Binius to a second run admitted with 7.8 GB)."""
        deadline = self.now_fn() + self.max_wait
        last = None
        while True:
            with self.lock:
                alone = self.in_flight == 0
                finished = list(self.finished)
            stray = [pid for directory in finished for pid in self.lingering_fn(directory)]
            free = self.mem_fn()
            service = self.service_gb_fn() if alone else 0.0
            low = free is not None and free + service < self.min_free_gb
            shown = "?" if free is None else f"{free:.1f}"
            if (not stray and not low) or (self.cancel is not None and self.cancel.is_set()):
                break
            if not alone:
                deadline = self.now_fn() + self.max_wait
            elif self.now_fn() >= deadline:
                self.say(
                    f"cleanup: starting {run_id} anyway after {self.max_wait:.0f}s "
                    f"(Lean pids left {stray}, MemAvailable {shown} GB, Lean service {service:.1f} GB)"
                )
                break
            state = (tuple(stray), low, alone)
            if state != last:
                self.say(
                    f"waiting before {run_id}: {len(stray)} Lean process(es) of finished runs still alive, "
                    f"MemAvailable {shown} GB"
                    + (f" + idle Lean service {service:.1f} GB" if alone else " beside a live run")
                    + f" (need {self.min_free_gb:g} GB)"
                )
                last = state
            if alone and low:
                self.close_idle_fn()
            self.sleep_fn(5)
        with self.lock:
            self.in_flight += 1

    def release(self) -> None:
        """A run that `before_run` admitted but was never launched."""
        with self.lock:
            self.in_flight -= 1

    def after_run(self, run_id: str, directory: Path) -> None:
        reaped = self.reap_fn(directory)
        closed = self.close_idle_fn()
        with self.lock:
            self.in_flight -= 1
            self.finished.append(directory)
            idle = self.in_flight == 0
        swept = self.sweep_fn(self.evaluations, self.started) if idle else 0
        free = self.mem_fn()
        self.say(
            f"cleanup {run_id}: reaped {reaped}"
            + (f", closed Lean {', '.join(Path(name).name for name in closed)}" if closed else "")
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
    run_fn: Callable[..., Any] = subprocess.run,
    summary_fn=None,
    housekeeping: Housekeeping | None = None,
    prewarm: scheduler.Prewarm | None = None,
    sampler: scheduler.ResourceSampler | None = None,
    on_finished=None,
    progress: Progress | None = None,
    stop: StopControl | None = None,
) -> dict:
    """One run; NotLaunched when the operator stopped the campaign before it started."""
    if summary_fn is None:
        from arena.summary import build_summary as summary_fn
    progress = progress or Progress()
    directory = RUNS / spec["run_id"]
    if housekeeping:
        housekeeping.before_run(spec["run_id"])
    if stop is not None and stop.requested:
        if housekeeping:
            housekeeping.release()
        raise NotLaunched(spec["run_id"])
    started = time.monotonic()
    if prewarm:
        prewarm.started(spec)
    if sampler:
        sampler.run_started()
    progress.event(f"start  {spec['run_id']}")
    try:
        with (logs / f"{spec['run_id']}.log").open("w") as log:
            proc = run_fn(
                command(spec, spec.get("limit_usd", limit), thinking, passthrough),
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                **({} if stop is None else {"stop": stop}),
            )
    finally:
        elapsed = time.monotonic() - started
        if sampler:
            sampler.run_finished()
        if prewarm:
            prewarm.finished(spec, elapsed)
        if on_finished:
            on_finished(spec)
        if housekeeping:
            housekeeping.after_run(spec["run_id"], directory)
    verb = "stopped" if stop is not None and stop.requested and proc.returncode != 0 else "done  "
    progress.event(f"{verb} {spec['run_id']} (exit {proc.returncode})")
    if proc.returncode == LEAN_UNHEALTHY_EXIT:
        progress.event(f"skipped {spec['run_id']}: Lean unhealthy, no model spend; continuing with the next row")
    config_path = directory / "run-config.json"
    packet_sha = json.loads(config_path.read_text()).get("packet_sha256") if config_path.exists() else None
    summary = summary_fn(directory) if directory.exists() else None
    return run_row(spec, summary, proc.returncode, packet_sha, expected, directory if directory.exists() else None)


@dataclass(frozen=True, kw_only=True)  # keyword-only: tokens after `--` go to the run, never to `preset`
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
    prewarm_minutes: float = 0  # >0 opens the next row's Lean early; off: only live runs hold memory
    fallback_model: str | None = None  # runs a subscription model's row when its usage window is (nearly) spent
    codex_max_pct: float = CODEX_MAX_PCT
    fallback_limit_usd: float = FALLBACK_LIMIT_USD  # the fallback run's own limit; it starts from $0
    skip_preflight: bool = False
    dry_run: bool = False
    json: bool = False
    plain: bool = False


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
    if args.prewarm_minutes < 0:
        print("--prewarm-minutes must be at least 0", file=sys.stderr)
        return 2
    rows, models = [r for r in args.rows.split(",") if r], [m for m in args.models.split(",") if m]
    if not 0 < args.fallback_limit_usd <= MAX_LIMIT_USD:
        print(f"--fallback-limit-usd must be above 0 and at most {MAX_LIMIT_USD:g}", file=sys.stderr)
        return 2
    if args.fallback_model is not None and args.fallback_model not in MODELS:
        print(f"unknown --fallback-model {args.fallback_model!r}; choose from {', '.join(MODELS)}", file=sys.stderr)
        return 2
    try:
        specs = plan(
            args.prefix,
            rows,
            models,
            args.replicates,
            group_of=lambda name: scheduler.row_group(engine.problem(name)),
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    overview = campaign_plan(args, rows, models, specs, passthrough_tokens)
    if live.enabled(args.plain):
        # The live view shows the plan itself; a dry run shows it once, with every command.
        if args.dry_run:
            Console().print(live.plan_panel(args.prefix, overview, commands=None))
    else:
        print(
            f"{len(specs)} runs ({len(rows)} rows x {len(models)} models x {args.replicates} replicates, {args.jobs} at a time); "
            f"limit ${args.limit_usd:g} each; planned spend ${worst_case_usd(specs, args.limit_usd):.2f}"
        )
        for line in overview.commands:
            print("  " + line)
    if args.dry_run:
        return 0
    clashes = [spec["run_id"] for spec in specs if (RUNS / spec["run_id"]).exists()]
    if clashes:
        print(f"run IDs already exist: {', '.join(clashes)}", file=sys.stderr)
        return 2
    lock = scheduler.CampaignLock()
    try:
        lock_info = lock.acquire({"prefix": args.prefix, "argv": sys.argv})
    except scheduler.CampaignLocked as error:
        print(error, file=sys.stderr)
        return 1
    try:
        return _run_campaign(args, rows, models, specs, passthrough_tokens, lock_info)
    finally:
        lock.release()


def campaign_plan(
    args, rows: list[str], models: list[str], specs: list[dict], passthrough: list[str]
) -> live.CampaignPlan:
    return live.CampaignPlan(
        runs=len(specs),
        rows=len(rows),
        models=len(models),
        replicates=args.replicates,
        jobs=args.jobs,
        limit_usd=args.limit_usd,
        planned_usd=worst_case_usd(specs, args.limit_usd),
        commands=[
            "arena run " + shlex.join(command(spec, args.limit_usd, args.thinking, passthrough)[4:]) for spec in specs
        ],
    )


def _run_campaign(
    args, rows, models, specs, passthrough_tokens, lock_info, run_fn=run_child, console: Console | None = None
) -> int:
    """Pre-spend checks, then the runs, then the report. With a terminal (or `console`) everything shows in one
    live view: plan, check steps, run board; event lines print above it."""
    board = live.start_campaign(
        args.prefix,
        specs,
        RUNS,
        args.limit_usd,
        plan=campaign_plan(args, rows, models, specs, passthrough_tokens),
        plain=getattr(args, "plain", False),
        console=console,
    )
    progress = Progress(board)
    stop = StopControl(progress)
    try:
        return _campaign_body(args, rows, models, specs, passthrough_tokens, lock_info, run_fn, progress, stop)
    finally:
        stop.restore()
        progress.close()


def _campaign_body(
    args, rows, models, specs, passthrough_tokens, lock_info, run_fn, progress: Progress, stop: StopControl
) -> int:
    board = progress.board
    out = RUNS / f"{args.prefix}-campaign"
    settings = {
        "prefix": args.prefix,
        "rows": rows,
        "models": models,
        "replicates": args.replicates,
        "jobs": args.jobs,
        "limit_usd": args.limit_usd,
        "thinking": args.thinking,
        "min_free_gb": args.min_free_gb,
        "cleanup_wait_s": args.cleanup_wait,
        "prewarm_minutes": args.prewarm_minutes,
        "fallback_model": getattr(args, "fallback_model", None),
        "codex_max_pct": getattr(args, "codex_max_pct", CODEX_MAX_PCT),
        "fallback_limit_usd": getattr(args, "fallback_limit_usd", FALLBACK_LIMIT_USD),
        "order": [spec["run_id"] for spec in specs],
        "started": lock_info["started"],
        "cpu_count": os.cpu_count(),
        "mem_total_gb": scheduler.mem_total_default(),
        "lock": lock_info,
    }
    try:
        check_indexes(rows)
        expected = check_packets(rows, progress=progress)
        fallback = getattr(args, "fallback_model", None)
        checked = list(dict.fromkeys([*models, *([fallback] if fallback else [])]))
        progress.plain(f"preflight: {check_preflight(checked, args.skip_preflight, progress=progress)}")
    except CampaignAbort as error:
        progress.close()
        print(f"aborted before any paid run: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if board is not None:
            board.steps_interrupted()
        progress.close()
        print("interrupted before any paid run; nothing was launched", file=sys.stderr)
        return 130
    out.mkdir(parents=True)
    campaign_path = out / "campaign.json"
    campaign_path.write_text(json.dumps({"settings": settings}, indent=2) + "\n")
    row_order = list(dict.fromkeys(spec["row"] for spec in specs))
    housekeeping = Housekeeping(args.min_free_gb, args.cleanup_wait)
    housekeeping.log = progress.event
    housekeeping.cancel = stop.event
    # From here on Ctrl+C is an operator stop (StopControl), never a KeyboardInterrupt.
    stop.install()
    sampler = scheduler.ResourceSampler()
    sampler.start()
    prewarm = (
        scheduler.Prewarm(
            row_order,
            args.replicates * len(models),
            lead_s=60 * args.prewarm_minutes,
            warm_fn=lambda name: _warm_row(name),
        )
        if args.prewarm_minutes > 0
        else None
    )
    completed: dict[str, int] = dict.fromkeys(rows, 0)
    fallback = getattr(args, "fallback_model", None)
    finished_lock = threading.Lock()
    hold = None
    stop_helpers = threading.Event()
    helper_thread = None
    try:
        row_info = [(name, scheduler.row_projects(engine.problem(name))) for name in row_order]
        try:
            socket_path = lean_session.ensure_service()
            os.environ[lean_session.ENV] = socket_path
            hold = scheduler.HoldKeeper(
                f"campaign-{args.prefix}-{os.getpid()}",
                os.getpid(),
                lambda payload, timeout: lean_session.request(payload, timeout, path=socket_path),
            )
            # Holding queued rows keeps their toolchains in memory between runs; only pre-warming needs that.
            hold.start(row_info if prewarm else [])
        except Exception as error:
            progress.note(f"Lean service hold unavailable ({error}); continuing with cold fallback")
        if prewarm:

            def poll_prewarm():
                while not stop_helpers.wait(30):
                    next_row = prewarm.due(time.monotonic())
                    if next_row:
                        try:
                            prewarm.warm_fn(next_row)
                        except Exception as error:
                            progress.note(f"pre-warm {next_row} failed: {error}")

            helper_thread = threading.Thread(target=poll_prewarm, daemon=True)
            helper_thread.start()

        def finished(spec):
            with finished_lock:
                completed[spec["row"]] += 1
                last = completed[spec["row"]] == args.replicates * len(models)
            if last and hold:
                hold.row_finished(spec["row"])

        def tracked(spec):
            if stop.requested:
                if board:
                    board.run_skipped(spec)
                return None
            if fallback and spec["model"] != fallback and on_subscription(spec["model"]):
                room, reading = subscription_room(getattr(args, "codex_max_pct", CODEX_MAX_PCT))
                if not room:
                    moved = fallback_spec(spec, fallback, getattr(args, "fallback_limit_usd", FALLBACK_LIMIT_USD))
                    progress.event(f"{spec['run_id']}: {reading}; running {moved['run_id']} on {fallback} instead")
                    if board:
                        board.run_skipped(spec)
                        board.add_run(moved)
                    spec = moved
            if board:
                board.run_started(spec)
            exit_code, launched = None, True
            try:
                row = execute(
                    spec,
                    args.limit_usd,
                    args.thinking,
                    passthrough_tokens,
                    out,
                    expected[spec["row"]],
                    housekeeping=housekeeping,
                    prewarm=prewarm,
                    sampler=sampler,
                    on_finished=finished,
                    run_fn=run_fn,
                    progress=progress,
                    stop=stop,
                )
            except NotLaunched:
                launched = False
                return None
            else:
                exit_code = row["exit_code"]
                return row
            finally:
                if board and launched:
                    board.run_finished(spec, exit_code, stopped=stop.requested)
                elif board:
                    board.run_skipped(spec)

        # The board polls each run directory; the runs' own stdout goes to their log files as before.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(tracked, specs))
            # A row the Lean gate refused before any model spend (memory, a cold toolchain) gets one more turn at
            # the end of the queue, when the machine is quieter; its first attempt stays in the report.
            retries = requeue_specs(specs, results) if not stop.requested else []
            for spec in retries:
                progress.event(f"requeue {spec['run_id']}: Lean refused the first attempt before any spend")
                if board:
                    board.add_run(spec)
            results += list(pool.map(tracked, retries))
            # A subscription run stopped by a spent usage window: the row runs again on the fallback model.
            moved = (
                usage_limit_specs(
                    [*specs, *retries], results, fallback, getattr(args, "fallback_limit_usd", FALLBACK_LIMIT_USD)
                )
                if not stop.requested
                else []
            )
            for spec in moved:
                progress.event(f"requeue {spec['run_id']}: the subscription's usage window ran out")
                if board:
                    board.add_run(spec)
            results += list(pool.map(tracked, moved))
        runs = [row for row in results if row is not None]
    finally:
        stop_helpers.set()
        if helper_thread:
            helper_thread.join()
        if hold:
            hold.close()
        observed = sampler.stop()
    if stop.requested:
        stopped = [row for row in runs if row["exit_code"] != 0]
        summaries = [str(RUNS / row["run_id"] / "summary.json") for row in stopped]
        message = (
            f"stopped by operator: {len(stopped)} run(s) stopped, {len(specs) - len(runs)} never launched, "
            f"${sum(row['spent_usd'] or 0 for row in runs):.4f} spent"
        )
        # The live view's last frame lists each stopped run with its summary path.
        if not (board is not None and board.set_notice(message)):
            print(message + (f"; summaries: {', '.join(summaries)}" if summaries else ""), flush=True)
    progress.close()
    report: dict = {
        "limit_usd": args.limit_usd,
        "prefix": args.prefix,
        **aggregate(runs, expected),
        "lean_unhealthy_runs": [run["run_id"] for run in lean_unhealthy_rows(runs)],
        "provider_unreachable_runs": [run["run_id"] for run in provider_unreachable_rows(runs)],
        "settings": settings,
        "observed": observed,
    }
    campaign_path.write_text(json.dumps(report, indent=2) + "\n")
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
    if stop.requested:
        return 130
    if not report["identical_packets"]:
        print("Packets differ between runs; the comparison is not valid.", file=sys.stderr)
        return 1
    return 0


def _warm_row(name: str) -> None:
    row = engine.problem(name)
    primary_version, primary_commit = engine.measure_version(row)
    result = engine.warm_session(row, primary_version, primary_commit, slots=1, lane="model")
    if _warm_refused(result):
        print(f"pre-warm {name}: {result}", flush=True)
    for version, commit in engine.versions(row):
        if version == primary_version:
            continue
        result = engine.warm_session(row, version, commit, 1, lane="background", wait=False)
        if _warm_refused(result):
            print(f"pre-warm {name} {version}: {result}", flush=True)


def _warm_refused(result: dict | None) -> bool:
    if result is None:
        return False
    failures = [str(item) for item in result.get("failed", [])]
    failures.append(str(result.get("reason", "")))
    return any("no room for a Lean worker" in failure for failure in failures)
