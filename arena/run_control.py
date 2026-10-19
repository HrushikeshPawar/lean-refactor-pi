"""Run-scoped operation receipts.

Receipts live in ``control.jsonl``. Proof events stay in the campaign ledger.
A repeated operation id with the same argument digest returns its receipt.
The same id with different arguments is ``operation_conflict`` and writes nothing.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_MISSING = ("actor_id", "session_id", "tool_call_id", "operation_id")


class OperationRejected(ValueError):
    """The operation cannot be applied."""

    def __init__(self, category: str, operation_id: str):
        super().__init__(category)
        self.category = category
        self.operation_id = operation_id


def argument_digest(arguments: object) -> str:
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


@contextmanager
def control_lock(directory: Path):
    """The first lock in the v8 order: control, then graph filing, then the ledger append."""
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "control.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _control_rows(directory: Path) -> list[dict]:
    path = directory / "control.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_bytes().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_control(directory: Path, event: dict) -> dict:
    path = directory / "control.jsonl"
    data = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        start = os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return {
        "byte_start": start,
        "byte_end": start + len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "record": "control.jsonl",
    }


def _abort_open_intents(directory: Path, rows: list[dict]) -> list[dict]:
    """An intent with no later receipt is aborted. The intent line stays in place."""
    open_ids = []
    receipt_ids = set()
    for row in rows:
        kind = row.get("kind")
        if kind == "operation_intent":
            open_ids.append(row.get("operation_id"))
        elif kind == "operation_receipt":
            receipt_ids.add(row.get("operation_id"))
    for operation_id in open_ids:
        if operation_id in receipt_ids or not operation_id:
            continue
        _append_control(
            directory,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "operation_receipt",
                "operation_id": operation_id,
                "status": "aborted",
                "event_seq": [],
                "evidence_refs": [],
            },
        )
        receipt_ids.add(operation_id)
    return _control_rows(directory)


def _receipt(rows: list[dict], operation_id: str) -> dict | None:
    found = None
    for row in rows:
        if row.get("kind") == "operation_receipt" and row.get("operation_id") == operation_id:
            found = row
    return found


class LedgerWriter:
    """Append ledger events while the caller already holds the control lock."""

    def __init__(self, directory: Path, operation: dict, seq: int):
        self.directory = directory
        self.operation = operation
        self.seq = seq
        self.evidence: list[dict] = []

    def append_ledger(self, event: dict) -> dict:
        from arena.campaign import _append

        self.seq += 1
        event_id = uuid.uuid4().hex
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "event_seq": self.seq,
            "operation_id": self.operation["operation_id"],
            "run_id": self.operation["run_id"],
            "actor_id": self.operation["actor_id"],
            "session_id": self.operation["session_id"],
        }
        for key in ("job_id", "activation_id"):
            if self.operation.get(key):
                envelope[key] = self.operation[key]
        envelope.update(event)
        ref = _append(self.directory, envelope)
        ref = {**ref, "event_id": event_id, "event_seq": self.seq, "record": "ledger.jsonl"}
        self.evidence.append(ref)
        return ref


def apply_operation(directory: Path, operation: dict, mutate: Callable[[LedgerWriter], list]) -> dict:
    """Commit one operation, or return the receipt already stored for this id and digest."""
    with control_lock(directory):
        return _apply_locked(directory, operation, mutate)


def _apply_locked(directory: Path, operation: dict, mutate: Callable[[LedgerWriter], list]) -> dict:
    required = ("operation_id", "kind", "arguments", "run_id", "actor_id", "session_id")
    missing = [key for key in required if not operation.get(key)]
    if missing:
        raise OperationRejected("invalid_input", str(operation.get("operation_id") or ""))
    rows = _abort_open_intents(directory, _control_rows(directory))
    digest = argument_digest(operation["arguments"])
    existing = _receipt(rows, operation["operation_id"])
    if existing is not None:
        if existing.get("argument_digest") != digest:
            return {
                "ok": False,
                "status": "operation_conflict",
                "category": "operation_conflict",
                "operation_id": operation["operation_id"],
            }
        return {
            "ok": True,
            "status": existing.get("status", "committed"),
            "operation_id": operation["operation_id"],
            "event_seq": existing.get("event_seq") or [],
            "evidence_refs": existing.get("evidence_refs") or [],
        }
    seq = max((int(row.get("event_seq_end") or 0) for row in rows), default=0)
    intent = {
        "schema_version": SCHEMA_VERSION,
        "kind": "operation_intent",
        "event_id": uuid.uuid4().hex,
        "operation_id": operation["operation_id"],
        "run_id": operation["run_id"],
        "actor_id": operation["actor_id"],
        "session_id": operation["session_id"],
        "operation_kind": operation["kind"],
        "argument_digest": digest,
    }
    for key in ("job_id", "activation_id"):
        if operation.get(key):
            intent[key] = operation[key]
    _append_control(directory, intent)
    writer = LedgerWriter(directory, operation, seq)
    try:
        mutate(writer)
    except Exception:
        _append_control(
            directory,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "operation_receipt",
                "operation_id": operation["operation_id"],
                "argument_digest": digest,
                "status": "aborted",
                "event_seq": [],
                "event_seq_end": seq,
                "evidence_refs": writer.evidence,
            },
        )
        raise
    end = writer.seq
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "operation_receipt",
        "event_id": uuid.uuid4().hex,
        "operation_id": operation["operation_id"],
        "run_id": operation["run_id"],
        "actor_id": operation["actor_id"],
        "session_id": operation["session_id"],
        "argument_digest": digest,
        "status": "committed",
        "event_seq": list(range(seq + 1, end + 1)),
        "event_seq_end": end,
        "evidence_refs": writer.evidence,
    }
    _append_control(directory, receipt)
    return {
        "ok": True,
        "status": "committed",
        "operation_id": operation["operation_id"],
        "event_seq": receipt["event_seq"],
        "evidence_refs": writer.evidence,
    }


def committed_operation_ids(directory: Path) -> set[str]:
    return {
        row["operation_id"]
        for row in _control_rows(directory)
        if row.get("kind") == "operation_receipt" and row.get("status") == "committed" and row.get("operation_id")
    }


def published_history(directory: Path, history: list[dict]) -> list[dict]:
    """Publish legacy rows and v8 rows backed by a committed receipt."""
    return committed_history(history, committed_operation_ids(directory))


def committed_history(history: list[dict], committed_operations: set[str] | frozenset[str]) -> list[dict]:
    return [
        event for event in history if not event.get("operation_id") or event["operation_id"] in committed_operations
    ]


def actor_ids(run_id: str) -> dict:
    """Actor and session for a harness-generated operation. Absent call fields stay missing."""
    from arena.traces import call_context

    context = call_context()
    actor = os.environ.get("ARENA_ACTOR_ID") or "local"
    session = os.environ.get("ARENA_SESSION_ID") or run_id
    found = {"actor_id": actor, "session_id": session, "missing": []}
    if context.get("tool_call_id"):
        found["tool_call_id"] = context["tool_call_id"]
    else:
        found["missing"] = ["tool_call_id"]
    return found


def construction_digest(payload: dict) -> str:
    return argument_digest(payload)


def input_roles(operation: dict | None) -> list[dict]:
    operation = operation or {}
    kind = operation.get("type")
    sources = list(operation.get("from") or [])
    if kind == "merged_from":
        roles = [{"role": "base", "proof_id": sources[0]}] if sources else []
        roles.extend({"role": "donor", "proof_id": source} for source in sources[1:])
        takes = operation.get("take") or []
        for index, take in enumerate(takes):
            if index + 1 < len(roles) and isinstance(take, dict):
                roles[index + 1]["step"] = take.get("step")
        return roles
    if kind == "filled_from" and sources:
        return [{"role": "sketch", "proof_id": sources[0], "hole": operation.get("hole")}]
    if kind == "edited_from" and sources:
        return [{"role": "base", "proof_id": sources[0]}]
    if kind == "filed_under_focus" and sources:
        return [{"role": "focus", "proof_id": sources[0]}]
    if kind == "root":
        return []
    return [{"role": "input", "proof_id": source} for source in sources]
