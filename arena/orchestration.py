"""Worker assignments. A receipt is durable before the child is opened.

At most two model activations own a slot. A queued job waits for a real exit.
Cancellation clears queued prompts, then aborts, and keeps the slot until the child is gone.
A passing tool result is published while the activation is still active.
A follow-up reuses the hypothesis session; a second prompt to an active job is busy.
"""

from __future__ import annotations

import fcntl
import hashlib
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from arena import run_control
from arena.campaign import _append, events
from arena.pi_rpc import WORKER_TOOLS, FrameReader, cancel_lines, prompt_line, worker_launch
from arena.run_control import OperationRejected

_MODEL_SLOTS = 2
_readers: dict[str, threading.Thread] = {}
_owned: dict[str, object] = {}
_live: dict[str, dict] = {}
_openers: dict[str, object] = {}
_stop_sent: set[str] = set()
_io_locks: dict[str, threading.RLock] = {}
_launch_gates = threading.local()
_readers_guard = threading.Lock()
_terminal_states = frozenset(("handled", "completed", "failed", "exhausted", "cancelled"))
_active_states = frozenset(("launching", "queued", "active"))
_live_states = frozenset(("queued", "launching", "active", "cancelling"))
_interest = threading.Condition()
_epoch = 0
_terminal_checks = frozenset(("passed", "proof_error", "inconclusive"))


def _wake() -> None:
    global _epoch
    with _interest:
        _epoch += 1
        _interest.notify_all()


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
    occupies_slot = state == "launching"
    command_id = None
    recovery_state = None
    for row in _states(directory):
        if row.get("activation_id") != delegation.get("activation_id"):
            continue
        state = row.get("state", state)
        occupies_slot = row.get("occupies_slot", occupies_slot)
        if row.get("command_id"):
            command_id = row["command_id"]
        if row.get("recovery_state"):
            recovery_state = row["recovery_state"]
    return {
        "activation_id": delegation["activation_id"],
        "state": state,
        "task": delegation["task"],
        "command_id": command_id,
        "resumed": bool(delegation.get("resumed")),
        "occupies_slot": occupies_slot,
        "recovery_state": recovery_state,
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
        "occupies_slot": current["occupies_slot"],
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
        "queue": [job["job_id"] for job in found if job["state"] == "queued"],
        "next_cursor": applicable[-1].get("event_id") if applicable else None,
        "accounting": spend["accounting"],
        "total": spend["total"],
    }


def _slot_count(directory: Path) -> int:
    return sum(1 for row in _delegations(directory) if _activation_view(directory, row)["occupies_slot"])


def _can_admit_directly(directory: Path) -> bool:
    return _slot_count(directory) < _MODEL_SLOTS and not any(
        _activation_view(directory, row)["state"] == "queued" for row in _delegations(directory)
    )


def _append_state(directory: Path, delegation: dict, state: str, **extra) -> None:
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
    _wake()


def _control_generation(directory: Path) -> str | None:
    return next(
        (
            row.get("generation")
            for row in reversed(run_control._control_rows(directory))
            if row.get("kind") == "run_generation" and row.get("generation")
        ),
        None,
    )


def _run_status(directory: Path) -> str | None:
    return next(
        (
            row.get("status")
            for row in reversed(run_control._control_rows(directory))
            if row.get("kind") == "run_state"
        ),
        None,
    )


def _recovering(directory: Path) -> bool:
    return _run_status(directory) == "recovering"


def _ownership_rows(directory: Path, activation_id: str) -> list[dict]:
    return [
        row for row in _history(directory)
        if row.get("type") == "process_ownership" and row.get("activation_id") == activation_id
    ]


def _append_ownership(directory: Path, delegation: dict, **fields) -> None:
    _append(
        directory,
        {
            "schema_version": run_control.SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "type": "process_ownership",
            "operation_id": delegation["operation_id"],
            "run_id": delegation["run_id"],
            "actor_id": delegation["actor_id"],
            "session_id": delegation.get("worker_session_id"),
            "job_id": delegation["job_id"],
            "activation_id": delegation["activation_id"],
            **fields,
        },
    )


def _request_uncertain(directory: Path, session_id: str | None = None) -> bool:
    rows = run_control._control_rows(directory)
    coverage = run_control._apply_coverage(rows)
    known = coverage["covered"] - set(coverage["unknown"])
    if any(
        row.get("kind") == "settlement"
        and (session_id is None or row.get("session_id") == session_id)
        and set(row.get("covered_request_ids") or []).intersection(coverage["unknown"])
        for row in rows
    ):
        return True
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("kind") not in ("dispatch_intent", "dispatch") or not row.get("attempt_id"):
            continue
        if session_id is not None and row.get("session_id") != session_id:
            continue
        latest[row["attempt_id"]] = row
    return any(
        row.get("request_id") not in known
        and row.get("status") not in ("rejected_before_dispatch", "failed_before_start")
        and row.get("sent") is not False
        for row in latest.values()
    )


