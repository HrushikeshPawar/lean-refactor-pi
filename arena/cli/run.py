"""Run one fresh, budgeted Arena theorem session through Pi's JSON mode."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

from arena import lean_health, lean_session, text
from arena import models as model_config
from arena.campaign import _runtime_event, autocheck, init, packet, run_dir, submission, write_state
from arena.cli import live
from arena.coordinator import Coordinator
from arena.engine import ROOT
from arena.provenance import code_version
from arena.seed import check_seed, prior_work, read_seed_proof, start_from_proof
from arena.skill import skill_hash, skill_prompt
from arena.summary import configured_cap, cost_report_from_ledger, render_text, write_summary
from arena.traces import langfuse_environment, langfuse_extension, plugin_problems

DEFAULT_LIMIT_USD = 0.5
MAX_LIMIT_USD = 2.5  # keep equal to MAX_LIMIT_USD in packages/arena-pi/extensions/spend.ts

SYSTEM_PROMPT = text.render("messages/run.system_prompt")


# Every per-model fact (prices, windows, output limits, compaction, timeout, thinking levels) lives in models.yaml.
CONFIG = model_config.load()
MODELS = model_config.models()
# After Pi exits, pending background full checks get this long before the submission is chosen.
DRAIN_S = 180  # wall-clock cap on the closing drain; candidates left unchecked are recorded in the summary
# How long Pi gets to finish an in-flight evaluation and write cost.json after a stop request.
STOP_GRACE_S = 45
THINKING_LEVELS = tuple(CONFIG["thinking"]["levels"])
_tool_started: dict[str, float] = {}
_request_count = 0
_tool_result_count = 0
_retry_count = 0
# The live terminal view while Pi runs; None means plain lines (not a TTY, --plain or ARENA_PLAIN=1).
_LIVE: live.RunDisplay | None = None
# Pi's stderr lines shown as events while the live view is up; every line also goes to pi-stderr.log.
PI_STDERR_SHOWN = ("alarm]", "[arena-restart]", "[arena-memory]")


class _Echo:
    """Keeps each complete line written to a stream; with `passthrough` the text also reaches the stream."""

    def __init__(self, stream, lines: list[str], passthrough: bool):
        self.stream, self.lines, self.partial, self.passthrough = stream, lines, "", passthrough

    def write(self, data: str) -> int:
        self.partial += data
        *done, self.partial = self.partial.split("\n")
        self.lines.extend(line for line in done if line.strip())
        return self.stream.write(data) if self.passthrough else len(data)

    def flush(self) -> None:
        if self.passthrough:
            self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


class _Setup:
    """The setup phase (Lean session, health gate, warm-up) in a small live panel of its own; its lines are shown
    again inside the run view once Pi starts. Plain output when the panel cannot start."""

    def __init__(self, run_id: str):
        from rich.console import Console
        from rich.live import Live
        from rich.panel import Panel
        from rich.text import Text

        self.lines: list[str] = []
        self.saved = (sys.stdout, sys.stderr)
        self.started = time.monotonic()
        console = Console(file=sys.stdout)

        def render():
            seconds = int(time.monotonic() - self.started)
            body = Text("\n".join(self.lines[-12:]) or "starting", overflow="ellipsis", no_wrap=True)
            title = f"arena run {run_id} · starting · {seconds}s"
            return Panel(body, title=title, title_align="left", border_style="cyan")

        self.live: Live | None = None
        try:
            self.live = Live(get_renderable=render, console=console, refresh_per_second=4, transient=True)
            self.live.start()
        except Exception:  # the panel is cosmetic: fall back to plain lines
            self.live = None
        passthrough = self.live is None
        sys.stdout = _Echo(sys.stdout, self.lines, passthrough)
        sys.stderr = _Echo(sys.stderr, self.lines, passthrough)

    def restore(self) -> list[str]:
        sys.stdout, sys.stderr = self.saved
        if self.live is not None:
            with contextlib.suppress(Exception):
                self.live.stop()
        return self.lines


_SETUP: _Setup | None = None


def drain_pi_stderr(stream, path: Path) -> None:
    """Pi's stderr bypasses the live view's redirect (it is another process), so a raw line would break the
    screen. Keep every line in pi-stderr.log; show alarms as events, or print all of them when output is plain."""
    with path.open("a") as log:
        for line in stream:
            log.write(line)
            log.flush()
            line = line.rstrip("\n")
            if _LIVE is None:
                print(line, file=sys.stderr, flush=True)
            elif any(mark in line for mark in PI_STDERR_SHOWN):
                _LIVE.line(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {line[:160]}")


def pi_settings(args, config: dict) -> dict:
    """Build the complete project settings file from the selected model and central config."""
    model = config["models"][args.model]
    timeout = config["provider_timeout_ms"]
    retry = config["retry"]
    return {
        "compaction": {
            "enabled": True,
            "keepRecentTokens": args.compact_keep_tokens,
            "reserveTokens": max(0, model["context_window"] - args.compact_at_tokens),
        },
        "autoEnableCodemode": False,
        "httpIdleTimeoutMs": timeout,
        "retry": {
            "enabled": True,
            "maxRetries": retry["max_retries"],
            "baseDelayMs": int(os.environ.get("ARENA_RETRY_BASE_MS", retry["base_delay_ms"])),
            "maxAgentDelayMs": retry["max_delay_ms"],
            "provider": {"timeoutMs": timeout, "maxRetries": 0},
        },
    }


def seed_agent_dir(target: Path, source: Path, provider: str, model_id: str, max_tokens: int) -> Path:
    """A Pi agent directory that links every entry of `source` except models.json, which becomes the
    operator's models.json plus a maxTokens override for the run model (so a turn cut at the run's
    output ceiling is not "recoverable" and stays in history)."""
    target.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        for entry in source.iterdir():
            link = target / entry.name
            if entry.name != "models.json" and not link.exists() and not link.is_symlink():
                link.symlink_to(entry)
    user = source / "models.json"
    merged = json.loads(user.read_text()) if user.is_file() else {}
    overrides = merged.setdefault("providers", {}).setdefault(provider, {}).setdefault("modelOverrides", {})
    overrides.setdefault(model_id, {})["maxTokens"] = max_tokens
    (target / "models.json").write_text(json.dumps(merged, indent=2) + "\n")
    return target


def attempt_has_model_error(event_log: Path, offset: int, intentional_stop: bool = False) -> bool:
    """Ignore the abort that ends a run on purpose (spend limit, confirmed finish) and errors Pi's retry loop recovered."""
    pending_error = False
    with event_log.open("rb") as events:
        events.seek(offset)
        for line in events:
            event = json.loads(line)
            if event.get("type") == "message_end":
                message = event.get("message", {})
                if message.get("role") == "assistant" and message.get("stopReason") in ("error", "aborted"):
                    aborted = message.get("stopReason") == "aborted" or "aborted" in str(
                        message.get("errorMessage", "")
                    )
                    pending_error = not (intentional_stop and aborted)
                elif message.get("role") == "assistant" and message.get("stopReason") in ("stop", "toolUse"):
                    pending_error = False
            elif event.get("type") == "auto_retry_end" and event.get("success"):
                pending_error = False
    return pending_error


