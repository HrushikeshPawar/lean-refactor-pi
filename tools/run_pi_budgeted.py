"""Run one fresh, budgeted Arena theorem session through Pi's JSON mode."""

from __future__ import annotations

import argparse
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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contextlib

from arena import lean_health, lean_session
from arena import models as model_config
from arena.campaign import autocheck, init, packet, run_dir, submission, write_state
from arena.skill import SKILL_DIR, skill_hash, skill_prompt
from arena.summary import configured_cap, cost_report_from_ledger, render_text, write_summary
from arena.traces import langfuse_environment, langfuse_extension, plugin_problems

SYSTEM_PROMPT = (
    "You are optimizing one Lean 4 proof for the Lean Refactor Arena. Only the listed tools are "
    "available. Keep replies short; spend effort on proofs, not prose."
)


ROOT = Path(__file__).resolve().parents[1]
# Every per-model fact (prices, windows, output limits, compaction, timeout, thinking levels) lives in models.yaml.
CONFIG = model_config.load()
MODELS = model_config.models()
MODEL_WINDOWS = {name: row["context_window"] for name, row in CONFIG["models"].items()}
# After Pi exits, pending background full checks get this long before the submission is chosen.
DRAIN_S = 300
# How long Pi gets to finish an in-flight evaluation and write cost.json after a stop request.
PROVIDER_TIMEOUT_MS = CONFIG["provider_timeout_ms"]
STOP_GRACE_S = 45
THINKING_LEVELS = tuple(CONFIG["thinking"]["levels"])
_tool_started: dict[str, tuple[float, dict]] = {}
_request_count = 0
_tool_result_count = 0
_retry_count = 0


def attempt_has_model_error(event_log: Path, offset: int) -> bool:
    """Ignore intentional cap stops and errors recovered by Pi's retry loop."""
    pending_error = False
    with event_log.open("rb") as events:
        events.seek(offset)
        for line in events:
            event = json.loads(line)
            if event.get("type") == "message_end":
                message = event.get("message", {})
                if message.get("role") == "assistant" and message.get("stopReason") in ("error", "aborted"):
                    pending_error = not str(message.get("errorMessage", "")).startswith("Arena budget stop:")
                elif message.get("role") == "assistant" and message.get("stopReason") in ("stop", "toolUse"):
                    pending_error = False
            elif event.get("type") == "auto_retry_end" and event.get("success"):
                pending_error = False
    return pending_error


def _describe_result(item: dict) -> str:
    """One probe or evaluation outcome for the live log: label, outcome, size and versions checked."""
    if item.get("ok") is False:
        return f"draft {item.get('index', '?')} rejected: {str(item.get('error', 'unknown error'))[:100]}"
    compat = item.get("compat") or {}
    passed = sum(bool(entry.get("passed")) for entry in compat.values())
    paths = sorted({str(entry["lean"]).split(" ")[0] for entry in compat.values() if entry.get("lean")})
    label = item.get("candidate") or item.get("probe") or "unrecorded"
    holes = f" {len(item['goals'])} holes" if item.get("goals") else ""
    versions = f" {passed}/{len(compat)} versions" if compat else ""
    via = f" lean={'+'.join(paths)}" if paths else ""
    return (
        f"{label} idea={item.get('idea_id', '?')} {item.get('tokens', '?')} tok "
        f"{item.get('heartbeat', '?')} HB{holes}{versions}{via}"
    )


def log_event(event: dict) -> None:
    global _request_count, _tool_result_count, _retry_count
    kind = event.get("type")
    note = None
    if kind == "tool_execution_start":
        name = event.get("toolName", "tool")
        if name in ("arena_evaluate", "arena_probe"):
            args = event.get("args") or {}
            _tool_started[event.get("toolCallId", "")] = (time.monotonic(), args)
            parent = (args.get("parents") or [args.get("parent", "?")])[0]
            note = f"{name} started idea={args.get('idea_id', '?')} parent={str(parent)[:12]} mode={args.get('mode', 'fast')}"
    elif kind == "tool_execution_end":
        _tool_result_count += 1
        name = event.get("toolName", "tool")
        started = _tool_started.pop(event.get("toolCallId", ""), None)
        elapsed = f" in {time.monotonic() - started[0]:.1f}s" if started else ""
        if name in ("arena_evaluate", "arena_probe"):
            try:
                result = json.loads(event["result"]["content"][0]["text"].splitlines()[0])
                args = started[1] if started else {}
                if result.get("ok") is False:
                    note = (
                        f"{name} rejected idea={args.get('idea_id', '?')} "
                        f"parent={str((args.get('parents') or [args.get('parent', '?')])[0])[:12]}"
                        f"{elapsed}; {result.get('error', 'unknown error')[:130]}"
                    )
                else:
                    items = result.get("drafts") or [result]
                    note = f"{name}{elapsed}: " + "; ".join(_describe_result(item) for item in items)
            except (KeyError, IndexError, TypeError, ValueError):
                note = "arena_evaluate returned an unreadable result"
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
    if note:
        print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {note}", flush=True)


