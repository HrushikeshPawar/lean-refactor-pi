"""One fresh worker assignment. The receipt is durable before the child is opened."""

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
_terminal_states = frozenset(("handled", "completed", "failed"))


def _reject(operation_id: str, reason: str) -> dict:
    return {"ok": False, "category": "invalid_input", "reason": reason, "operation_id": operation_id}


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


def _job_snapshot(directory: Path, job_id: str) -> dict | None:
    delegation = next((row for row in _delegations(directory) if row.get("job_id") == job_id), None)
    if delegation is None:
        return None
    state = delegation.get("state")
    command_id = None
    for row in _states(directory):
        if row.get("activation_id") != delegation.get("activation_id"):
            continue
        state = row.get("state", state)
        if row.get("command_id"):
            command_id = row["command_id"]
    return {
        "job_id": job_id,
        "activation_id": delegation["activation_id"],
        "session_id": delegation["worker_session_id"],
        "actor_id": delegation["actor_id"],
        "state": state,
        "scope": delegation["scope"],
        "anchor": delegation["anchor"],
        "tools": list(delegation["tools"]),
        "command_id": command_id,
        "task": delegation["task"],
    }


def jobs(directory: Path, job_ids: list[str] | None = None) -> dict:
    """Read-only assignment snapshots. This does not start a provider request."""
    found = []
    for row in _delegations(directory):
        if job_ids is not None and row.get("job_id") not in job_ids:
            continue
        snapshot = _job_snapshot(directory, row["job_id"])
        if snapshot is not None:
            found.append(snapshot)
    selected = {row["job_id"] for row in found}
    applicable = [
        row
        for row in _history(directory)
        if row.get("type") in ("delegation", "assignment_state") and row.get("job_id") in selected
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
        snapshot = _job_snapshot(directory, delegation["job_id"])
        if snapshot is not None and snapshot["state"] in _terminal_states:
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
    if kind == "agent_settled" and current.get("state") != "handled":
        if current.get("state") == "active":
            current["state"] = "completed"
        else:
            current["saw_settlement"] = True
    return current


def _take(directory: Path, delegation: dict, command_id: str, current: dict, records: list[dict]) -> None:
    for record in records:
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
    snapshot = _job_snapshot(directory, delegation["job_id"])
    return {
        "ok": True,
        "operation_id": delegation["operation_id"],
        "job_id": delegation["job_id"],
        "activation_id": delegation["activation_id"],
        "session_id": delegation["worker_session_id"],
        "state": snapshot["state"] if snapshot else "launching",
        "scope": delegation["scope"],
        "anchor": delegation["anchor"],
        "tools": list(WORKER_TOOLS),
        "evidence_refs": applied.get("evidence_refs") or [],
        "next_cursor": applied.get("event_seq") or [],
        "accounting": spend["accounting"],
        "total": spend["total"],
        "reused": bool(applied.get("reused")),
    }


def delegate(
    directory: Path,
    *,
    operation_id: str,
    run_id: str,
    actor_id: str,
    session_id: str,
    task: str,
    scope: str,
    anchor: object,
    open_child,
) -> dict:
    """Accept one fresh hypothesis and return before the worker settles."""
    if not operation_id or not run_id or not actor_id or not session_id or not isinstance(task, str) or not task:
        return _reject(operation_id, "identity")
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
        "scope": scope,
        "anchor": resolved,
        "tools": list(WORKER_TOOLS),
        "state": "launching",
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
    try:
        transport = open_child(
            worker_launch(
                directory,
                run_id=run_id,
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
        _write_prompt(transport, prompt_line(command_id, task, stored["anchor"]))
    except Exception as error:
        _record_state(directory, stored, "failed", command_id=command_id, reason=type(error).__name__)
    return _receipt_body(directory, stored, applied, spend)


def awaits_settlement(directory: Path, activation_id: str) -> bool:
    """True only while a real run can still settle. A handled prompt is not a run."""
    for row in _delegations(directory):
        if row.get("activation_id") != activation_id:
            continue
        snapshot = _job_snapshot(directory, row["job_id"])
        return snapshot is not None and snapshot["state"] in ("queued", "launching", "active")
    return False


def join_activation(activation_id: str, timeout: float = 5) -> None:
    with _readers_guard:
        thread = _readers.get(activation_id)
    if thread is not None:
        thread.join(timeout)