def _set_run(directory: Path, status: str, generation: str | None = None) -> None:
    with run_control.control_lock(directory):
        run_control._append_control(
            directory,
            {
                "schema_version": run_control.SCHEMA_VERSION,
                "kind": "run_state",
                "event_id": uuid.uuid4().hex,
                "status": status,
            },
        )
        if generation is not None:
            run_control._append_control(
                directory,
                {
                    "schema_version": run_control.SCHEMA_VERSION,
                    "kind": "run_generation",
                    "event_id": uuid.uuid4().hex,
                    "generation": generation,
                    "status": status,
                },
            )


def _fill_slots(directory: Path) -> None:
    """Open the oldest queued assignment only while a model slot is free."""
    while True:
        with run_control.control_lock(directory):
            if _recovering(directory) or _slot_count(directory) >= _MODEL_SLOTS:
                return
            queued = next(
                (row for row in _delegations(directory) if _activation_view(directory, row)["state"] == "queued"),
                None,
            )
            if queued is None:
                return
            opener = _openers.get(queued["activation_id"])
            if opener is None:
                return
            command_id = uuid.uuid4().hex
            _append_state(directory, queued, "launching", command_id=command_id, occupies_slot=True)
        _open_activation(directory, queued, opener, command_id)


def _record_state(directory: Path, delegation: dict, state: str, *, expected_transport=None,
                  expected_generation=None, **extra) -> None:
    with run_control.control_lock(directory):
        if expected_transport is not None and (
            _owned.get(delegation["activation_id"]) is not expected_transport or _recovering(directory)
            or expected_generation != _control_generation(directory)
        ):
            return
        snapshot = _activation_view(directory, delegation)
        if snapshot["state"] in _terminal_states:
            return
        if snapshot["state"] == "cancelling" and state != "cancelled":
            return
        _append_state(directory, delegation, state, **extra)
        live = _live.get(delegation["activation_id"])
        if live is not None:
            live["state"] = state
    if state in _terminal_states:
        _stop_activation(directory, delegation, expected_transport=expected_transport,
                         expected_generation=expected_generation)


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
    """Publish a passing candidate while the caller holds the run-control lock."""
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
        _wake()
    return True


def _apply_record(record: dict, command_id: str, current: dict) -> dict:
    if current["state"] in _terminal_states or current["state"] == "cancelling":
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
        with run_control.control_lock(directory):
            if (
                _recovering(directory)
                or current.get("generation") != _control_generation(directory)
                or _owned.get(delegation["activation_id"]) is not current.get("transport")
            ):
                continue
            current["state"] = _activation_view(directory, delegation)["state"]
            if current["state"] not in _terminal_states and _observe_tool(directory, delegation, record):
                continue
            previous = current["state"]
            _apply_record(record, command_id, current)
            changed = current["state"] != previous
            if changed:
                _append_state(
                    directory, delegation, current["state"], command_id=command_id,
                    outcome=current.get("outcome"), disposition=current.get("disposition"),
                    reason=current.get("reason"),
                )
        if changed and current["state"] in _terminal_states:
            _stop_activation(directory, delegation, expected_transport=current["transport"],
                             expected_generation=current["generation"])


def _read_child(directory: Path, delegation: dict, command_id: str, transport, ready: threading.Event,
                generation: str) -> None:
    reader = FrameReader()
    with run_control.control_lock(directory):
        current = {"state": _activation_view(directory, delegation)["state"],
                   "generation": generation, "transport": transport}
        _live[delegation["activation_id"]] = current
    ready.set()
    try:
        while True:
            chunk = transport.read(4096)
            if not chunk:
                if current["state"] in _active_states:
                    _record_state(directory, delegation, "failed", expected_transport=transport,
                                  expected_generation=generation, command_id=command_id, reason="stdout_closed")
                observe_exit(directory, delegation["activation_id"], expected_transport=transport,
                             expected_generation=generation)
                break
            _take(directory, delegation, command_id, current, reader.feed(chunk))
    except Exception as error:
        if current["state"] not in _terminal_states and current["state"] != "cancelling":
            _record_state(directory, delegation, "failed", expected_transport=transport,
                          expected_generation=generation, command_id=command_id, reason=type(error).__name__)
        if _owned.get(delegation["activation_id"]) is transport and not _recovering(directory):
            _stop_activation(directory, delegation, expected_transport=transport, expected_generation=generation)


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


def _live_ownership(rows: list[dict]) -> dict | None:
    spawned = None
    for row in rows:
        if row.get("phase") == "intent":
            spawned = None
        elif row.get("phase") == "spawned":
            spawned = row
        elif row.get("phase") in ("exited", "not_spawned"):
            spawned = None
    return spawned


def _identified(stored: dict, reading: dict | None) -> bool:
    return bool(
        reading and reading.get("alive") is True
        and stored.get("start_id") and reading.get("start_id") == stored["start_id"]
        and reading.get("run_id") == stored.get("run_id")
        and (reading.get("generation") is None or reading["generation"] == stored.get("generation"))
    )


