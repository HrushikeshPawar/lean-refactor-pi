"""Durable scratch experiments: exact input, then a retrievable outcome.

A local outcome is not target validity, compatibility, or cold status. Promotion is recorded
on the outcome when an anchored replacement files a candidate.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from arena import campaign
from arena.run_control import OperationRejected, actor_ids, apply_operation, published_history
from arena.traces import call_context


def _call_operation_id(identity: dict) -> str | None:
    call = identity.get("tool_call_id")
    if not call:
        return None
    key = ":".join(str(identity.get(k) or "") for k in ("actor_id", "session_id", "activation_id"))
    return f"scratch:{key}:{call}"


def replay_request(run_id: str, request: dict) -> dict | None:
    """Resolve a repeated invocation before mutable focus can change its anchor."""
    operation_id = _call_operation_id({**actor_ids(run_id), **call_context()})
    if operation_id is None:
        return None
    accepted = next((row for row in _scratch(campaign.run_dir(run_id))
                     if row.get("phase") == "accepted" and row.get("operation_id") == operation_id), None)
    if accepted is None or "request" not in accepted:
        return None
    if accepted["request"] != request:
        raise OperationRejected("operation_conflict", operation_id)
    return retrieve(run_id, accepted["experiment_id"])


def accept(
    run_id: str,
    code: str,
    helpers: list[str],
    *,
    context: dict | None = None,
    operation_id: str | None = None,
    request: dict | None = None,
) -> dict:
    """Commit the exact snippet before construction, replaying the same tool call once."""
    directory = campaign.run_dir(run_id)
    digest = hashlib.sha256(code.encode()).hexdigest()
    identity = {**actor_ids(run_id), **call_context()}
    if operation_id is None:
        operation_id = _call_operation_id(identity) or f"scratch:{uuid.uuid4().hex}"
    experiment_id = "e-" + hashlib.sha256(operation_id.encode()).hexdigest()
    init = next((row for row in campaign.events(directory) if row.get("kind") == "init"), None)
    submitted_context = {"theorem_run": run_id, **({"run_init": init} if init else {}), **(context or {})}
    arguments = {"code": code, "helpers": list(helpers), "identity": identity, "context": context or {}}
    if request is not None:
        arguments["request"] = request
    operation = {
        **identity,
        "operation_id": operation_id,
        "kind": "scratch_input",
        "arguments": arguments,
        "run_id": run_id,
    }
    created = []

    def store(writer):
        created.append(True)
        writer.append_ledger(
            {
                **identity,
                "kind": "scratch",
                "phase": "accepted",
                "state": "accepted",
                "experiment_id": experiment_id,
                "code_sha256": digest,
                "code": code,
                "helpers": list(helpers),
                **({"request": request} if request is not None else {}),
                "context": submitted_context,
            }
        )

    receipt = apply_operation(directory, operation, store)
    if not receipt.get("ok") or receipt.get("status") != "committed":
        raise OperationRejected(receipt.get("category") or receipt["status"], operation_id)
    found = retrieve(run_id, experiment_id)
    return {
        "experiment_id": experiment_id,
        "code_sha256": digest,
        "input_ref": receipt["evidence_refs"][0],
        "receipt": receipt,
        "outcome": found["outcome"],
        "replayed": not created,
    }


def finish(
    run_id: str,
    experiment_id: str,
    *,
    code: str,
    digest: str,
    outcome: str,
    raw: str | None,
    rendered: list[str],
    elapsed_ms: int,
    input_ref: dict | None = None,
    diagnostic: str | None = None,
    context: dict | None = None,
    promotion: dict | None = None,
    validity: str = "not_a_target_candidate",
    compatibility: str = "not_checked",
    cold: str = "not_checked",
) -> None:
    """Commit one immutable outcome using the accepted input's ownership."""
    directory = campaign.run_dir(run_id)
    accepted = next(
        (
            row
            for row in _scratch(directory)
            if row.get("experiment_id") == experiment_id and row.get("phase") == "accepted"
        ),
        None,
    )
    operation_id = f"scratch_outcome:{experiment_id}"
    if accepted is None or accepted.get("code") != code or accepted.get("code_sha256") != digest:
        raise OperationRejected("operation_conflict", operation_id)
    authoritative_ref = _input_ref(accepted)
    if input_ref is not None and input_ref != authoritative_ref:
        raise OperationRejected("operation_conflict", operation_id)
    data = {
        "outcome": outcome,
        "raw": raw,
        "rendered": rendered,
        "diagnostic": diagnostic,
        "elapsed_ms": elapsed_ms,
        "input_ref": authoritative_ref,
        "context": context or {},
        "promotion": promotion if promotion is not None else {"state": "not_promoted", "reason": "not_requested"},
        "validity": validity,
        "compatibility": compatibility,
        "cold": cold,
    }
    identity = _identity(accepted)
    receipt = apply_operation(
        directory,
        {
            **identity,
            "operation_id": operation_id,
            "run_id": run_id,
            "kind": "scratch_outcome",
            "arguments": {"experiment_id": experiment_id, **data},
        },
        lambda writer: [
            writer.append_ledger(
                {
                    **identity,
                    "kind": "scratch",
                    "phase": "outcome",
                    "state": outcome,
                    "experiment_id": experiment_id,
                    "code_sha256": digest,
                    "code": code,
                    **data,
                }
            )
        ],
    )
    if not receipt.get("ok") or receipt.get("status") != "committed":
        raise OperationRejected(receipt.get("category") or receipt["status"], operation_id)


