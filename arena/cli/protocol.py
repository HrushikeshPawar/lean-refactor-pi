#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign.

Every failure is one line of JSON: `{"ok": false, "error": "..."}`.
"""

import json
import os
import subprocess
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from arena import coordinator, orchestration, patterns, plans, team_reply, text
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
    "scratch",
    "reset_delivered",
    "await_results",
    "delegate",
    "jobs",
    "cancel",
    "card",
    "patterns",
    "island_turn",
    "plan",
)


# Tool calls the model makes. Each may carry sol's new notices in its `context` (team_reply.sol_notices), not its text.
NOTICE_ACTIONS = ("compile", "goal", "search", "read", "scratch", "patterns", "await_results", "delegate", "jobs",
                  "cancel", "card", "plan")


def run(args: SimpleNamespace) -> dict:
    result = _run(args)
    if args.action in NOTICE_ACTIONS:
        return team_reply.sol_notices(args.run_id, args.action, result)
    return result


def _run(args: SimpleNamespace) -> dict:
    if args.action == "reset_delivered":
        # Compaction calls this with no request: it only forgets what was delivered.
        tool_reply.reset_delivered(args.run_id)
        return tool_reply.reply()
    if args.action in ("compile", "goal", "search", "read", "scratch"):
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
            "scratch": v7_tools.scratch_tool,
        }[args.action]
        # The outer call counts this tool call for a worker's compile nudge; the handler's own attach does not.
        return tool_reply.attach_context(args.run_id, handler(args.theorem, args.run_id, request), action=args.action)
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
    if args.action == "await_results":
        request = {}
        if args.request_file is not None:
            request = json.loads(args.request_file.read_text())
            if not isinstance(request, dict):
                raise ValueError("request-file must contain an object")
        # A normal tool result. no_pending_work continues the turn; it does not finish or delegate.
        result = coordinator.await_results(
            run_dir(args.run_id),
            actor_id=os.environ.get("ARENA_ACTOR_ID") or request.get("actor_id") or "sol",
            cursor=request.get("cursor"),
            job_ids=_resolve_jobs(args.run_id, request.get("job_ids")),
        )
        return _with_text("await_results", result, args.run_id)
    if args.action in ("delegate", "jobs", "cancel"):
        return _with_text(args.action, _management(args), args.run_id)
    if args.action == "patterns":
        if args.request_file is None:
            raise ValueError("request-file is required")
        request = json.loads(args.request_file.read_text())
        if not isinstance(request, dict):
            raise ValueError("request-file must contain an object")
        return patterns.patterns_tool(args.theorem, args.run_id, request)
    if args.action == "card":
        return _with_text("card", _card(args), args.run_id)
    if args.action == "plan":
        return _with_text("plan", _plan(args), args.run_id)
    if args.action == "island_turn":
        # A worker's turn ended: the island extension asks whether to continue. The job comes from the environment.
        job_id, activation_id = os.environ.get("ARENA_JOB_ID"), os.environ.get("ARENA_ACTIVATION_ID")
        if not job_id or not activation_id:
            return {"ok": False, "category": "invalid_input", "reason": "worker_only"}
        return orchestration.island_turn(run_dir(args.run_id), job_id, activation_id)
    raise ValueError(f"Unsupported action: {args.action}")


def _resolve_jobs(run_id: str, job_ids):
    if not isinstance(job_ids, list):
        return job_ids
    return [orchestration.resolve_job(run_dir(run_id), item) for item in job_ids]


def _with_text(action: str, result: dict, run_id: str) -> dict:
    """The model reads `text`: the call's own result. Open requests and the cards the caller has not seen go to
    `context`, which the extension sends with the turn's other ambient lines."""
    directory = run_dir(run_id)
    shown = {**result, "text": team_reply.render(action, result, directory)}
    if result.get("ok") is False:
        return shown
    requests = team_reply.open_requests(directory) if action in ("await_results", "jobs") else []
    cards = tool_reply.card_lines(run_id)
    kinds = [name for name, lines in (("open_requests", requests), ("cards", cards)) if lines]
    return tool_reply.add_context(shown, [requests, cards], kinds)


def _harness_actor() -> str:
    return os.environ.get("ARENA_ACTOR_ID") or "sol"