def note_worker_event(directory: Path, *, activation_id: str, generation: str, evidence: dict | None = None) -> dict:
    """Retain validated late evidence without changing process or activation ownership."""
    from arena.campaign import _verification_outcome

    with run_control.control_lock(directory):
        delegation = next((row for row in _delegations(directory) if row["activation_id"] == activation_id), None)
        if delegation is None:
            return {"ok": False, "category": "not_found", "evidence": False, "state_changed": False}
        snapshot = _activation_view(directory, delegation)
        owned_generation = next(
            (row.get("generation") for row in reversed(_ownership_rows(directory, activation_id)) if row.get("generation")),
            None,
        )
        stale = (
            generation != owned_generation or generation != _control_generation(directory)
            or snapshot["state"] in ("cancelled", "cancelling", "recovering")
        )
        history = _history(directory)
        attempt = next((row for row in history if row.get("kind") == "attempt"
                        and row.get("event_id") == (evidence or {}).get("attempt_id")
                        and row.get("actor_id") == delegation["worker_actor_id"]
                        and row.get("session_id") == delegation["worker_session_id"]
                        and row.get("activation_id") == activation_id
                        and row.get("generation") == generation), None)
        proof_id = None if attempt is None else attempt.get("proof_id") or attempt.get("candidate_id")
        passing = proof_id and proof_id == (evidence or {}).get("proof_id") and any(
            row.get("kind") == "evaluation" and row.get("candidate_id") == proof_id
            and row.get("key") == (evidence or {}).get("evaluation_id")
            and _verification_outcome(row.get("result") or {}) == "passed" for row in history
        )
        valid = bool(stale and passing)
        duplicate = any(row.get("type") == "worker_finding" and row.get("activation_id") == activation_id
                        and row.get("attempt_id") == (evidence or {}).get("attempt_id")
                        and row.get("evaluation_id") == (evidence or {}).get("evaluation_id") for row in history)
        if valid and not duplicate:
            _append(directory, {
                "schema_version": run_control.SCHEMA_VERSION, "event_id": uuid.uuid4().hex,
                "type": "worker_finding", "operation_id": delegation["operation_id"],
                "run_id": delegation["run_id"], "actor_id": delegation["worker_actor_id"],
                "session_id": delegation["worker_session_id"], "job_id": delegation["job_id"],
                "activation_id": activation_id, "generation": generation,
                "attempt_id": attempt["event_id"], "proof_id": proof_id,
                "evaluation_id": evidence["evaluation_id"], "request_id": attempt.get("request_id"), "late": True,
            })
            _wake()
        return {"ok": True, "evidence": valid, "state_changed": False}


def _reconcile_owned(directory: Path, delegation: dict, inspect, signal) -> bool:
    rows = _ownership_rows(directory, delegation["activation_id"])
    owned = _live_ownership(rows)
    if owned is None:
        return not rows or rows[-1].get("phase") in ("exited", "not_spawned")
    if not owned.get("pid") or not owned.get("start_id"):
        return False
    probe = getattr(inspect, "owned_group", None)
    reading = probe(owned) if probe is not None else inspect(owned["pid"])
    if reading is None:
        return False
    if reading.get("group_alive") is not False:
        if reading.get("group_alive") is not True or not _identified(owned, reading):
            return False
        signal(owned.get("pgid", owned["pid"]))
        reading = probe(owned) if probe is not None else inspect(owned["pid"])
        if reading is None or reading.get("group_alive") is not False:
            return False
    with run_control.control_lock(directory):
        _append_ownership(directory, delegation, phase="exited", generation=owned.get("generation"),
                          session_path=owned.get("session_path"), pid=owned.get("pid"),
                          pgid=owned.get("pgid"), start_id=owned.get("start_id"), reason="confirmed_absent")
    return True


def reconcile(directory: Path, *, inspect, signal, open_child) -> dict:
    """Serialize restart, prove every old group absent, then resume only settled sessions."""
    directory = Path(directory)
    with (directory / "reconcile.lock").open("a") as fence:
        fcntl.flock(fence, fcntl.LOCK_EX)
        generation = uuid.uuid4().hex
        with _launch_gate(directory):
            _set_run(directory, "recovering", generation)
            with run_control.control_lock(directory):
                pending = []
                for delegation in _delegations(directory):
                    snapshot = _activation_view(directory, delegation)
                    if snapshot["state"] == "queued":
                        _openers[delegation["activation_id"]] = open_child
                    if not snapshot["occupies_slot"]:
                        continue
                    original = snapshot.get("recovery_state") if snapshot["state"] == "recovering" else snapshot["state"]
                    original = original or "active"
                    _append_state(directory, delegation, "recovering", occupies_slot=True,
                                  recovery_state=original, reason="recovery_required")
                    pending.append((delegation, original))
        blocked = False
        for delegation, original in pending:
            try:
                absent = _reconcile_owned(directory, delegation, inspect, signal)
            except Exception:
                absent = False
            with run_control.control_lock(directory):
                if not absent:
                    blocked = True
                    continue
                current = _activation_view(directory, delegation)["state"]
                stopped = any(row.get("kind") == "run_stop" for row in run_control._control_rows(directory))
                state = "cancelled" if stopped or original == "cancelling" or current == "cancelling" else original
                if state in _terminal_states:
                    _append_state(directory, delegation, state, occupies_slot=False, reason="confirmed_absent")
                else:
                    _append_state(directory, delegation, "recovering", occupies_slot=True,
                                  recovery_state=original, reason="child_absent")
        open_sessions = set()
        for delegation, _original in pending:
            if _live_ownership(_ownership_rows(directory, delegation["activation_id"])) is None:
                continue
            session_id = delegation.get("worker_session_id")
            if session_id:
                open_sessions.add(session_id)
        journals, sessions = _retained_evidence(directory)
        receipts = recover_receipts(directory, journals=journals, sessions=sessions, open_sessions=open_sessions)
        with run_control.control_lock(directory):
            held = (blocked or _request_uncertain(directory) or bool(receipts.get("usage_recovery_issues"))
                    or bool(receipts.get("proof_recovery_issues")))
        replacements = 0
        if not held:
            # The new generation may dispatch only after all old owners and request journals reconcile.
            _set_run(directory, "running")
            for delegation, original in pending:
                with run_control.control_lock(directory):
                    snapshot = _activation_view(directory, delegation)
                    if snapshot["state"] != "recovering":
                        continue
                    _append_state(directory, delegation, "launching", occupies_slot=True,
                                  recovery_state=original, reason="child_absent")
                    command_id = uuid.uuid4().hex
                _stop_sent.discard(delegation["activation_id"])
                _open_activation(directory, delegation, open_child, command_id, expected_generation=generation)
                if _live_ownership(_ownership_rows(directory, delegation["activation_id"])) is not None:
                    replacements += 1
            _fill_slots(directory)
        return {"ok": True, "status": "recovering" if held else "running",
                "generation": _control_generation(directory), "replacements": replacements, "blocked": bool(held),
                "receipts": receipts}


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