def record_raw(run_id: str, experiment_id: str, output: tuple[int, str] | None, context: dict) -> None:
    """Commit Lean's untouched result before diagnostic rendering can fail."""
    directory = campaign.run_dir(run_id)
    accepted = next(
        row
        for row in _scratch(directory)
        if row.get("experiment_id") == experiment_id and row.get("phase") == "accepted"
    )
    identity = _identity(accepted)
    operation_id = f"scratch_raw:{experiment_id}"
    data = {
        "experiment_id": experiment_id,
        "raw": output[1] if output else None,
        "returncode": output[0] if output else None,
        "context": context,
    }
    receipt = apply_operation(
        directory,
        {
            **identity,
            "operation_id": operation_id,
            "run_id": run_id,
            "kind": "scratch_raw",
            "arguments": data,
        },
        lambda writer: [writer.append_ledger({**identity, "kind": "scratch", "phase": "raw", **data})],
    )
    if not receipt.get("ok") or receipt.get("status") != "committed":
        raise OperationRejected(receipt.get("category") or receipt["status"], operation_id)


def _identity(accepted: dict) -> dict:
    return {
        key: accepted[key]
        for key in (
            "actor_id",
            "session_id",
            "job_id",
            "activation_id",
            "generation",
            "tool_call_id",
            "request_id",
            "turn",
        )
        if key in accepted
    }


def original_lines(directory: Path, match) -> list[dict]:
    """Exact ledger lines, with byte offsets, for records the caller selects."""
    path = directory / "ledger.jsonl"
    if not path.is_file():
        return []
    raw = path.read_bytes()
    found = []
    offset = 0
    for line in raw.splitlines(keepends=True):
        start = offset
        offset += len(line)
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and match(event):
            found.append(
                {
                    "kind": event.get("kind"),
                    "start": start,
                    "end": offset,
                    "sha256": hashlib.sha256(line).hexdigest(),
                    "line": line.decode(),
                }
            )
    return found