def log_event(event: dict) -> None:
    global _request_count, _tool_result_count, _retry_count
    kind = event.get("type")
    note = None
    if kind == "tool_execution_start":
        name = event.get("toolName", "tool")
        if name == "compile":
            args = event.get("args") or {}
            _tool_started[event.get("toolCallId", "")] = time.monotonic()
            parent = args.get("base") or args.get("from") or "?"
            note = f"{name} started drafts={len(args.get('drafts') or [])} base={str(parent)[:12]}"
    elif kind == "tool_execution_end":
        _tool_result_count += 1
        name = event.get("toolName", "tool")
        started = _tool_started.pop(event.get("toolCallId", ""), None)
        elapsed = f" in {time.monotonic() - started:.1f}s" if started is not None else ""
        if name == "compile":
            content = event.get("result", {}).get("content") or []
            detail = content[0].get("text", "") if content else ""
            note = f"compile{elapsed}: {detail[:180]}" if detail else f"compile{elapsed} completed"
        elif event.get("isError"):
            note = f"tool {name} returned an error"
        elif note is None:
            note = f"tool result #{_tool_result_count} {name} ok"
    elif kind == "message_end":
        message = event.get("message", {})
        if message.get("role") == "assistant":
            usage = message.get("usage") or {}
            if usage.get("totalTokens") or message.get("errorMessage"):
                _request_count += 1
            note = (
                f"provider response #{_request_count} model {message.get('stopReason', '?')} "
                f"output={usage.get('output', 0)} cache-read={usage.get('cacheRead', 0)} "
                f"cache-write={usage.get('cacheWrite', 0)}; tool-results={_tool_result_count}; retries={_retry_count}"
                + (f"; {str(message.get('errorMessage'))[:90]}" if message.get("errorMessage") else "")
            )
    elif kind == "auto_retry_start":
        _retry_count += 1
        note = f"provider retry {event.get('attempt')}/{event.get('maxAttempts')}: {event.get('errorMessage', '')}"
    elif kind == "agent_settled":
        note = "Pi agent settled"
    if _LIVE is not None:
        _LIVE.event(event)
    if note:
        line = f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {note}"
        if _LIVE is None or not _LIVE.line(line):
            print(line, flush=True)