def _io_lock(activation_id: str):
    with _readers_guard:
        return _io_locks.setdefault(activation_id, threading.RLock())


@contextmanager
def _launch_gate(directory: Path):
    key = str(directory.resolve())
    held = getattr(_launch_gates, "held", None)
    if held is None:
        held = _launch_gates.held = set()
    if key in held:
        yield
        return
    with (directory / "activation-gate.lock").open("a") as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)


def observe_exit(directory: Path, activation_id: str, *, expected_transport=None, expected_generation=None) -> bool:
    """Observe injected process liveness; stdout EOF alone never releases a slot."""
    transport = _owned.get(activation_id)
    absent = getattr(transport, "confirmed_absent", None)
    if absent is None or not absent():
        return False
    with run_control.control_lock(directory):
        if _recovering(directory) or _owned.get(activation_id) is not transport:
            return False
        if expected_transport is not None and transport is not expected_transport:
            return False
        if expected_generation is not None and expected_generation != _control_generation(directory):
            return False
        ownership = _live_ownership(_ownership_rows(directory, activation_id))
        if ownership is None or ownership.get("generation") != _control_generation(directory):
            return False
        delegation = next((row for row in _delegations(directory) if row["activation_id"] == activation_id), None)
        if delegation is None:
            return False
        snapshot = _activation_view(directory, delegation)
        if not snapshot["occupies_slot"]:
            return True
        state = snapshot["state"]
        if state == "cancelling":
            state = "cancelled"
        elif state not in _terminal_states:
            state = "failed"
        _append_state(directory, delegation, state, occupies_slot=False, reason="confirmed_absent")
        if activation_id in _live:
            _live[activation_id]["state"] = state
    _fill_slots(directory)
    return True


def _stop_activation(directory: Path, delegation: dict, *, expected_transport=None, expected_generation=None) -> None:
    activation_id = delegation["activation_id"]
    with _io_lock(activation_id):
        transport = _owned.get(activation_id)
        if transport is None:
            return
        if expected_transport is not None and transport is not expected_transport:
            return
        if expected_generation is not None and expected_generation != _control_generation(directory):
            return
        if activation_id not in _stop_sent:
            try:
                snapshot = _activation_view(directory, delegation)
                if snapshot["state"] == "cancelling":
                    _write_prompt(transport, cancel_lines(snapshot["command_id"] or activation_id))
                shutdown = getattr(transport, "shutdown", None)
                if shutdown is not None:
                    shutdown()
                    _stop_sent.add(activation_id)
            except Exception as error:
                # An uncertain stop retains ownership and can be retried.
                with run_control.control_lock(directory):
                    snapshot = _activation_view(directory, delegation)
                    _append_state(directory, delegation, snapshot["state"], stop_error=type(error).__name__)
                return
        observe_exit(directory, activation_id)