def _management(args: SimpleNamespace) -> dict:
    """Identity comes from the harness. The request body cannot choose the actor."""
    request = {}
    if args.request_file is not None:
        request = json.loads(args.request_file.read_text())
        if not isinstance(request, dict):
            raise ValueError("request-file must contain an object")
    if args.action == "jobs":
        if any(key != "job_ids" for key in request):
            return {"ok": False, "category": "invalid_input", "reason": text.render("replies/jobs.unknown_input")}
        job_ids = request.get("job_ids")
        if job_ids is not None and (not isinstance(job_ids, list) or any(not isinstance(item, str) for item in job_ids)):
            return {"ok": False, "category": "invalid_input", "reason": "job_ids",
                    "hint": text.render("replies/jobs.job_ids")}
        return orchestration.jobs(run_dir(args.run_id), _resolve_jobs(args.run_id, job_ids))
    identity = {
        "actor_id": _harness_actor(),
        "session_id": os.environ.get("ARENA_SESSION_ID") or args.run_id,
        "operation_id": os.environ.get("ARENA_TOOL_CALL_ID") or "",
        "run_id": args.run_id,
    }
    if args.action == "cancel":
        return coordinator.submit(run_dir(args.run_id), {
            "action": "cancel", "job_id": orchestration.resolve_job(run_dir(args.run_id), request.get("job_id")), **identity,
        })
    return coordinator.submit(run_dir(args.run_id), {
        "action": "delegate",
        "task": request.get("task"),
        "scope": request.get("scope"),
        "job_id": orchestration.resolve_job(run_dir(args.run_id), request.get("job_id")),
        "at": request.get("at"),
        "objective": request.get("objective"),
        **identity,
    })


def _card(args: SimpleNamespace) -> dict:
    """An actor's card save. Identity comes from the harness environment, never from the request."""
    request = json.loads(args.request_file.read_text()) if args.request_file is not None else {}
    fields = {name: request[name].strip() for name in orchestration.CARD_FIELDS if isinstance(request.get(name), str)} \
        if isinstance(request, dict) else {}
    if not fields:
        return {"ok": False, "category": "invalid_input", "reason": "fields",
                "hint": text.render("replies/team.card_empty")}
    actor = _harness_actor()
    return orchestration.save_card(
        run_dir(args.run_id), operation_id=os.environ.get("ARENA_TOOL_CALL_ID") or uuid.uuid4().hex,
        job_id=os.environ.get("ARENA_JOB_ID") if actor != "sol" else None, run_id=args.run_id, actor_id=actor,
        session_id=os.environ.get("ARENA_SESSION_ID") or args.run_id, fields=fields,
    )


def _plan(args: SimpleNamespace) -> dict:
    """The orchestrator's plan save. Identity comes from the harness environment, never from the request."""
    request = json.loads(args.request_file.read_text()) if args.request_file is not None else {}
    steps = request.get("steps") if isinstance(request, dict) else None
    return plans.save_plan(
        run_dir(args.run_id), operation_id=os.environ.get("ARENA_TOOL_CALL_ID") or uuid.uuid4().hex,
        run_id=args.run_id, actor_id=_harness_actor(),
        session_id=os.environ.get("ARENA_SESSION_ID") or args.run_id, steps=steps,
    )


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
        if args.action in ("compile", "goal", "search", "read", "scratch", "reset_delivered"):
            log_tool_error(args.run_id, args.action)
            forms = v7_tools.TOOL_FORMS.get(args.action, [])
            print(json.dumps(tool_reply.error_reply("internal_error", message[:400], [], forms), ensure_ascii=False))
            return 2
        print(json.dumps({"ok": False, "error": message[:400]}, ensure_ascii=False))
        return 2
    except Exception as error:
        message = " ".join(str(error).split()) or type(error).__name__
        if args.action in ("compile", "goal", "search", "read", "scratch", "reset_delivered"):
            log_tool_error(args.run_id, args.action)
            forms = v7_tools.TOOL_FORMS.get(args.action, [])
            print(json.dumps(tool_reply.error_reply("internal_error", message[:400], [], forms), ensure_ascii=False))
            return 2
        raise