@contextlib.contextmanager
def live_view(args, directory: Path, health: dict | None, worker: subprocess.Popen | None):
    """Show the live view while Pi runs; always gives the terminal back before the summary is printed."""
    global _LIVE, _SETUP
    setup, _SETUP = _SETUP, None
    lines = setup.restore() if setup else []
    if _LEAN["socket"] is None:
        lean = "no session (cold compiles)"
    elif health is None:
        lean = "session leased; no gate"
    else:
        lean = f"session leased; gate {health['verdict']}, timeout {os.environ.get(lean_health.TIMEOUT_ENV, '?')}"
    _LIVE = live.start_run(
        args.run_id,
        directory,
        plain=args.plain,
        theorem=args.theorem,
        model=args.model,
        limit_usd=args.limit_usd,
        lean=lean,
        merge_worker=worker,
        clear=bool(lines),
    )
    for line in lines:
        if _LIVE is None or not _LIVE.line(line):
            print(line, flush=True)
    try:
        yield
    finally:
        display, _LIVE = _LIVE, None
        if display is not None:
            display.stop()


_LEAN: dict = {"socket": None, "run_id": None, "directory": None}


class BackgroundChecks(TypedDict):
    thread: threading.Thread | None
    stop: threading.Event
    failed: threading.Event


_BACKGROUND: BackgroundChecks = {"thread": None, "stop": threading.Event(), "failed": threading.Event()}


def start_background_checks(
    theorem: str, directory: Path, report: dict | None, check_fn=None
) -> threading.Thread | None:
    """Check pending toolchains after the primary gate, without delaying the model."""
    if not report or not report.get("pending"):
        return None

    def check() -> None:
        kwargs = {"cancelled": _BACKGROUND["stop"].is_set}
        if check_fn is not None:
            kwargs["check_fn"] = check_fn
        failed = lean_health.check_others(theorem, directory, **kwargs)
        if any(not item.get("passed") for item in failed) or lean_health.tripped(directory) is not None:
            _BACKGROUND["failed"].set()

    thread = threading.Thread(target=check, name="arena-lean-background-checks", daemon=True)
    _BACKGROUND["thread"] = thread
    thread.start()
    return thread


def reference_failure_message(directory: Path) -> str:
    marker = lean_health.tripped(directory) or {}
    return (
        f"Lean unhealthy on {marker.get('version', 'unknown')}: "
        f"{marker.get('detail') or 'reference check failed'}; stopping before further spend"
    )


def watch_background_failure(failed: threading.Event, directory: Path, stop_fn) -> threading.Thread:
    """Stop Pi once a background reference check records an unhealthy toolchain."""

    def watch() -> None:
        if not failed.wait():
            return
        stop_fn(reference_failure_message(directory))

    thread = threading.Thread(target=watch, name="arena-lean-failure-watcher", daemon=True)
    thread.start()
    return thread


def start_lean_session(directory: Path, row: dict, run_id: str) -> None:
    """Lease this run's toolchains on the shared Lean service; failure only costs speed."""
    try:
        from arena import engine

        _LEAN["directory"] = directory
        path = lean_session.ensure_service()
        os.environ[lean_session.ENV] = path
        primary, others = engine.lease_projects(row)
        reply = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": run_id,
                "pid": os.getpid(),
                "primary": primary,
                "others": others,
            },
            5,
            path,
        )
        if not reply or not reply.get("ok"):
            raise lean_session.SessionError((reply or {}).get("reason", "service refused lease"))
        _LEAN.update(socket=path, run_id=run_id)
        os.environ[lean_session.RUN_ID_ENV] = run_id
        status = lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 5, path) or {}
        print(f"Lean session pid={status.get('pid')}; socket={path}", flush=True)
    except (lean_session.SessionError, OSError) as error:
        os.environ.pop(lean_session.ENV, None)
        print(f"Lean session unavailable ({error}); Lean calls will compile cold", file=sys.stderr, flush=True)


def lean_gate(theorem: str, directory: Path, gate_fn=None) -> dict | None:
    """Blocking Lean health gate, run after the session daemon is up and before Pi or any model request.

    Healthy: the row's per-check limit goes into ARENA_LEAN_TIMEOUT (Pi and every tool process it spawns inherit the
    environment this runner copies for them). Returns the gate report, or None when no gate applies (no session, or
    ARENA_LEAN_GATE=0 for offline tests).
    """
    (directory / lean_health.TRIPPED_FILE).unlink(missing_ok=True)  # a resumed run starts with a clean breaker
    if _LEAN["socket"] is None or os.environ.get(lean_health.GATE_ENV) == "0":
        return None
    slots = lean_session.PRIMARY_MIN_WORKERS
    print(
        f"Lean health gate: warming {slots} primary workers and checking its reference proof first; "
        "other toolchains are checked in the background",
        flush=True,
    )
    report = (gate_fn or lean_health.gate)(theorem, slots, directory)
    if report["verdict"] == "healthy":
        lean_health.apply_timeout_env(report)
        print(f"Lean gate healthy: {lean_health.TIMEOUT_ENV}={os.environ[lean_health.TIMEOUT_ENV]}", flush=True)
    return report


