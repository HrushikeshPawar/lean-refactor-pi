"""Run one fresh, budgeted Arena theorem session through Pi's JSON mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.campaign import init, packet, run_dir
from tools.arena_skill import SKILL_DIR, skill_hash, skill_prompt

SYSTEM_PROMPT = ("You are optimizing one Lean 4 proof for the Lean Refactor Arena. Only the listed tools are "
                 "available. Keep replies short; spend effort on proofs, not prose.")


ROOT = Path(__file__).resolve().parents[1]
MODELS = ("gpt-6-luna", "qwen3.8-flash", "deepseek-v4.1-flash")
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
_tool_started: dict[str, tuple[float, dict]] = {}


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


def log_event(event: dict) -> None:
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
        name = event.get("toolName", "tool")
        started = _tool_started.pop(event.get("toolCallId", ""), None)
        elapsed = f" in {time.monotonic() - started[0]:.1f}s" if started else ""
        if name in ("arena_evaluate", "arena_probe"):
            try:
                result = json.loads(event["result"]["content"][0]["text"])
                compat = result.get("compat", {})
                passed = sum(bool(item.get("passed")) for item in compat.values())
                if result.get("node_number") or result.get("proof_id"):
                    label = f"#{result['node_number']}" if result.get("node_number") else f"probe {str(result['proof_id'])[:8]}"
                    outcome = "Lean pass" if result.get("ok") else "Lean fail"
                    note = (f"{name} {label} {outcome} idea={result.get('idea_id', '?')} "
                            f"{result.get('mode', 'fast')} {result.get('tokens', '?')} tokens "
                            f"{passed}/{len(compat)} versions{elapsed}")
                elif result.get("ok") is False:
                    args = started[1] if started else {}
                    note = (f"{name} rejected idea={args.get('idea_id', '?')} "
                            f"parent={str((args.get('parents') or [args.get('parent', '?')])[0])[:12]}"
                            f"{elapsed}; {result.get('error', 'unknown error')[:130]}")
                else:
                    note = f"{name} returned without a recorded node{elapsed}"
            except (KeyError, IndexError, TypeError, ValueError):
                note = "arena_evaluate returned an unreadable result"
        elif event.get("isError"):
            note = f"tool {name} returned an error"
    elif kind == "message_end":
        message = event.get("message", {})
        if message.get("role") == "assistant":
            usage = message.get("usage") or {}
            note = (f"model {message.get('stopReason', '?')} "
                    f"output={usage.get('output', 0)} cache-read={usage.get('cacheRead', 0)} "
                    f"cache-write={usage.get('cacheWrite', 0)}"
                    + (f"; {str(message.get('errorMessage'))[:90]}" if message.get("errorMessage") else ""))
    elif kind == "auto_retry_start":
        note = f"provider retry {event.get('attempt')}/{event.get('maxAttempts')}: {event.get('errorMessage', '')}"
    elif kind == "agent_settled":
        note = "Pi agent settled"
    if note:
        print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {note}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--prompt-file", type=Path, help="Optional extra instructions appended after the source packet")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hard-cap-usd", type=float, default=1.0)
    parser.add_argument("--thinking", choices=THINKING_LEVELS, default="high",
                        help="Reasoning level, recorded in run-config.json (default: high)")
    parser.add_argument("--no-skill", action="store_true", help="Run without the Arena Lean skill (A/B factor)")
    parser.add_argument("--no-mcp", action="store_true", help="Do not load the Lean MCP server (offline tests)")
    parser.add_argument("--test-extension", action="append", default=[], type=Path,
                        help="Extra Pi extension, used only to load the offline fake provider in tests")
    parser.add_argument("--resume-run", action="store_true", help="Resume the exact Pi session and cost ledger")
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without launching Pi")
    args = parser.parse_args()

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
    if args.resume_run:
        config = json.loads((directory / "run-config.json").read_text())
        if (config["theorem"], config["model"], config["hard_cap_usd"]) != (args.theorem, args.model, args.hard_cap_usd):
            parser.error("resume theorem, model, or cap differs from the original run")
        if config.get("thinking") not in (None, args.thinking) or (
                config.get("skill") and config["skill"]["sha256"] != (None if args.no_skill else skill_hash())):
            parser.error("resume thinking level or skill differs from the original run")
        prompt = "Resume the existing Arena run from its recorded candidate frontier. Continue improving the proof."
    else:
        prompt = packet(args.theorem) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
    command = [
        "pi", "--offline", "--approve", "--mode", "json",
        "--no-builtin-tools", "--no-context-files", "--no-extensions",
        "--no-skills", "--no-prompt-templates",
        *([] if args.no_mcp else ["--extension", "builtin:mcp"]),
        *[item for path in args.test_extension for item in ("--extension", str(path.resolve()))],
        "--extension", str(ROOT / "packages/arena-pi/extensions/arena.ts"),
        "--system-prompt", SYSTEM_PROMPT,
        *([] if args.no_skill else ["--append-system-prompt", skill_prompt()]),
        "--thinking", args.thinking,
        "--model", f"arena-budget/{args.model}",
        "--session-id", args.run_id,
        "--session-dir", str(directory / "session"),
        "--name", f"{args.theorem} | {args.model} | {args.run_id}",
        "--", f"/arena {args.theorem}", prompt,
    ]
    if args.dry_run:
        print(f"Validated {args.theorem} with {args.model}; session {args.run_id}; cap ${args.hard_cap_usd:g}")
        print("Pi will write packet, candidate ledger, events, cost, and session under", directory)
        return 0

    if not args.resume_run:
        init(args.theorem, args.run_id, extra)
        (directory / "run-config.json").write_text(json.dumps({"theorem": args.theorem,
            "model": args.model, "hard_cap_usd": args.hard_cap_usd,
            "packet_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "thinking": args.thinking,
            "skill": None if args.no_skill else {"name": "arena-lean", "sha256": skill_hash()}},
            indent=2) + "\n")
    shadow = directory / "scratch" / "project"
    env = os.environ.copy()
    env["ARENA_BUDGET_REQUIRED"] = "1"
    env["ARENA_AUTOCONTINUE"] = "1"
    env["ARENA_RUN_ID"] = args.run_id
    env["ARENA_MODEL"] = args.model
    env["ARENA_HARD_CAP_USD"] = str(args.hard_cap_usd)
    env["ARENA_SKILL_DIR"] = "" if args.no_skill else str(SKILL_DIR)
    if args.no_mcp:
        env["ARENA_NO_MCP"] = "1"
    env.pop("ARENA_STOP_USD", None)
    env["ARENA_BUDGET_REPORT_PATH"] = str(directory / "cost.json")
    worker_command = [sys.executable, "-m", "tools.arena_merge_worker", args.run_id,
                      "--parent-pid", str(os.getpid())]
    worker_log = (directory / "merge-worker.log").open("a")
    worker = subprocess.Popen(worker_command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                              stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)
    worker_log.close()
    print(f"Merge worker pid={worker.pid}; log={directory / 'merge-worker.log'}", flush=True)
    print(f"Pi session={args.run_id}; model={args.model}; actual-usage cap=${args.hard_cap_usd:g}; resume={args.resume_run}", flush=True)
    status_path = directory / "merge-worker.json"
    for _ in range(30):
        if worker.poll() is not None:
            print("Merge worker exited before Pi started; inspect merge-worker.log", file=sys.stderr)
            return 1
        if status_path.exists() and json.loads(status_path.read_text()).get("pid") == worker.pid:
            break
        time.sleep(0.1)
    else:
        print("Merge worker did not become ready; inspect merge-worker.log", file=sys.stderr)
        return 1
    event_log = directory / "events.jsonl"
    event_offset = event_log.stat().st_size if event_log.exists() else 0
    with event_log.open("a") as output:
        process = subprocess.Popen(command, cwd=shadow, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, text=True, bufsize=1)
        assert process.stdout is not None
        for line in process.stdout:
            output.write(line)
            output.flush()
            try:
                log_event(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError):
                print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] non-JSON Pi output recorded", flush=True)
        exit_code = process.wait()
    report_path = directory / "cost.json"
    print(f"Pi exit={exit_code}; events={directory / 'events.jsonl'}; cost={report_path}")
    if exit_code:
        return exit_code
    if not report_path.exists():
        print("Pi did not produce a cost report", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())
    if report.get("error") or report.get("theorem") != args.theorem:
        print(f"Invalid cost report: {report.get('error', 'theorem mismatch')}",
              file=sys.stderr)
        return 1
    if report["hard_cap_usd"] != args.hard_cap_usd:
        print("Arena cap configuration changed", file=sys.stderr)
        return 1
    print(f"Ledger-priced observed tokens=${report['spent_usd']:.6f}; unresolved exposure=${report.get('unresolved_usd', 0):.6f}; cap=${args.hard_cap_usd:.2f}", flush=True)
    embedded = report.get("pi_embedded_estimate") or {}
    if embedded.get("priced_entries") and not embedded.get("missing_entries"):
        print(f"Pi embedded estimate=${embedded['usd']:.6f}; delta=${report['spent_usd'] - embedded['usd']:.6f} (different configured price rates; neither is an invoice)", flush=True)
    cache = report.get("cache_utilization", {})
    if cache.get("all", {}).get("reuse_pct") is not None:
        print(f"Cache reuse: all={cache['all']['reuse_pct']:.1f}% recent-10={cache['recent_ten']['reuse_pct']:.1f}%", flush=True)
    if report["spent_usd"] > args.hard_cap_usd:
        print("Observed usage exceeded the cap on the final in-flight request", file=sys.stderr)
    if attempt_has_model_error(event_log, event_offset):
        print("Pi ended with a model error or abort; inspect events.jsonl", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