def retrieve(run_id: str, reference: str) -> dict | None:
    """Return one experiment, or an explicit missing-code record for a hash-only row."""
    rows = _scratch(campaign.run_dir(run_id))
    matched = [row for row in rows if row.get("experiment_id") == reference]
    if matched:
        found = _joined(matched)
        directory = campaign.run_dir(run_id)
        found["original_lines"] = original_lines(
            directory, lambda row: row.get("experiment_id") == reference
        )
        return found
    hashed = [row for row in rows if row.get("code_sha256") == reference and not row.get("experiment_id")]
    if not hashed:
        return None
    stored = [row["code"] for row in hashed if "code" in row]
    unique = set(stored)
    if len(unique) > 1:
        return {"experiment_id": reference, "code": None, "code_status": "ambiguous", "outcome": "unavailable"}
    if len(unique) == 1:
        code = stored[0]
        return {
            "experiment_id": reference,
            "code": code,
            "code_status": "retained",
            "outcome": "recorded",
            "code_sha256": reference,
            "validity": "not_a_target_candidate",
            "compatibility": "not_checked",
            "cold": "not_checked",
            "promotion": {"state": "not_promoted", "reason": "historical_record"},
            "raw": None,
            "rendered": [],
            "diagnostic": None,
        }
    return {
        "experiment_id": reference,
        "code": None,
        "code_status": "missing",
        "outcome": "unavailable",
        "diagnostic": "missing code",
    }


def unresolved_helpers(run_id: str, helpers: list[str]) -> list[str]:
    missing = []
    for reference in helpers:
        found = retrieve(run_id, reference)
        if found is None or found.get("code_status") != "retained":
            missing.append(reference)
    return missing


def _joined(rows: list[dict]) -> dict:
    accepted = next(row for row in rows if "code" in row)
    outcome = next((row for row in reversed(rows) if row.get("outcome")), None)
    result = {
        "experiment_id": accepted["experiment_id"],
        "code": accepted["code"],
        "code_status": "retained",
        "code_sha256": accepted.get("code_sha256"),
        "helpers": accepted.get("helpers") or [],
        "actor_id": accepted.get("actor_id"),
        "session_id": accepted.get("session_id"),
        "job_id": accepted.get("job_id"),
        "tool_call_id": accepted.get("tool_call_id"),
        "request_id": accepted.get("request_id"),
        "activation_id": accepted.get("activation_id"),
        "generation": accepted.get("generation"),
        "operation_id": accepted.get("operation_id"),
        "context": accepted.get("context"),
        "outcome": "accepted",
        "raw": None,
        "rendered": [],
        "diagnostic": None,
        "elapsed_ms": None,
        "input_ref": _input_ref(accepted),
        "promotion": {"state": "not_promoted", "reason": "outcome_pending"},
        "validity": "not_a_target_candidate",
        "compatibility": "not_checked",
        "cold": "not_checked",
    }
    raw = next((row for row in reversed(rows) if row.get("phase") == "raw"), None)
    if raw is not None:
        result.update(raw=raw.get("raw"), returncode=raw.get("returncode"))
        result["context"] = {**(accepted.get("context") or {}), **(raw.get("context") or {})}
    result["submitted_context"] = accepted.get("context")
    if outcome:
        for key in (
            "outcome",
            "raw",
            "rendered",
            "diagnostic",
            "elapsed_ms",
            "input_ref",
            "promotion",
            "validity",
            "compatibility",
            "cold",
        ):
            if key in outcome and not (key == "raw" and outcome[key] is None and raw is not None):
                result[key] = outcome[key]
        if outcome.get("context"):
            result["context"] = {**(result.get("context") or {}), **outcome["context"]}
            result["submitted_context"] = accepted.get("context")
    return result


def _input_ref(accepted: dict) -> dict | None:
    directory = campaign.run_dir(accepted.get("run_id") or accepted["context"]["theorem_run"])
    from arena.run_control import _control_rows

    # The authoritative receipt retains the exact original byte range and hash.
    for row in _control_rows(directory):
        if (
            row.get("kind") == "operation_receipt"
            and row.get("status") == "committed"
            and row.get("operation_id") == accepted.get("operation_id")
        ):
            return next(iter(row.get("evidence_refs") or []), None)
    return None


def _scratch(directory: Path) -> list[dict]:
    return [row for row in published_history(directory, campaign.events(directory)) if row.get("kind") == "scratch"]


def elapsed_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