def stop_unhealthy(args, directory: Path, reasons: list[str]) -> int:
    """End a run that never reached Pi (or was stopped by the breaker) as `lean_unhealthy`: cost.json and a
    summary the normal tooling reads, exit status EXIT_CODE so a campaign skips the row and goes on."""
    print(f"Lean unhealthy; not starting the model: {'; '.join(reasons)}", file=sys.stderr, flush=True)
    report_path = directory / "cost.json"
    try:
        report_path.write_text(json.dumps(cost_report_from_ledger(directory), indent=2) + "\n")
        print(render_text(write_summary(directory, lean_health.STOP_REASON)), end="", flush=True)
    except Exception as error:  # the stop must still be reported
        (directory / "stop-reason.txt").write_text(lean_health.STOP_REASON + "\n")
        print(f"Run summary failed: {error}", file=sys.stderr)
    print(f"stop_reason={lean_health.STOP_REASON}; spent $0 on the model", flush=True)
    return lean_health.EXIT_CODE


def stop_lean_session() -> None:
    """Release this run's lease (the service keeps its toolchains warm for a while); runs on every way out of `main`."""
    directory, _LEAN["directory"] = _LEAN["directory"], None
    path, _LEAN["socket"] = _LEAN["socket"], None
    run_id, _LEAN["run_id"] = _LEAN["run_id"], None
    os.environ.pop(lean_session.ENV, None)
    os.environ.pop(lean_session.RUN_ID_ENV, None)
    if directory is None:
        return
    if path and run_id:
        lean_session.request({"op": "release", "protocol": lean_session.PROTOCOL, "run_id": run_id}, 10, path)
    # A run that never got as far as `init` leaves nothing but the session's own files.
    try:
        if directory.is_dir() and all(
            item.name in lean_session.SESSION_FILES or item.name == "lean-session.log" for item in directory.iterdir()
        ):
            shutil.rmtree(directory)
    except OSError:
        pass


@dataclass(frozen=True)
class RunOptions:
    model: str
    theorem: str
    run_id: str
    prompt_file: Path | None = None
    limit_usd: float = DEFAULT_LIMIT_USD
    thinking: str = CONFIG["thinking"]["default"]
    compact_at_tokens: int | None = None
    compact_keep_tokens: int | None = None
    merge_worker: bool = False
    no_lean_session: bool = False
    no_skill: bool = False
    preflight: bool = False
    no_langfuse: bool = False
    test_extension: list[Path] = field(default_factory=list)
    resume_run: bool = False
    seed_run: Path | None = None  # an ended run whose graph and history this run continues from
    seed_proof: Path | None = None  # a proof file this run starts from instead of the reference proof
    no_golf: bool = False  # compatibility flag; post-run golf is disabled for every run
    dry_run: bool = False
    plain: bool = False


def _release_setup() -> None:
    """Give the terminal back from the setup panel when the run ends before the live view takes over (an
    unhealthy gate, a refused option, Ctrl+C), printing the lines the panel held."""
    global _SETUP
    setup, _SETUP = _SETUP, None
    if setup is not None:
        for line in setup.restore():
            print(line, flush=True)


def execute(options: RunOptions) -> int:
    try:
        return run(options)
    except KeyboardInterrupt:
        _release_setup()
        # Ctrl+C before Pi started (packet, Lean gate): from Pi's start on, `interrupt` handles it and never raises.
        print("interrupted before Pi started; no model spend", file=sys.stderr, flush=True)
        return 130
    finally:
        _release_setup()
        _BACKGROUND["stop"].set()
        stop_lean_session()


