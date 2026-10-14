#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign.

Every failure is one line of JSON: `{"ok": false, "error": "..."}`.
"""

import json
import os
import subprocess
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from arena import reply as tool_reply
from arena import tools as v7_tools
from arena.campaign import (
    autocheck,
    frontier,
    init,
    run_dir,
    state,
    submission,
    write_state,
)
from arena.memory import memory

ACTIONS = (
    "init",
    "frontier",
    "autocheck",
    "state",
    "submission",
    "memory",
    "compile",
    "goal",
    "search",
    "read",
    "finish",
    "reset_delivered",
)


def run(args: SimpleNamespace) -> dict:
    if args.action == "reset_delivered":
        # Compaction calls this with no request: it only forgets what was delivered.
        tool_reply.reset_delivered(args.run_id)
        return tool_reply.reply()
    if args.action in ("compile", "goal", "search", "read", "finish"):
        if args.request_file is None:
            raise ValueError("request-file is required")
        request = json.loads(args.request_file.read_text())
        if not isinstance(request, dict):
            raise ValueError("request-file must contain an object")
        handler = {
            "compile": v7_tools.compile_tool,
            "goal": v7_tools.goal_tool,
            "search": v7_tools.search_tool,
            "read": v7_tools.read_tool,
            "finish": v7_tools.finish_tool,
        }[args.action]
        return tool_reply.attach_context(args.run_id, handler(args.theorem, args.run_id, request))
    if args.action == "init":
        return init(args.theorem, args.run_id)
    if args.action == "frontier":
        return frontier(args.run_id)
    if args.action == "autocheck":
        return autocheck(args.theorem, args.run_id, args.max_seconds)
    if args.action == "state":
        return state(args.run_id)
    if args.action == "memory":
        return memory(args.run_id, args.spent_usd, args.cap_usd)
    if args.action == "submission":
        return submission(args.run_id)
    raise ValueError(f"Unsupported action: {args.action}")


def publish_state(run_id: str) -> None:
    """Refresh state.json after every action; it is derived data, so failures are ignored."""
    try:
        if (run_dir(run_id) / "ledger.jsonl").exists():
            write_state(run_id)
    except Exception:
        pass


def log_tool_error(run_id: str, action: str) -> None:
    """Append the current exception's traceback to the run's tool-errors.log for the operator; never raises."""
    try:
        header = {
            "ts": time.time(),
            "action": action,
            "tool_call_id": os.environ.get("ARENA_TOOL_CALL_ID"),
            "turn": os.environ.get("ARENA_TURN"),
        }
        with (run_dir(run_id) / "tool-errors.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(header) + "\n" + traceback.format_exc() + "\n")
    except Exception:
        pass


@dataclass(frozen=True)
class ProtocolOptions:
    action: str
    theorem: str
    run_id: str
    request_file: Path | None = None
    max_seconds: float | None = None
    spent_usd: float | None = None
    cap_usd: float | None = None


def execute(options: ProtocolOptions) -> int:
    args = SimpleNamespace(**asdict(options))
    try:
        if args.action not in ACTIONS:
            raise ValueError(f"unknown action {args.action!r}")
        result = run(args)
        print(json.dumps(result, ensure_ascii=False))
        publish_state(args.run_id)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        message = " ".join(str(error).split()) or type(error).__name__
        if args.action in ("compile", "goal", "search", "read", "finish", "reset_delivered"):
            log_tool_error(args.run_id, args.action)
            forms = v7_tools.TOOL_FORMS.get(args.action, [])
            print(json.dumps(tool_reply.error_reply("internal_error", message[:400], [], forms), ensure_ascii=False))
            return 2
        print(json.dumps({"ok": False, "error": message[:400]}, ensure_ascii=False))
        return 2
    except Exception as error:
        message = " ".join(str(error).split()) or type(error).__name__
        if args.action in ("compile", "goal", "search", "read", "finish", "reset_delivered"):
            log_tool_error(args.run_id, args.action)
            forms = v7_tools.TOOL_FORMS.get(args.action, [])
            print(json.dumps(tool_reply.error_reply("internal_error", message[:400], [], forms), ensure_ascii=False))
            return 2
        raise
