"""Worker assignments. A receipt is durable before the child is opened.

A passing tool result is published while the activation is still active.
A follow-up reuses the hypothesis session; a second prompt to an active job is busy.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path

from arena import run_control
from arena.campaign import _append, events
from arena.pi_rpc import WORKER_TOOLS, FrameReader, prompt_line, worker_launch
from arena.run_control import OperationRejected

_readers: dict[str, threading.Thread] = {}
_readers_guard = threading.Lock()
_terminal_states = frozenset(("handled", "completed", "failed", "exhausted"))
_active_states = frozenset(("launching", "queued", "active"))


def _reject(operation_id: str, reason: str, category: str = "invalid_input") -> dict:
    return {"ok": False, "category": category, "reason": reason, "operation_id": operation_id}


def _resolve_anchor(directory: Path, scope: str, anchor: object) -> dict | str:
    """Resolve a caller reference against the saved proof. Caller hashes are not copied."""
    if scope not in ("proof", "step") or not isinstance(anchor, dict):
        return "scope"
    ref = anchor.get("node")
    if not isinstance(ref, str) or not ref:
        return "node"
    if scope == "proof" and ("steps" in anchor or "hole" in anchor):
        return "anchor"
    if scope == "step" and ("steps" in anchor) == ("hole" in anchor):
        return "anchor"
    from arena.campaign import _proof_reader
    from arena.graph import Graph

    graph = Graph.from_history(
        events(directory),
        _proof_reader(directory),
        committed_operations=run_control.committed_operation_ids(directory),
    )
    node = next((item for item in graph.nodes if item.id == ref or item.proof_id == ref), None)
    path = None if node is None else directory / "proofs" / f"{node.proof_id}.lean"
    if node is None or path is None or not path.is_file():
        return "node"
    resolved = {
        "node": node.id,
        "proof_id": node.proof_id,
        "proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "path": f"proofs/{node.proof_id}.lean",
    }
    if scope == "proof":
        return resolved
    if "hole" in anchor:
        hole_ref = anchor.get("hole")
        if not isinstance(hole_ref, str) or not hole_ref:
            return "hole"
        match = next(
            (
                hole
                for hole in node.holes
                if hole_ref in {str(hole["index"]), f"h{hole['index']}", hole.get("id"), f"{node.id}.h{hole['index']}"}
            ),
            None,
        )
        if match is None:
            return "hole"
        resolved["hole"] = f"{node.id}.h{match['index']}"
        resolved["source"] = {"line": match["line"], "column": match["column"]}
        return resolved
    steps = anchor.get("steps")
    if not isinstance(steps, list) or len(steps) != 2 or not all(isinstance(item, int) for item in steps):
        return "steps"
    start, end = steps
    if start < 1 or end > len(node.steps) or start > end:
        return "steps"
    chosen = node.steps[start - 1 : end]
    resolved["steps"] = [start, end]
    resolved["step_ids"] = [step.id for step in chosen]
    resolved["step_hashes"] = [step.hash for step in chosen]
    resolved["source"] = {"first_line": chosen[0].first_line, "last_line": chosen[-1].last_line}
    return resolved


def _delegations(directory: Path) -> list[dict]:
    return [row for row in _history(directory) if row.get("type") == "delegation"]


def _history(directory: Path) -> list[dict]:
    return run_control.published_history(directory, events(directory))


def _states(directory: Path) -> list[dict]:
    return [row for row in _history(directory) if row.get("type") == "assignment_state"]


def _job_rows(directory: Path, job_id: str) -> list[dict]:
    return [row for row in _delegations(directory) if row.get("job_id") == job_id]


def _activation_view(directory: Path, delegation: dict) -> dict:
    state = delegation.get("state")
    command_id = None
    for row in _states(directory):
        if row.get("activation_id") != delegation.get("activation_id"):
            continue
        state = row.get("state", state)
        if row.get("command_id"):
            command_id = row["command_id"]
    return {
        "activation_id": delegation["activation_id"],
        "state": state,
        "task": delegation["task"],
        "command_id": command_id,
        "resumed": bool(delegation.get("resumed")),
    }


def _job_snapshot(directory: Path, job_id: str) -> dict | None:
    rows = _job_rows(directory, job_id)
    if not rows:
        return None
    original = rows[0]
    delegation = rows[-1]
    current = _activation_view(directory, delegation)
    findings = [
        {
            "event_id": row.get("event_id"),
            "activation_id": row.get("activation_id"),
            "request_id": row.get("request_id"),
            "attempt_id": row.get("attempt_id"),
            "proof_id": row.get("proof_id"),
            "evaluation_id": row.get("evaluation_id"),
        }
        for row in _history(directory)
        if row.get("type") == "worker_finding" and row.get("job_id") == job_id
    ]
    return {
        "job_id": job_id,
        "activation_id": delegation["activation_id"],
        "session_id": original["worker_session_id"],
        "actor_id": original["actor_id"],
        "state": current["state"],
        "scope": original["scope"],
        "anchor": original["anchor"],
        "hypothesis": original.get("hypothesis", original["task"]),
        "tools": list(original["tools"]),
        "command_id": current["command_id"],
        "task": delegation["task"],
        "resumed": bool(delegation.get("resumed")),
        "activations": [_activation_view(directory, row) for row in rows],
        "findings": findings,
    }


def jobs(directory: Path, job_ids: list[str] | None = None) -> dict:
    """Read-only assignment snapshots. This does not start a provider request."""
    found = []
    seen: set[str] = set()
    for row in _delegations(directory):
        if row.get("job_id") in seen:
            continue
        if job_ids is not None and row.get("job_id") not in job_ids:
            continue
        seen.add(row["job_id"])
        snapshot = _job_snapshot(directory, row["job_id"])
        if snapshot is not None:
            found.append(snapshot)
    selected = {row["job_id"] for row in found}
    applicable = [
        row
        for row in _history(directory)
        if row.get("type") in ("delegation", "assignment_state", "worker_finding") and row.get("job_id") in selected
    ]
    spend = run_control.read_state(directory)
    return {
        "ok": True,
        "jobs": found,
        "events": applicable,
        "next_cursor": applicable[-1].get("event_id") if applicable else None,
        "accounting": spend["accounting"],
        "total": spend["total"],
    }


def _record_state(directory: Path, delegation: dict, state: str, **extra) -> None:
    with _readers_guard:
        snapshot = _activation_view(directory, delegation)
        if snapshot["state"] in _terminal_states:
            return
        _append(
            directory,
            {
                "schema_version": run_control.SCHEMA_VERSION,
                "event_id": uuid.uuid4().hex,
                "type": "assignment_state",
                "operation_id": delegation["operation_id"],
                "run_id": delegation["run_id"],
                "actor_id": delegation["actor_id"],
                "session_id": delegation["session_id"],
                "job_id": delegation["job_id"],
                "activation_id": delegation["activation_id"],
                "state": state,
                **extra,
            },
        )


def _compile_findings(directory: Path, delegation: dict, record: dict) -> list[dict]:
    if record.get("type") != "tool_execution_end" or record.get("toolName") != "compile" or record.get("isError"):
        return []
    result = record.get("result")
    details = result.get("details") if isinstance(result, dict) else None
    if not isinstance(details, dict) or details.get("ok") is False:
        return []
    history = _history(directory)
    attempts = {row.get("event_id"): row for row in history if row.get("kind") == "attempt"}
    findings = []
    for item in details.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "closed" or item.get("ok") is False:
            continue
        for reference in item.get("attempts") or []:
            if not isinstance(reference, dict):
                continue
            attempt = attempts.get(reference.get("attempt_id"))
            if attempt is None:
                continue
            tool_call = attempt.get("tool_call_id") or (attempt.get("data") or {}).get("tool_call_id")
            if (
                not record.get("toolCallId") or tool_call != record["toolCallId"]
                or attempt.get("actor_id") != delegation["worker_actor_id"]
                or attempt.get("session_id") != delegation["worker_session_id"]
            ):
                continue
            proof_id = attempt.get("proof_id") or attempt.get("candidate_id")
            evaluation = next((
                row for row in reversed(history)
                if row.get("kind") == "evaluation" and row.get("candidate_id") == proof_id
                and row.get("key") and (row.get("result") or {}).get("ok") is True
            ), None)
            if evaluation is not None:
                findings.append({
                    "attempt_id": attempt["event_id"], "proof_id": proof_id,
                    "evaluation_id": evaluation["key"], "request_id": attempt.get("request_id"),
                })
    return findings


def _observe_tool(directory: Path, delegation: dict, record: dict) -> bool:
    """Publish a passing candidate at the tool boundary. This does not settle the assignment."""
    if record.get("type") != "tool_execution_end":
        return False
    for finding in _compile_findings(directory, delegation, record):
        if any(
            row.get("type") == "worker_finding" and row.get("activation_id") == delegation["activation_id"]
            and row.get("attempt_id") == finding["attempt_id"] and row.get("evaluation_id") == finding["evaluation_id"]
            for row in _history(directory)
        ):
            continue
        _append(
            directory,
            {
                "schema_version": run_control.SCHEMA_VERSION,
                "event_id": uuid.uuid4().hex,
                "type": "worker_finding",
                "operation_id": delegation["operation_id"],
                "run_id": delegation["run_id"],
                "actor_id": delegation["worker_actor_id"],
                "session_id": delegation["worker_session_id"],
                "job_id": delegation["job_id"],
                "activation_id": delegation["activation_id"],
                **finding,
            },
        )
    return True


def _apply_record(record: dict, command_id: str, current: dict) -> dict:
    if current["state"] in _terminal_states:
        return current
    kind = record.get("type")
    if kind == "response" and record.get("id") == command_id:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        disposition = data.get("disposition")
        if record.get("success") is not True:
            current["state"] = "failed"
            current["reason"] = "prompt_rejected"
        elif disposition == "handled":
            current["state"] = "handled"
            current["outcome"] = "no_run"
        elif disposition in ("started", "queued"):
            current["disposition"] = disposition
            current["state"] = "completed" if current.get("saw_settlement") else "active"
        else:
            current["state"] = "failed"
            current["reason"] = "invalid_prompt_disposition"
        return current
    if kind == "assignment_exhausted" and current.get("state") == "active":
        current["state"] = "exhausted"
        return current
    if kind == "agent_settled" and current.get("state") != "handled":
        if current.get("state") == "active":
            current["state"] = "completed"
        else:
            current["saw_settlement"] = True
    return current


def _take(directory: Path, delegation: dict, command_id: str, current: dict, records: list[dict]) -> None:
    for record in records:
        if current["state"] not in _terminal_states and _observe_tool(directory, delegation, record):
            continue
        previous = current["state"]
        _apply_record(record, command_id, current)
        if current["state"] == previous:
            continue
        _record_state(
            directory,
            delegation,
            current["state"],
            command_id=command_id,
            outcome=current.get("outcome"),
            disposition=current.get("disposition"),
            reason=current.get("reason"),
        )


def _read_child(directory: Path, delegation: dict, command_id: str, transport, ready: threading.Event) -> None:
    reader = FrameReader()
    current = {"state": "launching"}
    ready.set()
    try:
        while True:
            chunk = transport.read(4096)
            if not chunk:
                if current["state"] in ("launching", "queued", "active"):
                    current["state"] = "failed"
                    _record_state(directory, delegation, "failed", command_id=command_id, reason="process_exit")
                break
            _take(directory, delegation, command_id, current, reader.feed(chunk))
    except Exception as error:
        if current["state"] not in _terminal_states:
            _record_state(directory, delegation, "failed", command_id=command_id, reason=type(error).__name__)


def _write_prompt(transport, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = transport.write(payload[offset:])
        if written is None:
            break
        if type(written) is not int or written <= 0 or written > len(payload) - offset:
            raise OSError("invalid prompt write count")
        offset += written
    flush = getattr(transport, "flush", None)
    if flush is not None:
        flush()


def _receipt_body(directory: Path, delegation: dict, applied: dict, spend: dict) -> dict:
    snapshot = _activation_view(directory, delegation)
    return {
        "ok": True,
        "operation_id": delegation["operation_id"],
        "job_id": delegation["job_id"],
        "activation_id": delegation["activation_id"],
        "session_id": delegation["worker_session_id"],
        "state": snapshot["state"],
        "scope": delegation["scope"],
        "anchor": delegation["anchor"],
        "tools": list(WORKER_TOOLS),
        "hypothesis": delegation.get("hypothesis", delegation["task"]),
        "evidence_refs": applied.get("evidence_refs") or [],
        "next_cursor": applied.get("event_seq") or [],
        "accounting": spend["accounting"],
        "total": spend["total"],
        "reused": bool(applied.get("reused")),
        "resumed": bool(delegation.get("resumed")),
    }


def deliver(directory: Path, actor_id: str) -> dict:
    """Findings already published for this actor, including those from an active assignment."""
    view = jobs(directory)
    results = []
    owned = [job for job in view["jobs"] if job.get("actor_id") == actor_id]
    for job in owned:
        original = job["activations"][0]["activation_id"]
        results.extend({
            **finding,
            "job_id": job["job_id"],
            "session_id": job["session_id"],
            "resumed": finding.get("activation_id") != original,
        } for finding in job["findings"])
    spend = run_control.read_state(directory)
    return {
        "ok": True,
        "results": results,
        "jobs": owned,
        "accounting": view["accounting"],
        "total": view["total"],
        "stopped": spend["stopped"],
    }


def _open_activation(directory: Path, stored: dict, open_child, command_id: str) -> None:
    try:
        transport = open_child(
            worker_launch(
                directory,
                run_id=stored["run_id"],
                worker_actor_id=stored["worker_actor_id"],
                worker_session_id=stored["worker_session_id"],
                job_id=stored["job_id"],
                activation_id=stored["activation_id"],
                anchor=stored["anchor"],
            )
        )
        transport.subscribe()
        ready = threading.Event()
        thread = threading.Thread(
            target=_read_child,
            args=(directory, stored, command_id, transport, ready),
            daemon=True,
        )
        with _readers_guard:
            _readers[stored["activation_id"]] = thread
        thread.start()
        if not ready.wait(5):
            raise RuntimeError("reader did not start")
        _write_prompt(transport, prompt_line(command_id, stored["task"], stored["anchor"]))
    except Exception as error:
        _record_state(directory, stored, "failed", command_id=command_id, reason=type(error).__name__)


def _same_anchor(directory: Path, stored: dict, scope: str | None, anchor: object) -> bool:
    if scope is None and anchor is None:
        return True
    if scope != stored["scope"]:
        return False
    resolved = _resolve_anchor(directory, scope or "", anchor)
    return False if isinstance(resolved, str) else resolved == stored["anchor"]


def _follow_up(
    directory: Path,
    *,
    operation_id: str,
    run_id: str,
    actor_id: str,
    session_id: str,
    task: str,
    scope: str | None,
    anchor: object,
    job_id: str,
    open_child,
) -> dict:
    activation_id = uuid.uuid4().hex

    def mutate(writer) -> list:
        writer.append_ledger({"type": "delegation", **delegation})
        return []

    try:
        with run_control.control_lock(directory):
            current = _job_snapshot(directory, job_id)
            if current is None:
                return _reject(operation_id, "job", "not_found")
            source = _job_rows(directory, job_id)[0]
            if run_id != source["run_id"] or actor_id != source["actor_id"]:
                return _reject(operation_id, "ownership")
            if not _same_anchor(directory, current, scope, anchor):
                return _reject(operation_id, "anchor")
            arguments = {
                "job_id": job_id,
                "task": task,
                "run_id": run_id,
                "actor_id": actor_id,
                "session_id": session_id,
                "scope": source["scope"],
                "anchor": source["anchor"],
            }
            control_rows = run_control._abort_open_intents(directory, run_control._control_rows(directory))
            existing = run_control._receipt(control_rows, operation_id)
            if existing is None and current["state"] in _active_states:
                return _reject(operation_id, "active", "busy")
            delegation = {
                "operation_id": operation_id,
                "run_id": source["run_id"],
                "actor_id": source["actor_id"],
                "session_id": session_id,
                "job_id": job_id,
                "activation_id": activation_id,
                "worker_session_id": source["worker_session_id"],
                "worker_actor_id": source["worker_actor_id"],
                "task": task,
                "hypothesis": source.get("hypothesis", source["task"]),
                "scope": source["scope"],
                "anchor": source["anchor"],
                "tools": list(source["tools"]),
                "state": "launching",
                "resumed": True,
            }
            applied = run_control._apply_locked(
                directory,
                {
                    "operation_id": operation_id,
                    "kind": "delegate",
                    "arguments": arguments,
                    "run_id": run_id,
                    "actor_id": actor_id,
                    "session_id": session_id,
                    "job_id": job_id,
                    "activation_id": activation_id,
                },
                mutate,
            )
    except OperationRejected as error:
        return _reject(operation_id, error.category)
    if not applied.get("ok"):
        return applied
    if applied.get("status") == "aborted":
        return {**applied, "ok": False, "category": "operation_aborted"}
    stored = next((row for row in _delegations(directory) if row.get("operation_id") == operation_id), None)
    if stored is None:
        return {**applied, "ok": False, "category": "missing_delegation"}
    spend = run_control.read_state(directory)
    if stored["activation_id"] != activation_id:
        return _receipt_body(directory, stored, {**applied, "reused": True}, spend)
    command_id = uuid.uuid4().hex
    _record_state(directory, stored, "launching", command_id=command_id)
    _open_activation(directory, stored, open_child, command_id)
    return _receipt_body(directory, stored, applied, spend)


def delegate(
    directory: Path,
    *,
    operation_id: str,
    run_id: str,
    actor_id: str,
    session_id: str,
    task: str,
    open_child,
    scope: str | None = None,
    anchor: object = None,
    job_id: str | None = None,
) -> dict:
    """Accept one hypothesis, or resume its saved session, and return before the worker settles."""
    if not operation_id or not run_id or not actor_id or not session_id or not isinstance(task, str) or not task:
        return _reject(operation_id, "identity")
    if job_id:
        return _follow_up(
            directory,
            operation_id=operation_id,
            run_id=run_id,
            actor_id=actor_id,
            session_id=session_id,
            task=task,
            scope=scope,
            anchor=anchor,
            job_id=job_id,
            open_child=open_child,
        )
    if scope is None or anchor is None:
        return _reject(operation_id, "scope")
    resolved = _resolve_anchor(directory, scope, anchor)
    if isinstance(resolved, str):
        return _reject(operation_id, resolved)
    job_id = uuid.uuid4().hex
    activation_id = uuid.uuid4().hex
    worker_session_id = uuid.uuid4().hex
    worker_actor_id = uuid.uuid4().hex
    arguments = {
        "task": task,
        "scope": scope,
        "anchor": resolved,
        "actor_id": actor_id,
        "session_id": session_id,
    }
    delegation = {
        "operation_id": operation_id,
        "run_id": run_id,
        "actor_id": actor_id,
        "session_id": session_id,
        "job_id": job_id,
        "activation_id": activation_id,
        "worker_session_id": worker_session_id,
        "worker_actor_id": worker_actor_id,
        "task": task,
        "hypothesis": task,
        "scope": scope,
        "anchor": resolved,
        "tools": list(WORKER_TOOLS),
        "state": "launching",
        "resumed": False,
    }

    def mutate(writer) -> list:
        writer.append_ledger({"type": "delegation", **delegation})
        return []

    try:
        applied = run_control.apply_operation(
            directory,
            {
                "operation_id": operation_id,
                "kind": "delegate",
                "arguments": arguments,
                "run_id": run_id,
                "actor_id": actor_id,
                "session_id": session_id,
                "job_id": job_id,
                "activation_id": activation_id,
            },
            mutate,
        )
    except OperationRejected as error:
        return _reject(operation_id, error.category)
    if not applied.get("ok"):
        return applied
    if applied.get("status") == "aborted":
        return {**applied, "ok": False, "category": "operation_aborted"}
    stored = next((row for row in _delegations(directory) if row.get("operation_id") == operation_id), None)
    if stored is None:
        return {**applied, "ok": False, "category": "missing_delegation"}
    spend = run_control.read_state(directory)
    if stored["job_id"] != job_id:
        return _receipt_body(directory, stored, {**applied, "reused": True}, spend)
    # The receipt is already durable. Open the reader, then write the prompt.
    command_id = uuid.uuid4().hex
    _record_state(directory, stored, "launching", command_id=command_id)
    _open_activation(directory, stored, open_child, command_id)
    return _receipt_body(directory, stored, applied, spend)


def awaits_settlement(directory: Path, activation_id: str) -> bool:
    """True only while this activation can still settle. A handled prompt is not a run."""
    for row in _delegations(directory):
        if row.get("activation_id") != activation_id:
            continue
        return _activation_view(directory, row)["state"] in _active_states
    return False


def join_activation(activation_id: str, timeout: float = 5) -> None:
    with _readers_guard:
        thread = _readers.get(activation_id)
    if thread is not None:
        thread.join(timeout)