def run(options: RunOptions) -> int:
    global _request_count, _tool_result_count, _retry_count
    _tool_started.clear()
    _request_count = _tool_result_count = _retry_count = 0
    _BACKGROUND["stop"].clear()
    _BACKGROUND["failed"].clear()
    _BACKGROUND["thread"] = None
    args = SimpleNamespace(**asdict(options))
    if args.model not in MODELS:
        print(f"error: unknown model {args.model!r}; choose from {', '.join(MODELS)}", file=sys.stderr)
        return 2
    if args.thinking not in THINKING_LEVELS:
        print(
            f"error: unknown thinking level {args.thinking!r}; choose from {', '.join(THINKING_LEVELS)}",
            file=sys.stderr,
        )
        return 2

    compaction = CONFIG["models"][args.model]["compaction"]
    if args.compact_at_tokens is None:
        args.compact_at_tokens = compaction["at_tokens"]
    if args.compact_keep_tokens is None:
        args.compact_keep_tokens = compaction["keep_recent_tokens"]
    if not math.isfinite(args.limit_usd) or not 0 < args.limit_usd <= MAX_LIMIT_USD:
        print(f"error: --limit-usd must be above 0 and at most {MAX_LIMIT_USD:g}", file=sys.stderr)
        return 2

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.run_id):
        print("error: --run-id must be a Pi-compatible session ID", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines()]
    row = next((row for row in rows if row["name"] == args.theorem), None)
    if row is None:
        print(f"error: unknown warm-up theorem: {args.theorem}", file=sys.stderr)
        return 2
    extra = args.prompt_file.read_text().strip() if args.prompt_file else ""

    if args.seed_proof is not None and (args.seed_run is not None or args.resume_run or args.preflight):
        print(
            "error: --seed-proof starts a new run; it cannot go with --seed-run, --resume-run or --preflight",
            file=sys.stderr,
        )
        return 2
    directory = run_dir(args.run_id)
    if directory.exists() != args.resume_run:
        print("error: --resume-run must be used exactly when the run ID already exists", file=sys.stderr)
        return 2
    if args.seed_run is not None:
        if args.resume_run or args.preflight:
            print("error: --seed-run starts a new run; it cannot go with --resume-run or --preflight", file=sys.stderr)
            return 2
        try:
            check_seed(args.seed_run)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    if args.seed_proof is not None:
        try:
            read_seed_proof(args.theorem, args.seed_proof)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    global _SETUP
    if not args.dry_run and live.enabled(args.plain):
        _SETUP = _Setup(args.run_id)
    if not args.dry_run and not args.no_lean_session:
        start_lean_session(directory, row, args.run_id)
    if args.resume_run:
        config = json.loads((directory / "run-config.json").read_text())
        if (config["theorem"], config["model"], configured_cap(config)) != (
            args.theorem,
            args.model,
            args.limit_usd,
        ):
            print("error: resume theorem, model, or limit differs from the original run", file=sys.stderr)
            return 2
        if config.get("thinking") not in (None, args.thinking) or (
            config.get("skill") and config["skill"]["sha256"] != (None if args.no_skill else skill_hash())
        ):
            print("error: resume thinking level or skill differs from the original run", file=sys.stderr)
            return 2
        prompt = text.render("messages/run.resume")
    else:
        prompt = (
            text.render("messages/run.preflight")
            if args.preflight
            else packet(args.theorem) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
        )
    if args.no_langfuse and not args.test_extension:
        print("error: --no-langfuse is only for offline runs with --test-extension", file=sys.stderr)
        return 2
    plugin = None if args.no_langfuse else langfuse_extension()
    command = [
        "pi",
        "--offline",
        "--approve",
        "--mode",
        "json",
        "--no-builtin-tools",
        "--no-context-files",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        *[item for path in args.test_extension for item in ("--extension", str(path.resolve()))],
        "--extension",
        str(ROOT / "packages/arena-pi/extensions/arena.ts"),
        *([] if plugin is None else ["--extension", str(plugin)]),
        "--system-prompt",
        SYSTEM_PROMPT,
        *([] if args.no_skill else ["--append-system-prompt", skill_prompt()]),
        "--thinking",
        args.thinking,
        "--model",
        model_config.pi_model(args.model, CONFIG),
        "--session-id",
        args.run_id,
        "--session-dir",
        str(directory / "session"),
        "--name",
        f"{args.theorem} | {args.model} | {args.run_id}",
        "--",
        f"/arena {args.theorem}",
        prompt,
    ]
    if args.dry_run:
        print(f"Validated {args.theorem} with {args.model}; session {args.run_id}; limit ${args.limit_usd:g}")
        print("Pi will write packet, candidate ledger, events, cost, and session under", directory)
        return 0
    if plugin is not None:
        if not plugin.is_file():
            print(f"Langfuse plugin is not installed at {plugin}", file=sys.stderr)
            return 1
        problems = plugin_problems()
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1

    price_problems = [] if args.test_extension else model_config.catalog_price_problems(CONFIG)
    if price_problems:
        print("Pi's catalog prices differ from models.yaml; the spend stop would be wrong:", file=sys.stderr)
        print("\n".join(price_problems), file=sys.stderr)
        return 1
    if not args.resume_run:
        init(args.theorem, args.run_id, extra, seed=args.seed_run)
        if args.seed_run is not None:
            # The recorded packet hash stays that of the plain packet; the prior work follows it.
            section = prior_work(args.run_id, args.seed_run)
            with (directory / "packet.txt").open("a") as packet_file:
                packet_file.write("\n" + section)
            command[-1] = prompt + "\n" + section
        (directory / "run-config.json").write_text(
            json.dumps(
                {
                    "theorem": args.theorem,
                    "model": args.model,
                    "pi_model": model_config.pi_model(args.model, CONFIG),
                    "limit_usd": args.limit_usd,
                    "packet_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "thinking": args.thinking,
                    "seed_run": None if args.seed_run is None else str(args.seed_run),
                    "seed_proof": None if args.seed_proof is None else str(args.seed_proof),
                    "merge_worker": args.merge_worker,
                    "compact_at_tokens": args.compact_at_tokens,
                    "compact_keep_tokens": args.compact_keep_tokens,
                    "skill": None if args.no_skill else {"name": "arena-lean", "sha256": skill_hash()},
                    "code": code_version(),
                },
                indent=2,
            )
            + "\n"
        )
    health = lean_gate(args.theorem, directory)
    if health is not None and health["verdict"] != "healthy":
        return stop_unhealthy(args, directory, health["reasons"])
    if args.seed_proof is not None:
        try:
            seeded = start_from_proof(args.theorem, args.run_id, args.seed_proof)
        except ValueError as error:
            print(f"error: {error}; no model spend, the run did not start", file=sys.stderr)
            return 2
        if seeded.get("reference"):
            print(f"Seed proof {args.seed_proof} is the reference proof; starting as usual", flush=True)
        else:
            print(f"Seeded from {args.seed_proof}: proxy {seeded['best_proxy']}", flush=True)
            # The recorded packet hash stays that of the plain packet; the prior work follows it.
            section = prior_work(args.run_id)
            with (directory / "packet.txt").open("a") as packet_file:
                packet_file.write("\n" + section)
            command[-1] = prompt + "\n" + section
    start_background_checks(args.theorem, directory, health)
    shadow = directory / "scratch" / "project"
    env = os.environ.copy()
    env["ARENA_BUDGET_REQUIRED"] = "1"
    env["ARENA_AUTOCONTINUE"] = "0" if args.preflight else "1"
    env["ARENA_RUN_ID"] = args.run_id
    env["ARENA_MODEL"] = args.model
    env["ARENA_PI_MODEL_ID"] = CONFIG["models"][args.model].get("id", args.model)
    env["ARENA_MODELS_JSON"] = model_config.pi_json(CONFIG)
    env["ARENA_LIMIT_USD"] = str(args.limit_usd)
    env["ARENA_REQUEST_OUTPUT_TOKENS"] = str(CONFIG["models"][args.model]["request_output_tokens"])
    env.setdefault("ARENA_OUTAGE_LIMIT_MS", str(CONFIG["outage_limit_ms"]))
    env["ARENA_BUDGET_REPORT_PATH"] = str(directory / "cost.json")
    if plugin is not None:
        try:
            env.update(langfuse_environment())
        except RuntimeError as error:
            _BACKGROUND["stop"].set()
            print(error, file=sys.stderr)
            return 1
    worker = None
    if args.merge_worker:
        worker_command = [
            sys.executable,
            "-m",
            "arena.cli.merge",
            args.run_id,
            "--parent-pid",
            str(os.getpid()),
        ]
        worker_log = (directory / "merge-worker.log").open("a")
        worker = subprocess.Popen(
            worker_command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        worker_log.close()
        print(f"Merge worker pid={worker.pid}; log={directory / 'merge-worker.log'}", flush=True)
    print(
        f"Pi session={args.run_id}; model={args.model}; limit=${args.limit_usd:g}; resume={args.resume_run}",
        flush=True,
    )
    status_path = directory / "merge-worker.json"
    for _ in range(30 if worker else 0):
        if worker is not None and worker.poll() is not None:
            print("Merge worker exited before Pi started; inspect merge-worker.log", file=sys.stderr)
            _BACKGROUND["stop"].set()
            return 1
        if worker is not None and status_path.exists() and json.loads(status_path.read_text()).get("pid") == worker.pid:
            break
        time.sleep(0.1)
    else:
        if worker:
            print("Merge worker did not become ready; inspect merge-worker.log", file=sys.stderr)
            _BACKGROUND["stop"].set()
            return 1
    # Pi reads the project's .pi/settings.json. Compaction is the only thing allowed to rewrite
    # history, and only once the context passes --compact-at-tokens.
    (shadow / ".pi").mkdir(exist_ok=True)
    (shadow / ".pi" / "settings.json").write_text(json.dumps(pi_settings(args, CONFIG), indent=2) + "\n")
    # Pi reads models.json only from its agent directory, so the run gets its own directory that links
    # everything else (auth.json, plugins, settings) from the operator's and caps the run model's maxTokens.
    selected_model = CONFIG["models"][args.model]
    env["PI_CODING_AGENT_DIR"] = str(
        seed_agent_dir(
            directory / "pi-agent",
            Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi/agent"),
            model_config.provider(args.model, CONFIG),
            selected_model.get("id", args.model),
            selected_model["request_output_tokens"],
        )
    )
    event_log = directory / "events.jsonl"
    event_offset = event_log.stat().st_size if event_log.exists() else 0
    state: dict = {"process": None, "signal": None, "timer": None, "tripped": False}
    stop_lock = threading.Lock()
    segment_started = time.time()

    def force_stop() -> None:
        process = state["process"]
        if process is not None and process.poll() is None:
            print("Pi did not stop in time; killing it", file=sys.stderr, flush=True)
            kill_group(process, signal.SIGKILL)

    def interrupt(signum, _frame):
        # Pi runs in its own session, so a terminal Ctrl+C reaches only this
        # runner. Pi's JSON mode shuts down cleanly (and writes cost.json) on
        # SIGTERM but not on SIGINT, so every stop request becomes a SIGTERM.
        if state["signal"] is not None:
            force_stop()
            return
        state["signal"] = signum
        process = state["process"]
        if process is not None and process.poll() is None:
            print(
                f"Stopping Pi cleanly (up to {STOP_GRACE_S}s); press Ctrl+C again to kill it",
                file=sys.stderr,
                flush=True,
            )
            process.terminate()
            state["timer"] = threading.Timer(STOP_GRACE_S, force_stop)
            state["timer"].daemon = True
            state["timer"].start()

    def stop_for_lean(message: str) -> None:
        with stop_lock:
            if state["tripped"]:
                return
            state["tripped"] = True
        print(message, file=sys.stderr, flush=True)
        process = state["process"]
        if process is not None and process.poll() is None:
            process.terminate()
            state["timer"] = threading.Timer(STOP_GRACE_S, force_stop)
            state["timer"].daemon = True
            state["timer"].start()

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupt)
    with Coordinator(directory) as coordinator, event_log.open("a") as output, live_view(args, directory, health, worker):
        env["ARENA_GENERATION"] = coordinator.generation
        model_phase_id = f"model:{os.getpid()}:{time.monotonic_ns()}"
        process = subprocess.Popen(
            command,
            cwd=shadow,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        _runtime_event(directory, {"kind": "phase", "phase": "model", "phase_id": model_phase_id, "status": "start"})
        state["process"] = process
        assert process.stderr is not None
        stderr_reader = threading.Thread(
            target=drain_pi_stderr, args=(process.stderr, directory / "pi-stderr.log"), daemon=True
        )
        stderr_reader.start()
        if _BACKGROUND["thread"] is not None:
            watch_background_failure(_BACKGROUND["failed"], directory, stop_for_lean)
        if state["signal"] is not None:
            process.terminate()
        assert process.stdout is not None
        for line in process.stdout:
            line = stamp_tool_event(line)
            output.write(line)
            output.flush()
            try:
                log_event(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError):
                print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] non-JSON Pi output recorded", flush=True)
            if not state["tripped"] and lean_health.tripped(directory):
                marker = lean_health.tripped(directory) or {}
                if marker.get("source") == "reference_check":
                    message = reference_failure_message(directory)
                else:
                    message = (
                        f"Lean circuit breaker tripped ({lean_health.BREAKER_LIMIT} consecutive Lean timeouts or "
                        "failures); stopping Pi cleanly"
                    )
                stop_for_lean(message)
        try:
            exit_code = process.wait(timeout=STOP_GRACE_S)
        except subprocess.TimeoutExpired:
            kill_group(process, signal.SIGKILL)
            exit_code = process.wait()
        stderr_reader.join(timeout=5)
    _runtime_event(directory, {"kind": "phase", "phase": "model", "phase_id": model_phase_id, "status": "end", "exit_code": exit_code})
    if state["timer"] is not None:
        state["timer"].cancel()
    # Lean servers and evaluations Pi started share its process group.
    kill_group(process, signal.SIGTERM)
    if worker is not None and worker.poll() is None:
        worker.terminate()
    _BACKGROUND["stop"].set()
    return finish(
        args,
        directory,
        event_log,
        event_offset,
        exit_code,
        state["signal"],
        segment_started,
        tripped=state["tripped"] or lean_health.tripped(directory) is not None,
    )