def _open_activation(directory: Path, stored: dict, open_child, command_id: str,
                     *, expected_generation: str | None = None) -> None:
    activation_id = stored["activation_id"]
    transport = None
    spawn_attempted = False
    with _launch_gate(directory), _io_lock(activation_id):
        try:
            with run_control.control_lock(directory):
                if _recovering(directory):
                    return
                generation = _control_generation(directory)
                if expected_generation is not None and generation != expected_generation:
                    return
                if generation is None:
                    generation = uuid.uuid4().hex
                    run_control._append_control(directory, {
                        "schema_version": run_control.SCHEMA_VERSION, "kind": "run_generation",
                        "event_id": uuid.uuid4().hex, "generation": generation, "status": "running",
                    })
                state = _activation_view(directory, stored)["state"]
                if any(row.get("kind") == "run_stop" for row in run_control._control_rows(directory)):
                    if _live_ownership(_ownership_rows(directory, activation_id)) is None:
                        _append_state(directory, stored, "cancelled", occupies_slot=False, reason="run_stopped")
                    return
                if state == "cancelling":
                    _append_state(directory, stored, "cancelled", occupies_slot=False, reason="not_spawned")
                elif state != "launching":
                    return
            if state == "cancelling":
                _fill_slots(directory)
                return
            launch = worker_launch(
                directory, run_id=stored["run_id"], worker_actor_id=stored["worker_actor_id"],
                worker_session_id=stored["worker_session_id"], job_id=stored["job_id"],
                activation_id=activation_id, anchor=stored["anchor"], generation=generation,
            )
            with run_control.control_lock(directory):
                _append_ownership(directory, stored, phase="intent", generation=generation,
                                  session_path=launch["session_dir"])
            spawn_attempted = True
            try:
                transport = open_child(launch)
            except BaseException as error:
                if getattr(error, "not_spawned", False):
                    with run_control.control_lock(directory):
                        _append_ownership(directory, stored, phase="not_spawned", generation=generation,
                                          session_path=launch["session_dir"])
                raise
            _owned[activation_id] = transport
            identity = getattr(transport, "process_identity", None)
            described = identity() if identity is not None else None
            if (
                isinstance(described, dict) and type(described.get("pid")) is int and described["pid"] > 0
                and described.get("start_id") and type(described.get("pgid", described["pid"])) is int
                and described.get("pgid", described["pid"]) > 0
                and described.get("run_id", stored["run_id"]) == stored["run_id"]
                and described.get("generation", generation) == generation
            ):
                with run_control.control_lock(directory):
                    _append_ownership(
                        directory, stored, phase="spawned", generation=generation,
                        session_path=launch["session_dir"], pid=described["pid"],
                        pgid=described.get("pgid", described["pid"]), start_id=described["start_id"],
                    )
            else:
                raise RuntimeError("worker process identity unavailable")
            transport.subscribe()
            ready = threading.Event()
            thread = threading.Thread(
                target=_read_child, args=(directory, stored, command_id, transport, ready, generation), daemon=True,
            )
            with _readers_guard:
                _readers[activation_id] = thread
            thread.start()
            if not ready.wait(5):
                raise RuntimeError("reader did not start")
            if (_activation_view(directory, stored)["state"] == "launching"
                    and not _recovering(directory) and _control_generation(directory) == generation):
                _write_prompt(transport, prompt_line(command_id, stored["task"], stored["anchor"]))
            if _activation_view(directory, stored)["state"] == "cancelling":
                _stop_activation(directory, stored)
        except Exception as error:
            not_spawned = not spawn_attempted or bool(getattr(error, "not_spawned", False))
            with run_control.control_lock(directory):
                state = _activation_view(directory, stored)["state"]
                if state not in _terminal_states and state != "cancelling":
                    state = "failed"
                if not_spawned and state == "cancelling":
                    state = "cancelled"
                _append_state(directory, stored, state, command_id=command_id,
                              reason=type(error).__name__, occupies_slot=not not_spawned)
            if not_spawned:
                _fill_slots(directory)
            elif transport is not None:
                _stop_activation(directory, stored)


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
            if existing is None and _recovering(directory):
                return _reject(operation_id, "recovering", "recovery_required")
            if existing is None and (current["state"] in _active_states | {"cancelling"} or current["occupies_slot"]):
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
                "state": "launching" if _can_admit_directly(directory) else "queued",
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
            if applied.get("ok") and applied.get("status") == "committed" and existing is None:
                _openers[activation_id] = open_child
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
    if stored["state"] == "queued":
        _fill_slots(directory)
        return _receipt_body(directory, stored, applied, spend)
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
        "state": "queued",
        "resumed": False,
    }

    def mutate(writer) -> list:
        writer.append_ledger({"type": "delegation", **delegation})
        return []

    try:
        with run_control.control_lock(directory):
            if run_control._receipt(run_control._control_rows(directory), operation_id) is None and _recovering(directory):
                return _reject(operation_id, "recovering", "recovery_required")
            if _can_admit_directly(directory):
                delegation["state"] = "launching"
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
            if applied.get("ok") and applied.get("status") == "committed":
                accepted = next((row for row in _delegations(directory)
                                 if row.get("operation_id") == operation_id), None)
                if accepted is not None and accepted["activation_id"] == activation_id:
                    _openers[activation_id] = open_child
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
    # The receipt is already durable. A queued job waits until a slot is actually free.
    if stored["state"] == "queued":
        _fill_slots(directory)
        return _receipt_body(directory, stored, applied, spend)
    command_id = uuid.uuid4().hex
    _record_state(directory, stored, "launching", command_id=command_id)
    _open_activation(directory, stored, open_child, command_id)
    return _receipt_body(directory, stored, applied, spend)