_LEAN: dict = {"process": None, "directory": None}


def start_lean_session(directory: Path, parent_pid: int) -> None:
    """Start the run's Lean session daemon. Failing to start it only costs speed: calls run cold."""
    try:
        _LEAN["directory"] = directory
        _LEAN["process"] = lean_session.start_daemon(directory, parent_pid)
        os.environ[lean_session.ENV] = str(lean_session.socket_path(directory))
        print(f"Lean session pid={_LEAN['process'].pid}; socket={os.environ[lean_session.ENV]}", flush=True)
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
    if _LEAN["process"] is None or os.environ.get(lean_health.GATE_ENV) == "0":
        return None
    slots = min(lean_session.MAX_SLOTS, 4)
    print(
        f"Lean health gate: warming {slots} workers per version and checking the reference proof "
        f"(blocks until done; no model request is made before it passes)",
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
    """Stop the daemon and every Lean process it started; runs on every way out of `main`."""
    directory, _LEAN["directory"] = _LEAN["directory"], None
    process, _LEAN["process"] = _LEAN["process"], None
    os.environ.pop(lean_session.ENV, None)
    if directory is None:
        return
    lean_session.stop_daemon(directory, process)
    # A run that never got as far as `init` leaves nothing but the session's own files.
    try:
        if directory.is_dir() and all(
            item.name in lean_session.SESSION_FILES or item.name == "lean-session.log" for item in directory.iterdir()
        ):
            shutil.rmtree(directory)
    except OSError:
        pass


def main() -> int:
    try:
        return run()
    finally:
        stop_lean_session()


def run() -> int:
    global _request_count, _tool_result_count, _retry_count
    _tool_started.clear()
    _request_count = _tool_result_count = _retry_count = 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--prompt-file", type=Path, help="Optional extra instructions appended after the source packet")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--hard-cap-usd",
        "--cap-usd",
        dest="hard_cap_usd",
        type=float,
        default=3.0,
        help="Spend cap in USD, 0.10-3.00. Only $3 is a hard cap (worst-case request estimates are "
        "gated against it); a value below 3 is a soft cap on actual settled spend, so the last "
        "request may overshoot it",
    )
    parser.add_argument(
        "--thinking",
        choices=THINKING_LEVELS,
        default=CONFIG["thinking"]["default"],
        help="Reasoning level, recorded in run-config.json (default: high)",
    )
    parser.add_argument(
        "--compact-at-tokens",
        type=int,
        help="Context size above which Pi compacts older turns; below it history is never rewritten "
        "(default: the model's value in models.yaml)",
    )
    parser.add_argument(
        "--compact-keep-tokens",
        type=int,
        help="Recent tokens kept verbatim when compaction runs (default: the model's value in models.yaml)",
    )
    parser.add_argument(
        "--merge-worker",
        action="store_true",
        help="Run the deterministic merge worker beside the model (off by default: it competes for Lean CPU)",
    )
    parser.add_argument(
        "--no-lean-session",
        action="store_true",
        help="Compile every Lean call cold instead of through the run's persistent Lean session",
    )
    parser.add_argument("--no-skill", action="store_true", help="Run without the Arena Lean skill (A/B factor)")
    parser.add_argument("--no-mcp", action="store_true", help="Do not load the Lean MCP server (offline tests)")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Send a short skill-read prompt instead of the theorem packet (cheap trace check)",
    )
    parser.add_argument(
        "--no-langfuse",
        action="store_true",
        help="Do not load the Langfuse plugin (offline tests only; requires --test-extension)",
    )
    parser.add_argument(
        "--test-extension",
        action="append",
        default=[],
        type=Path,
        help="Extra Pi extension, used only to load the offline fake provider in tests",
    )
    parser.add_argument("--resume-run", action="store_true", help="Resume the exact Pi session and cost ledger")
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without launching Pi")
    args = parser.parse_args()

    compaction = CONFIG["models"][args.model]["compaction"]
    if args.compact_at_tokens is None:
        args.compact_at_tokens = compaction["at_tokens"]
    if args.compact_keep_tokens is None:
        args.compact_keep_tokens = compaction["keep_recent_tokens"]
    if not math.isfinite(args.hard_cap_usd) or not 0.1 <= args.hard_cap_usd <= 3:
        parser.error("--hard-cap-usd must be between 0.10 and 3.00")

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.run_id):
        parser.error("--run-id must be a Pi-compatible session ID")
    rows = (json.loads(line) for line in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines())
    if args.theorem not in {row["name"] for row in rows}:
        parser.error(f"unknown warm-up theorem: {args.theorem}")
    extra = args.prompt_file.read_text().strip() if args.prompt_file else ""

    directory = run_dir(args.run_id)
    if directory.exists() != args.resume_run:
        parser.error("--resume-run must be used exactly when the run ID already exists")
    if not args.dry_run and not args.no_lean_session:
        start_lean_session(directory, os.getpid())
    if args.resume_run:
        config = json.loads((directory / "run-config.json").read_text())
        if (config["theorem"], config["model"], configured_cap(config)) != (
            args.theorem,
            args.model,
            args.hard_cap_usd,
        ):
            parser.error("resume theorem, model, or cap differs from the original run")
        if config.get("thinking") not in (None, args.thinking) or (
            config.get("skill") and config["skill"]["sha256"] != (None if args.no_skill else skill_hash())
        ):
            parser.error("resume thinking level or skill differs from the original run")
        prompt = "Resume the existing Arena run from its recorded candidate frontier. Continue improving the proof."
    else:
        prompt = (
            "Call the arena_skill_read tool once with no arguments, then stop. Do not evaluate, edit, or search."
            if args.preflight
            else packet(args.theorem) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
        )
    if args.no_langfuse and not args.test_extension:
        parser.error("--no-langfuse is only for offline runs with --test-extension")
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
        *([] if args.no_mcp else ["--extension", "builtin:mcp"]),
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
        f"arena-budget/{args.model}",
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
        print(f"Validated {args.theorem} with {args.model}; session {args.run_id}; cap ${args.hard_cap_usd:g}")
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

    if not args.resume_run:
        init(args.theorem, args.run_id, extra)
        (directory / "run-config.json").write_text(
            json.dumps(
                {
                    "theorem": args.theorem,
                    "model": args.model,
                    "soft_cap_usd": args.hard_cap_usd,
                    "packet_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "thinking": args.thinking,
                    "merge_worker": args.merge_worker,
                    "compact_at_tokens": args.compact_at_tokens,
                    "compact_keep_tokens": args.compact_keep_tokens,
                    "skill": None if args.no_skill else {"name": "arena-lean", "sha256": skill_hash()},
                },
                indent=2,
            )
            + "\n"
        )
    health = lean_gate(args.theorem, directory)
    if health is not None and health["verdict"] != "healthy":
        return stop_unhealthy(args, directory, health["reasons"])
    shadow = directory / "scratch" / "project"
    env = os.environ.copy()
    env["ARENA_BUDGET_REQUIRED"] = "1"
    env["ARENA_AUTOCONTINUE"] = "0" if args.preflight else "1"
    env["ARENA_RUN_ID"] = args.run_id
    env["ARENA_MODEL"] = args.model
    env["ARENA_MODELS_JSON"] = model_config.pi_json(CONFIG)
    env["ARENA_HARD_CAP_USD"] = str(args.hard_cap_usd)
    env["ARENA_SKILL_DIR"] = "" if args.no_skill else str(SKILL_DIR)
    if args.no_mcp:
        env["ARENA_NO_MCP"] = "1"
    env.pop("ARENA_STOP_USD", None)
    env["ARENA_BUDGET_REPORT_PATH"] = str(directory / "cost.json")
    if plugin is not None:
        try:
            env.update(langfuse_environment())
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
    worker = None
    if args.merge_worker:
        worker_command = [
            sys.executable,
            "-m",
            "tools.arena_merge_worker",
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
        f"Pi session={args.run_id}; model={args.model}; actual-usage cap=${args.hard_cap_usd:g}; resume={args.resume_run}",
        flush=True,
    )
    status_path = directory / "merge-worker.json"
    for _ in range(30 if worker else 0):
        if worker.poll() is not None:
            print("Merge worker exited before Pi started; inspect merge-worker.log", file=sys.stderr)
            return 1
        if status_path.exists() and json.loads(status_path.read_text()).get("pid") == worker.pid:
            break
        time.sleep(0.1)
    else:
        if worker:
            print("Merge worker did not become ready; inspect merge-worker.log", file=sys.stderr)
            return 1
    # Pi reads the project's .pi/settings.json. Compaction is the only thing allowed to rewrite
    # history, and only once the context passes --compact-at-tokens.
    (shadow / ".pi").mkdir(exist_ok=True)
    (shadow / ".pi" / "settings.json").write_text(
        json.dumps(
            {
                "compaction": {
                    "enabled": True,
                    "keepRecentTokens": args.compact_keep_tokens,
                    "reserveTokens": max(0, MODEL_WINDOWS[args.model] - args.compact_at_tokens),
                },
                # The model gets only declared tools; Pi's codemode sandbox could call any tool and
                # non-LLM models outside the Arena budget guard.
                "autoEnableCodemode": False,
                # Pi's default HTTP idle timeout is 300 s (v6c2 DeepSeek lost a request to it); a silent
                # request is cut after PROVIDER_TIMEOUT_MS instead. Provider-level retries stay off.
                "httpIdleTimeoutMs": PROVIDER_TIMEOUT_MS,
                "retry": {"provider": {"timeoutMs": PROVIDER_TIMEOUT_MS, "maxRetries": 0}},
            },
            indent=2,
        )
        + "\n"
    )
    event_log = directory / "events.jsonl"
    event_offset = event_log.stat().st_size if event_log.exists() else 0
    state: dict = {"process": None, "signal": None, "timer": None, "tripped": False}
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

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupt)
    with event_log.open("a") as output:
        process = subprocess.Popen(
            command,
            cwd=shadow,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        state["process"] = process
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
                # The Lean circuit breaker fired while a tool result was recorded: no further model requests.
                state["tripped"] = True
                print(
                    f"Lean circuit breaker tripped ({lean_health.BREAKER_LIMIT} consecutive Lean timeouts or "
                    f"failures); stopping Pi cleanly",
                    file=sys.stderr,
                    flush=True,
                )
                if process.poll() is None:
                    process.terminate()
                    state["timer"] = threading.Timer(STOP_GRACE_S, force_stop)
                    state["timer"].daemon = True
                    state["timer"].start()
        try:
            exit_code = process.wait(timeout=STOP_GRACE_S)
        except subprocess.TimeoutExpired:
            kill_group(process, signal.SIGKILL)
            exit_code = process.wait()
    if state["timer"] is not None:
        state["timer"].cancel()
    # Lean servers and evaluations Pi started share its process group.
    kill_group(process, signal.SIGTERM)
    if worker is not None and worker.poll() is None:
        worker.terminate()
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


def kill_group(process: subprocess.Popen, number: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, number)


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
    if not report_path.exists() or report_path.stat().st_mtime < segment_started:
        report_path.write_text(json.dumps(cost_report_from_ledger(directory), indent=2) + "\n")
        print("Pi wrote no cost report for this segment; reconstructed it from the cost journal", file=sys.stderr)
    try:
        # Checks still queued when the model stopped are finished here (no model cost), unless the
        # run was interrupted, so the submission reflects every candidate the model produced.
        if interrupted is None and not tripped:
            drained = autocheck(args.theorem, args.run_id, DRAIN_S)
            if drained["checked"] or drained.get("remaining"):
                print(
                    f"Background checks after Pi exited: {drained['checked']}; still pending {drained.get('remaining', [])}",
                    flush=True,
                )
        write_state(args.run_id)
        answer = submission(args.run_id)
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
    if report.get("soft_cap_usd") != args.hard_cap_usd or report.get("hard_cap_usd") != 3:
        print("Arena cap configuration changed", file=sys.stderr)
        return 1
    print(
        f"Ledger-priced observed tokens=${report['spent_usd']:.6f}; unresolved exposure=${report.get('unresolved_usd', 0):.6f}; cap=${args.hard_cap_usd:.2f}",
        flush=True,
    )
    embedded = report.get("pi_embedded_estimate") or {}
    drift = report["spent_usd"] - embedded.get("usd", 0)
    if (
        embedded.get("priced_entries")
        and not embedded.get("missing_entries")
        and abs(drift) > max(1e-6, 0.01 * report["spent_usd"])
    ):
        print(
            f"Pricing drift: ledger ${report['spent_usd']:.6f} vs Pi's estimate ${embedded['usd']:.6f}; check the price table in budget.ts",
            file=sys.stderr,
            flush=True,
        )
    cache = report.get("cache_utilization", {})
    if cache.get("all", {}).get("reuse_pct") is not None:
        saved = cache["all"].get("savings_pct")
        print(
            f"Cache hit rate: all={cache['all']['reuse_pct']:.1f}% recent-10={cache['recent_ten']['reuse_pct']:.1f}%"
            + (f", input-side cost savings {saved:.1f}%" if saved is not None else ""),
            flush=True,
        )
    if report["spent_usd"] > args.hard_cap_usd:
        print(
            f"Observed usage overshot the ${args.hard_cap_usd:g} cap by ${report['spent_usd'] - args.hard_cap_usd:.6f} on the final in-flight request",
            file=sys.stderr,
        )
    if attempt_has_model_error(event_log, event_offset):
        print("Pi ended with a model error or abort; inspect events.jsonl", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