def stamp_tool_event(line: str) -> str:
    """Add the wall-clock `ts` to tool_execution_start/end events so tool latency can be computed later."""
    if '"tool_execution_' not in line:
        return line
    try:
        event = json.loads(line)
    except ValueError:
        return line
    if event.get("type") in ("tool_execution_start", "tool_execution_end") and "ts" not in event:
        event["ts"] = round(time.time(), 3)
        return json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    return line


def _stopped_on_purpose(directory: Path) -> bool:
    """True when the cost ledger's last control row says the run ended by its spend limit or a confirmed finish."""
    controls = []
    with contextlib.suppress(OSError, ValueError):
        controls = [
            row
            for row in map(json.loads, (directory / "cost-ledger.jsonl").read_text().splitlines())
            if row.get("kind") == "control"
        ]
    return bool(controls) and controls[-1].get("stop") in ("limit_reached", "finished")


def kill_group(process: subprocess.Popen, number: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, number)


def _until_stopped(job, skipped: str):
    """Run `job()`; a further stop request skips what is left of it (None)."""

    def skip(_signum, _frame):
        raise KeyboardInterrupt

    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {number: signal.signal(number, skip) for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        return job()
    except KeyboardInterrupt:
        print(skipped, file=sys.stderr, flush=True)
        return None
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def closing_drain(theorem: str, run_id: str) -> dict | None:
    """Full-check queued candidates for up to DRAIN_S; a further stop request skips the rest (None)."""
    return _until_stopped(
        lambda: autocheck(theorem, run_id, DRAIN_S, closing=True), "Closing checks skipped by a further stop request"
    )


def finish(
    args,
    directory: Path,
    event_log: Path,
    event_offset: int,
    exit_code: int,
    interrupted: int | None,
    segment_started: float = 0.0,
    tripped: bool = False,
) -> int:
    """Always leave cost.json and a run summary behind, even for a killed or crashed run."""
    report_path = directory / "cost.json"
    # On a resumed run, a cost.json left by an earlier segment is stale.
    if (directory / "control.jsonl").is_file():
        from arena.run_control import read_state

        read_state(directory)
    elif not report_path.exists() or report_path.stat().st_mtime < segment_started:
        report_path.write_text(json.dumps(cost_report_from_ledger(directory), indent=2) + "\n")
        print("Pi wrote no cost report for this segment; reconstructed it from the cost journal", file=sys.stderr)
    summary_phase_ended = False
    try:
        # Checks still queued when the model stopped are finished here (no model cost), on a normal end
        # and on an operator stop alike, so the submission reflects every candidate the model produced.
        # Only an unhealthy Lean skips them.
        drained = closing_drain(args.theorem, args.run_id) if not tripped else None
        if drained and (drained["checked"] or drained.get("remaining") or drained.get("skipped")):
            print(
                f"Background checks after Pi exited: {drained['checked']}; skipped (cannot beat the best) {drained.get('skipped', [])}; still pending {drained.get('remaining', [])}{' (drain cap reached)' if drained.get('timed_out') else ''}",
                flush=True,
            )
        summary_phase_id = f"summary:{os.getpid()}:{time.monotonic_ns()}"
        _runtime_event(directory, {"kind": "phase", "phase": "summary", "phase_id": summary_phase_id, "status": "start"})
        write_state(args.run_id)
        answer = submission(args.run_id)
        _runtime_event(directory, {"kind": "phase", "phase_id": summary_phase_id, "phase": "summary", "status": "end"})
        summary_phase_ended = True
        print(
            f"Submission: {answer.get('candidate') or 'none'}"
            + (
                f" proxy {answer['proxy']} ({answer['tokens']} tok, {answer['heartbeats']} HB)"
                if answer.get("candidate")
                else f" ({answer['reason']})"
            ),
            flush=True,
        )
    except Exception as error:
        if "summary_phase_id" in locals() and not summary_phase_ended:
            _runtime_event(directory, {"kind": "phase", "phase": "summary", "phase_id": summary_phase_id, "status": "error", "error": str(error)[:300]})
        print(f"Choosing the submission failed: {error}", file=sys.stderr)
    try:
        print(
            render_text(
                write_summary(
                    directory,
                    "interrupted"
                    if interrupted is not None and not tripped
                    else lean_health.STOP_REASON
                    if tripped
                    else None,
                )
            ),
            end="",
            flush=True,
        )
    except Exception as error:  # a summary failure must never hide the run's own result
        print(f"Run summary failed: {error}", file=sys.stderr)
    if tripped:
        print(f"stop_reason={lean_health.STOP_REASON}; cost.json and summary.json were written", flush=True)
        return lean_health.EXIT_CODE
    if interrupted is not None:
        print(f"Interrupted by signal {interrupted}; cost.json and summary.json were written", file=sys.stderr)
        return 128 + interrupted
    print(f"Pi exit={exit_code}; events={directory / 'events.jsonl'}; cost={report_path}")
    if exit_code:
        return exit_code
    if not report_path.exists():
        print("Pi did not produce a cost report", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())
    if report.get("error") or report.get("theorem") != args.theorem:
        print(f"Invalid cost report: {report.get('error', 'theorem mismatch')}", file=sys.stderr)
        return 1
    if float(report.get("limit_usd") or 0) != args.limit_usd:
        print("Arena limit configuration changed", file=sys.stderr)
        return 1
    spent_usd = float(report["spent_usd"])
    print(f"Spent ${spent_usd:.6f} of the ${args.limit_usd:.2f} limit", flush=True)
    cache = report.get("cache_utilization", {})
    if cache.get("all", {}).get("reuse_pct") is not None:
        print(
            f"Cache hit rate: all={cache['all']['reuse_pct']:.1f}% recent-10={cache['recent_ten']['reuse_pct']:.1f}%",
            flush=True,
        )
    if spent_usd > args.limit_usd:
        print(
            f"Spend overshot the ${args.limit_usd:g} limit by ${spent_usd - args.limit_usd:.6f} on the last call",
            file=sys.stderr,
        )
    if attempt_has_model_error(event_log, event_offset, _stopped_on_purpose(directory)):
        print("Pi ended with a model error or abort; inspect events.jsonl", file=sys.stderr)
        return 1
    return 0