def cancel(
    directory: Path,
    *,
    operation_id: str,
    run_id: str,
    actor_id: str,
    session_id: str,
    job_id: str,
) -> dict:
    """Commit cancellation of one exact activation before touching its transport."""
    if not operation_id or not run_id or not actor_id or not session_id or not job_id:
        return _reject(operation_id, "identity")
    arguments = {"job_id": job_id, "run_id": run_id, "actor_id": actor_id, "session_id": session_id}
    try:
        with run_control.control_lock(directory):
            current = _job_snapshot(directory, job_id)
            if current is None:
                return _reject(operation_id, "job", "not_found")
            source = _job_rows(directory, job_id)[0]
            if run_id != source["run_id"] or actor_id != source["actor_id"]:
                return _reject(operation_id, "ownership")
            previous = next((row for row in _states(directory)
                             if row.get("operation_id") == operation_id and row.get("cancel_operation_id")), None)
            activation_id = previous["activation_id"] if previous is not None else current["activation_id"]
            stored = next(row for row in _delegations(directory) if row["activation_id"] == activation_id)
            snapshot = _activation_view(directory, stored)
            prior = next((row["cancel_operation_id"] for row in _states(directory)
                          if row.get("activation_id") == activation_id and row.get("cancel_operation_id")), None)
            canonical_id = prior or operation_id
            state = snapshot["state"]
            if state == "queued":
                state = "cancelled"
            elif state in ("launching", "active", "recovering"):
                state = "cancelling"

            def mutate(writer) -> list:
                writer.append_ledger({
                    "type": "assignment_state", "state": state,
                    "command_id": snapshot["command_id"], "cancel_operation_id": canonical_id,
                    "occupies_slot": snapshot["occupies_slot"],
                })
                return []

            applied = run_control._apply_locked(directory, {
                "operation_id": operation_id, "kind": "cancel", "arguments": arguments,
                "run_id": run_id, "actor_id": actor_id, "session_id": session_id,
                "job_id": job_id, "activation_id": activation_id,
            }, mutate)
            if not applied.get("ok"):
                return applied
            if applied.get("status") == "aborted":
                return {**applied, "ok": False, "category": "operation_aborted"}
            if activation_id in _live:
                _live[activation_id]["state"] = _activation_view(directory, stored)["state"]
            canonical_receipt = run_control._receipt(run_control._control_rows(directory), canonical_id)
            evidence_refs = (canonical_receipt or {}).get("evidence_refs") or []
    except OperationRejected as error:
        return _reject(operation_id, error.category)
    _stop_activation(directory, stored)
    spend = run_control.read_state(directory)
    snapshot = _activation_view(directory, stored)
    return {
        "ok": True, "operation_id": canonical_id, "job_id": job_id,
        "activation_id": activation_id, "state": snapshot["state"],
        "reused": previous is not None or prior is not None,
        "evidence_refs": evidence_refs,
        "accounting": spend["accounting"], "total": spend["total"],
    }


def _delivery_rows(directory: Path, actor_id: str) -> list[dict]:
    return [
        row for row in _history(directory)
        if row.get("kind") == "delivered_reply" and row.get("actor_id") == actor_id
        and ((row.get("data") or {}).get("channel") == "worker_inbox"
             or "acked" in (row.get("data") or {}))
    ]


def _acked(directory: Path, actor_id: str, cursor: str | None) -> set[str] | None:
    rows = _delivery_rows(directory, actor_id)
    if cursor is None:
        return {identity for row in rows for identity in (row.get("data") or {}).get("acked", [])}
    match = next((row for row in rows if row.get("event_id") == cursor), None)
    if match is None:
        return None
    return set((match.get("data") or {}).get("acked") or [])


def _wait_rows(directory: Path) -> list[dict]:
    rows = list(_history(directory))
    rows.extend(
        row for row in run_control._control_rows(directory)
        if row.get("kind") == "run_stop" and row.get("event_id")
    )
    return rows


def _selectable(row: dict, job_ids: list[str] | None) -> bool:
    kind = row.get("type") or row.get("kind")
    if kind == "run_stop":
        return True
    if job_ids is not None and row.get("job_id") not in job_ids:
        return False
    if kind == "worker_finding":
        return True
    if kind == "verification" and row.get("state") in _terminal_checks:
        return True
    return kind == "assignment_state" and row.get("state") in _terminal_states


def _open_checks(directory: Path, job_ids: list[str] | None) -> bool:
    latest: dict[tuple[str, str], str] = {}
    for row in _history(directory):
        if (row.get("type") or row.get("kind")) != "verification":
            continue
        job_id = row.get("job_id")
        evaluation_id = row.get("evaluation_id")
        if not job_id or not evaluation_id or (job_ids is not None and job_id not in job_ids):
            continue
        execution = row.get("check_id") or f"legacy:{job_id}:{evaluation_id}"
        latest[(job_id, execution)] = row.get("state") or ""
    return any(state in {"queued", "running"} for state in latest.values())


def _reader_can_emit(activation_id: str) -> bool:
    transport = _owned.get(activation_id)
    reader = _readers.get(activation_id)
    absent = getattr(transport, "confirmed_absent", None)
    return bool(transport is not None and reader is not None and reader.is_alive()
                and not (absent is not None and absent()))


def _has_producer(directory: Path, job_ids: list[str] | None) -> bool:
    if _open_checks(directory, job_ids):
        return True
    for snapshot in _selected_jobs(directory, job_ids):
        activation_id = snapshot["activation_id"]
        if snapshot["state"] not in _live_states:
            continue
        if _reader_can_emit(activation_id):
            return True
        # A launch already owned by delegate may still be opening its transport.
        if snapshot["state"] == "launching" and activation_id in _openers and activation_id not in _readers:
            return True
        # Queued work can progress only if a locally owned child can release its slot.
        if snapshot["state"] == "queued" and activation_id in _openers and any(
            _activation_view(directory, row)["occupies_slot"] and _reader_can_emit(row["activation_id"])
            for row in _delegations(directory)
        ):
            return True
    return False


def _public_event(row: dict) -> dict:
    event = {
        key: row[key]
        for key in (
            "event_id", "job_id", "activation_id", "state", "attempt_id", "proof_id",
            "evaluation_id", "request_id", "run_id", "actor_id", "session_id",
            "operation_id", "reason", "outcome", "check_id", "attempt_ids", "recovery_of",
        )
        if row.get(key) is not None
    }
    event["type"] = row.get("type") or row.get("kind")
    return event


def _wake_reason(events: list[dict]) -> str:
    if any(event["type"] == "run_stop" for event in events):
        return "run_stopped"
    if any(event["type"] in ("worker_finding", "verification") for event in events):
        return "result"
    last = events[-1]
    if last.get("state") == "cancelled":
        return "cancelled"
    if last.get("state") == "failed":
        return "failed"
    return "settled"


def _selected_jobs(directory: Path, job_ids: list[str] | None) -> list[dict]:
    found = []
    seen: set[str] = set()
    for row in _delegations(directory):
        job_id = row.get("job_id")
        if not job_id or job_id in seen or (job_ids is not None and job_id not in job_ids):
            continue
        seen.add(job_id)
        snapshot = _job_snapshot(directory, job_id)
        if snapshot is not None:
            found.append(snapshot)
    return found


def _spend(directory: Path) -> dict:
    return run_control._spend_view(directory, run_control._control_rows(directory))


def _commit_delivery(
    directory: Path, actor_id: str, fresh: list[dict], acked: set[str], *,
    wake_reason: str | None = None, job_ids: list[str] | None = None, reason: str | None = None,
) -> dict:
    identities = [row["event_id"] for row in fresh]
    merged = sorted((_acked(directory, actor_id, None) or set()) | acked | set(identities))
    selected = _selected_jobs(directory, job_ids)
    wake_reason = wake_reason or _wake_reason([_public_event(row) for row in fresh])
    arguments = {"channel": "worker_inbox", "actor_id": actor_id, "event_ids": identities,
                 "acked": merged, "job_ids": sorted(job_ids) if job_ids is not None else None,
                 "wake_reason": wake_reason, "reason": reason,
                 "assignments": [[job["activation_id"], job["state"]] for job in selected]}
    operation_id = run_control.argument_digest(arguments)[:32]
    source = fresh[0] if fresh else next(iter(_delegations(directory)), {})

    def mutate(ctx):
        return [ctx.append_ledger({
            "kind": "delivered_reply",
            "data": {"channel": "worker_inbox", "event_ids": identities, "acked": merged,
                     "wake_reason": wake_reason, "reason": reason},
        })]

    applied = run_control._apply_locked(
        directory,
        {
            "operation_id": operation_id,
            "kind": "delivered_reply",
            "arguments": arguments,
            "run_id": source.get("run_id") or "run",
            "actor_id": actor_id,
            "session_id": f"{actor_id}-delivery",
        },
        mutate,
    )
    if not applied.get("ok"):
        return applied
    token = applied["evidence_refs"][-1]["event_id"]
    spend = _spend(directory)
    return {
        "ok": True,
        "operation_id": operation_id,
        "wake_reason": wake_reason,
        **({"reason": reason} if reason else {}),
        "events": [_public_event(row) for row in fresh],
        "jobs": selected,
        "evidence_refs": applied.get("evidence_refs") or [],
        "next_cursor": token,
        "accounting": spend["accounting"],
        "total": spend["total"],
    }


def note_verification(
    directory: Path,
    *,
    job_id: str,
    evaluation_id: str,
    state: str,
    run_id: str,
    actor_id: str,
    session_id: str,
    check_id: str | None = None,
    proof_id: str | None = None,
    attempt_ids: list[str] | None = None,
    recovery_of: str | None = None,
) -> dict:
    """Publish one execution's lifecycle, separately from its reusable evaluation key."""
    if state not in {"queued", "running", *_terminal_checks}:
        return _reject("", "verification_state")
    if not job_id or not evaluation_id or not run_id or not actor_id or not session_id:
        return _reject("", "identity")
    check_id = check_id or f"legacy:{job_id}:{evaluation_id}"
    arguments = {"job_id": job_id, "evaluation_id": evaluation_id, "check_id": check_id,
                 "state": state, "proof_id": proof_id, "attempt_ids": sorted(attempt_ids or [])}
    if recovery_of:
        arguments["recovery_of"] = recovery_of
    operation_id = run_control.argument_digest(arguments)[:32]

    def mutate(ctx):
        return [ctx.append_ledger({"type": "verification", **arguments})]

    applied = run_control.apply_operation(
        directory,
        {"operation_id": operation_id, "kind": "verification", "arguments": arguments,
         "run_id": run_id, "actor_id": actor_id, "session_id": session_id, "job_id": job_id},
        mutate,
    )
    _wake()
    return applied


def wake_waiters() -> None:
    """Wake waiters after their cancellation events have been set."""
    _wake()


def await_results(
    directory: Path,
    *,
    actor_id: str,
    cursor: str | None = None,
    job_ids: list[str] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Return retained evidence or no_pending_work. Waiting performs no provider request.

    A wait that actually blocks is durable: a `wait` row when it starts and a `wait_end` row with the same
    wait id and the wake reason when it ends, so an intentionally waiting orchestrator is visible. An
    immediate return writes nothing.
    """
    waiting: dict[str, str] = {}

    def blocked() -> None:
        if waiting:
            return
        waiting["id"] = uuid.uuid4().hex
        _append(directory, {"event_id": uuid.uuid4().hex, "kind": "wait", "wait_id": waiting["id"],
                            "actor_id": actor_id, "job_ids": sorted(job_ids) if job_ids is not None else None,
                            "cursor": cursor})

    result: dict = {}
    try:
        result = _await_results(directory, actor_id, cursor, job_ids, cancel_event, blocked)
        return result
    finally:
        if waiting:
            _append(directory, {"event_id": uuid.uuid4().hex, "kind": "wait_end", "wait_id": waiting["id"],
                                "actor_id": actor_id,
                                "wake_reason": result.get("wake_reason") or result.get("reason") or "interrupted"})


def _await_results(directory, actor_id, cursor, job_ids, cancel_event, blocked) -> dict:
    if not actor_id:
        return _reject("", "identity")
    if job_ids is not None and (
        not isinstance(job_ids, list) or not all(isinstance(item, str) and item for item in job_ids)
    ):
        return _reject("", "job_ids")
    with run_control.watch_directory(directory) as watch:
        while True:
            with run_control.control_lock(directory):
                if cancel_event is not None and cancel_event.is_set():
                    return {**_reject("", "wait_cancelled", "cancelled"), "retryable": True}
                acked = _acked(directory, actor_id, cursor)
                if acked is None:
                    return _reject("", "cursor")
                fresh = [
                    row for row in _wait_rows(directory)
                    if row.get("event_id") and row["event_id"] not in acked and _selectable(row, job_ids)
                ]
                if fresh:
                    return _commit_delivery(directory, actor_id, fresh, acked, job_ids=job_ids,
                                            wake_reason="run_stopped" if _spend(directory)["stopped"] else None)
                if _spend(directory)["stopped"]:
                    return _commit_delivery(directory, actor_id, [], acked,
                                            wake_reason="run_stopped", job_ids=job_ids)
                if not _has_producer(directory, job_ids):
                    stale = any(job["state"] in _live_states for job in _selected_jobs(directory, job_ids))
                    return _commit_delivery(directory, actor_id, [], acked, wake_reason="no_pending_work",
                                            job_ids=job_ids, reason="recovery_required" if stale else None)
                with _interest:
                    if not watch.available:
                        return {**_reject("", "notification_unavailable", "notification_unavailable"),
                                "retryable": True}
                    if cancel_event is not None and cancel_event.is_set():
                        return {**_reject("", "wait_cancelled", "cancelled"), "retryable": True}
                    seen = _epoch
            blocked()
            with _interest:
                if _epoch != seen:
                    continue
                _interest.wait()


def _journal_charges(journals: list[dict], sessions: list[dict]) -> list[dict]:
    from arena.recovery_usage import journal_charges
    return journal_charges(journals, sessions)


def _jsonl_rows(path: Path) -> list[dict]:
    from arena.recovery_usage import jsonl_rows
    return jsonl_rows(path)


def _retained_evidence(directory: Path) -> tuple[list[dict], list[dict]]:
    from arena.recovery_usage import retained_evidence
    return retained_evidence(directory)


def recover_receipts(
    directory: Path,
    *,
    journals: list[dict],
    sessions: list[dict],
    open_sessions: set[str] | None = None,
) -> dict:
    """Rebuild spend, evaluation, and delivery from committed receipts and retained evidence.

    A journal or session response settles its covered requests once. An uncertain call with
    no actual usage stays unknown. Definitely-unsent requests are left for an explicit new
    preparation. This does not send a provider request or change the stop or deadline origin.
    """
    directory = Path(directory)
    from arena.recovery_usage import reconcile_usage

    usage_recovery = reconcile_usage(directory, journals, sessions, open_sessions)
    usage_recovery_issues = usage_recovery["issues"]
    from arena.recovery_proofs import recover as recover_proofs

    recovered_proofs = recover_proofs(directory, _history(directory), open_sessions=open_sessions or set())
    view = run_control.read_state(directory)
    rows = run_control._control_rows(directory)
    origin = next((row.get("origin") for row in rows if row.get("kind") == "track_deadline" and row.get("origin")), None)
    unsent = sorted(request_id for request_id in run_control._prepared(rows)
                    if run_control._definitely_unsent(rows, request_id))
    return {
        "ok": True,
        "total": view["total"],
        "accounting": view["accounting"],
        "unknown_requests": view["unknown_requests"],
        "accounting_failures": view["accounting_failures"],
        "stop_reason": view["stop_reason"],
        "deadline_origin": origin,
        **recovered_proofs,
        "usage_recovery_issues": usage_recovery_issues,
        "unsent": unsent,
        "resent": False,
    }


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


run_control.listen_for_wait(_wake)
