"""Run-scoped operation receipts.

Receipts live in ``control.jsonl``. Proof events stay in the campaign ledger.
A repeated operation id with the same argument digest returns its receipt.
The same id with different arguments is ``operation_conflict`` and writes nothing.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMA_VERSION = 1
ACTUAL_COST_THRESHOLD = Decimal("2.50")

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
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_control(directory: Path, event: dict) -> dict:
    path = directory / "control.jsonl"
    data = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        start = os.lseek(fd, 0, os.SEEK_END)
        separator = b"\n" if start and os.pread(fd, 1, start - 1) != b"\n" else b""
        pending = memoryview(separator + data)
        while pending:
            written = os.write(fd, pending)
            if written <= 0:
                raise OSError("control ledger write made no progress")
            pending = pending[written:]
        start += len(separator)
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
    actor = os.environ.get("ARENA_ACTOR_ID") or "sol"
    session = os.environ.get("ARENA_SESSION_ID") or run_id
    found = {"actor_id": actor, "session_id": session, "missing": []}
    if context.get("tool_call_id"):
        found["tool_call_id"] = context["tool_call_id"]
    else:
        found["missing"] = ["tool_call_id"]
    return found


def construction_digest(payload: dict) -> str:
    return argument_digest(payload)


def _usage_amount(usage: object) -> Decimal | None:
    """The provider total, when the usage object is complete. Incomplete usage is not zero."""
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost")
    if not isinstance(cost, dict) or "total" not in cost:
        return None
    total = cost.get("total")
    if isinstance(total, bool):
        return None
    if isinstance(total, float):
        if not math.isfinite(total) or total < 0:
            return None
        return Decimal(str(total))
    if isinstance(total, int):
        if total < 0:
            return None
        return Decimal(total)
    return _decimal_amount(total)


def _decimal_amount(amount: object) -> Decimal | None:
    """Accept a non-negative decimal string. Floats and invalid text are not money."""
    if not isinstance(amount, str):
        return None
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def _money(value: Decimal) -> str:
    return format(value, "f")


def prepare_request(directory: Path, request: dict) -> dict:
    """Record a provider request before dispatch. Repeating the same id is a no-op."""
    if _missing_request(request):
        raise OperationRejected("invalid_input", str(request.get("request_id") or ""))
    with control_lock(directory):
        _rows, result = _prepare_locked(directory, _control_rows(directory), request)
        return result


def _missing_request(request: dict) -> bool:
    return any(not request.get(key) for key in ("request_id", "run_id", "actor_id", "session_id"))


def _prepare_locked(directory: Path, rows: list[dict], request: dict) -> tuple[list[dict], dict]:
    digest = argument_digest(request)
    for row in rows:
        if row.get("kind") == "provider_request" and row.get("request_id") == request["request_id"]:
            if row.get("argument_digest") != digest:
                return rows, {"ok": False, "status": "operation_conflict", "request_id": request["request_id"]}
            return rows, {"ok": True, "status": "prepared", "request_id": request["request_id"], "reused": True}
    event = {
        "schema_version": SCHEMA_VERSION,
        "kind": "provider_request",
        "event_id": uuid.uuid4().hex,
        "operation_id": request["request_id"],
        "request_id": request["request_id"],
        "run_id": request["run_id"],
        "actor_id": request["actor_id"],
        "session_id": request["session_id"],
        "status": "prepared",
        "argument_digest": digest,
    }
    if request.get("job_id"):
        event["job_id"] = request["job_id"]
    _append_control(directory, event)
    return _control_rows(directory), {"ok": True, "status": "prepared", "request_id": request["request_id"], "reused": False}


def _dispatch_identity(attempt: dict) -> dict:
    identity = {
        "request_id": attempt.get("request_id"),
        "attempt_id": attempt.get("attempt_id"),
        "run_id": attempt.get("run_id"),
        "actor_id": attempt.get("actor_id"),
        "session_id": attempt.get("session_id"),
    }
    if attempt.get("job_id"):
        identity["job_id"] = attempt["job_id"]
    if attempt.get("generation"):
        identity["generation"] = attempt["generation"]
    return identity


def _fence_reason(rows: list[dict], attempt: dict) -> str | None:
    """A committed stop or recovery fence. Settled totals alone do not stop a dispatch."""
    if any(row.get("kind") == "run_stop" for row in rows):
        return "run_stopped"
    if any(row.get("kind") == "run_state" and row.get("status") == "recovering" for row in rows):
        return "recovering"
    generation = next(
        (row.get("generation") for row in reversed(rows) if row.get("kind") == "run_generation" and row.get("generation")),
        None,
    )
    if generation is not None and attempt.get("generation") != generation:
        return "stale_generation"
    return None


def begin_dispatch(directory: Path, attempt: dict) -> dict:
    """Record a dispatch that the caller is sending inside this same locked section."""
    return _dispatch_locked(directory, attempt, lambda: "invoked")


def serve_dispatch(directory: Path, attempt: dict, acknowledge) -> dict:
    """Check the stop, let the caller invoke transport, then record the receipt before unlocking.

    ``acknowledge`` runs while the control lock is held. It must return ``invoked`` only after
    transport has been called, and it must not wait for the response. Any other return records
    the attempt as unsent. A closed acknowledge (broken pipe, empty read) releases the lock.
    """
    return _dispatch_locked(directory, attempt, acknowledge)


def _dispatch_locked(directory: Path, attempt: dict, acknowledge) -> dict:
    """Admit one transport attempt, or record that it was not sent.

    Replaying an attempt does not authorize a second send. A transport error after invocation
    stays uncertain: it is not proof of no charge.
    """
    if _missing_request(attempt) or not attempt.get("attempt_id"):
        raise OperationRejected("invalid_input", str(attempt.get("attempt_id") or attempt.get("request_id") or ""))
    with control_lock(directory):
        rows = _ensure_accounting_failures(directory, _ensure_threshold_stop(directory, _control_rows(directory)))
        digest = argument_digest(_dispatch_identity(attempt))
        prior = [
            row for row in rows if row.get("kind") == "dispatch" and row.get("attempt_id") == attempt["attempt_id"]
        ]
        if prior:
            last = prior[-1]
            if last.get("argument_digest") != digest:
                return {
                    "ok": False,
                    "admitted": False,
                    "status": "operation_conflict",
                    "request_id": attempt["request_id"],
                    "attempt_id": attempt["attempt_id"],
                }
            return {
                "ok": True,
                "admitted": False,
                "reused": True,
                "status": last.get("status"),
                "sent": last.get("sent"),
                "request_id": attempt["request_id"],
                "attempt_id": attempt["attempt_id"],
            }
        existing = next(
            (row for row in rows if row.get("kind") == "provider_request" and row.get("request_id") == attempt["request_id"]),
            None,
        )
        if existing and any(existing.get(key) != attempt.get(key) for key in ("run_id", "actor_id", "session_id")):
            return {
                "ok": False,
                "admitted": False,
                "status": "operation_conflict",
                "request_id": attempt["request_id"],
                "attempt_id": attempt["attempt_id"],
            }
        if existing is None:
            request = {
                "request_id": attempt["request_id"],
                "run_id": attempt["run_id"],
                "actor_id": attempt["actor_id"],
                "session_id": attempt["session_id"],
            }
            if attempt.get("job_id"):
                request["job_id"] = attempt["job_id"]
            rows, prepared = _prepare_locked(directory, rows, request)
            if not prepared["ok"]:
                return {
                    "ok": False,
                    "admitted": False,
                    "status": "operation_conflict",
                    "request_id": attempt["request_id"],
                    "attempt_id": attempt["attempt_id"],
                }
        reason = _fence_reason(rows, attempt)
        if reason is None and acknowledge() != "invoked":
            reason = "launch_failed"
            status = "failed_before_start"
            sent = "unsent"
        else:
            status = "rejected_before_dispatch" if reason else "dispatch_started"
            sent = "unsent" if reason else "uncertain"
        event = {
            "schema_version": SCHEMA_VERSION,
            "kind": "dispatch",
            "event_id": uuid.uuid4().hex,
            "operation_id": attempt["attempt_id"],
            "request_id": attempt["request_id"],
            "attempt_id": attempt["attempt_id"],
            "run_id": attempt["run_id"],
            "actor_id": attempt["actor_id"],
            "session_id": attempt["session_id"],
            "status": status,
            "sent": sent,
            "argument_digest": digest,
        }
        if reason:
            event["reason"] = reason
        if attempt.get("job_id"):
            event["job_id"] = attempt["job_id"]
        if attempt.get("generation"):
            event["generation"] = attempt["generation"]
        _append_control(directory, event)
        return {
            "ok": True,
            "admitted": reason is None,
            "status": status,
            "sent": sent,
            "reason": reason,
            "request_id": attempt["request_id"],
            "attempt_id": attempt["attempt_id"],
            "reused": False,
        }


def _prepared(rows: list[dict]) -> dict[str, dict]:
    return {row["request_id"]: row for row in rows if row.get("kind") == "provider_request" and row.get("request_id")}


def _settlement_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("kind") == "settlement"]


def _canonical_settlement(settlement: dict) -> dict:
    covered = list(settlement.get("covered_request_ids") or [])
    return {
        "settlement_id": settlement.get("settlement_id"),
        "reconciles": settlement.get("reconciles"),
        "covered_request_ids": covered,
        "state": settlement.get("state"),
        "amount": settlement.get("amount"),
        "usage": settlement.get("usage"),
        "actor_id": settlement.get("actor_id"),
        "session_id": settlement.get("session_id"),
        "job_id": settlement.get("job_id"),
        "run_id": settlement.get("run_id"),
        "transport": settlement.get("transport"),
        "irreconcilable": bool(settlement.get("irreconcilable")),
    }


def _apply_coverage(rows: list[dict]) -> dict:
    """One charge per covered request. A later reconciliation replaces an unknown amount."""
    charges: dict[str, dict] = {}
    unknown: set[str] = set()
    originals: dict[str, dict] = {}
    for row in _settlement_rows(rows):
        if row.get("reconciles"):
            continue
        originals[row["settlement_id"]] = row
        amount = _decimal_amount(row.get("counted_amount")) if row.get("state") == "known" else None
        for request_id in row.get("covered_request_ids") or []:
            if amount is None:
                unknown.add(request_id)
                charges.pop(request_id, None)
            else:
                unknown.discard(request_id)
                charges[request_id] = {
                    "amount": amount,
                    "actor_id": row.get("actor_id"),
                    "job_id": row.get("job_id"),
                    "settlement_id": row["settlement_id"],
                }
    for row in _settlement_rows(rows):
        if not row.get("reconciles"):
            continue
        amount = _decimal_amount(row.get("counted_amount"))
        if amount is None:
            continue
        for request_id in row.get("covered_request_ids") or []:
            unknown.discard(request_id)
            charges[request_id] = {
                "amount": amount,
                "actor_id": row.get("actor_id"),
                "job_id": row.get("job_id"),
                "settlement_id": row["settlement_id"],
            }
    # Grouped coverage stores the whole amount on every covered id. Count each settlement once.
    seen: set[str] = set()
    total = Decimal("0")
    by_actor: dict[str, Decimal] = {}
    by_job: dict[str, Decimal] = {}
    for charge in charges.values():
        if charge["settlement_id"] in seen:
            continue
        seen.add(charge["settlement_id"])
        total += charge["amount"]
        if charge.get("actor_id"):
            by_actor[charge["actor_id"]] = by_actor.get(charge["actor_id"], Decimal("0")) + charge["amount"]
        if charge.get("job_id"):
            by_job[charge["job_id"]] = by_job.get(charge["job_id"], Decimal("0")) + charge["amount"]
    return {
        "total": total,
        "by_actor": by_actor,
        "by_job": by_job,
        "unknown": sorted(unknown),
        "originals": originals,
        "covered": {request_id for row in originals.values() for request_id in row.get("covered_request_ids") or []},
        "accounting_failures": [
            row
            for row in rows
            if row.get("kind") == "accounting_failure" and unknown.intersection(row.get("covered_request_ids") or [])
        ],
    }


def _projection(directory: Path, coverage: dict, stopped: bool, stop_reason: str | None) -> None:
    report = {
        "spent_usd": _money(coverage["total"]),
        "limit_usd": _money(ACTUAL_COST_THRESHOLD),
        "accounting": "unknown" if coverage["unknown"] else "known",
        "unknown_requests": coverage["unknown"],
        "accounting_failures": coverage["accounting_failures"],
        "stopped": stopped,
        "stop_reason": stop_reason,
        "by_actor": {key: _money(value) for key, value in sorted(coverage["by_actor"].items())},
        "by_job": {key: _money(value) for key, value in sorted(coverage["by_job"].items())},
        "projection_of": "control.jsonl",
    }
    path = directory / "cost.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def _spend_view(rows: list[dict], *, reused: bool = False, stop_transition: bool = False) -> dict:
    coverage = _apply_coverage(rows)
    stops = [row.get("reason") for row in rows if row.get("kind") == "run_stop"]
    settlements = {
        row["settlement_id"]: {"state": row.get("state"), "reconciles": row.get("reconciles")}
        for row in _settlement_rows(rows)
        if row.get("settlement_id")
    }
    return {
        "ok": True,
        "total": _money(coverage["total"]),
        "accounting": "unknown" if coverage["unknown"] else "known",
        "unknown_requests": coverage["unknown"],
        "accounting_failures": coverage["accounting_failures"],
        "by_actor": {key: _money(value) for key, value in coverage["by_actor"].items()},
        "by_job": {key: _money(value) for key, value in coverage["by_job"].items()},
        "stopped": bool(stops),
        "stop_reason": stops[-1] if stops else None,
        "stop_transition": stop_transition,
        "stops": [reason for reason in stops if reason],
        "settlements": settlements,
        "reused": reused,
        "status": "committed",
    }


def _ensure_threshold_stop(directory: Path, rows: list[dict]) -> list[dict]:
    """A crash between the settlement line and the stop line is repaired under the same lock."""
    coverage = _apply_coverage(rows)
    if coverage["total"] < ACTUAL_COST_THRESHOLD:
        return rows
    if any(row.get("kind") == "run_stop" and row.get("reason") == "spend_threshold" for row in rows):
        return rows
    _append_control(
        directory,
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "run_stop",
            "event_id": uuid.uuid4().hex,
            "reason": "spend_threshold",
            "total": _money(coverage["total"]),
            "threshold": _money(ACTUAL_COST_THRESHOLD),
        },
    )
    rows = _control_rows(directory)
    coverage = _apply_coverage(rows)
    _projection(directory, coverage, True, "spend_threshold")
    return rows


def _ensure_accounting_failures(directory: Path, rows: list[dict]) -> list[dict]:
    recorded = {row.get("settlement_id") for row in rows if row.get("kind") == "accounting_failure"}
    changed = False
    for row in _settlement_rows(rows):
        if not row.get("irreconcilable") or row.get("state") != "unknown" or row["settlement_id"] in recorded:
            continue
        _append_control(
            directory,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "accounting_failure",
                "event_id": uuid.uuid4().hex,
                "category": "accounting_unknown",
                "settlement_id": row["settlement_id"],
                "covered_request_ids": row["covered_request_ids"],
            },
        )
        recorded.add(row["settlement_id"])
        changed = True
    return _control_rows(directory) if changed else rows


def read_state(directory: Path) -> dict:
    """The shared actual-cost view. Repairs a missing threshold stop, then refreshes cost.json."""
    with control_lock(directory):
        rows = _ensure_accounting_failures(directory, _ensure_threshold_stop(directory, _control_rows(directory)))
        coverage = _apply_coverage(rows)
        reason = next((row.get("reason") for row in reversed(rows) if row.get("kind") == "run_stop"), None)
        _projection(directory, coverage, reason is not None, reason)
        return _spend_view(rows)


def settle_usage(directory: Path, settlement: dict) -> dict:
    """Settle one provider charge, or reconcile an earlier unknown report without charging it twice."""
    settlement_id = str(settlement.get("settlement_id") or "")
    covered = list(settlement.get("covered_request_ids") or [])
    if not settlement_id or not covered or settlement.get("state") not in ("known", "unknown"):
        raise OperationRejected("invalid_input", settlement_id)
    if any(not isinstance(request_id, str) or not request_id for request_id in covered):
        raise OperationRejected("invalid_input", settlement_id)
    with control_lock(directory):
        rows = _ensure_accounting_failures(directory, _ensure_threshold_stop(directory, _control_rows(directory)))
        digest = argument_digest(_canonical_settlement(settlement))
        for row in _settlement_rows(rows):
            if row.get("settlement_id") != settlement_id:
                continue
            if row.get("argument_digest") != digest:
                return {
                    "ok": False,
                    "status": "operation_conflict",
                    "settlement_id": settlement_id,
                    "total": _spend_view(rows)["total"],
                }
            return {
                **_spend_view(rows, reused=True),
                "settlement_id": settlement_id,
                "state": row["state"],
            }
        prepared = _prepared(rows)
        missing = [request_id for request_id in covered if request_id not in prepared]
        if missing:
            raise OperationRejected("not_found", settlement_id)
        coverage = _apply_coverage(rows)
        reconciles = settlement.get("reconciles")
        if reconciles:
            original = coverage["originals"].get(reconciles)
            if original is None or original.get("state") != "unknown":
                return {"ok": False, "status": "operation_conflict", "settlement_id": settlement_id}
            if list(original.get("covered_request_ids") or []) != covered:
                return {"ok": False, "status": "operation_conflict", "settlement_id": settlement_id}
            if any(
                row.get("reconciles") == reconciles and row.get("state") == "known" for row in _settlement_rows(rows)
            ):
                return {"ok": False, "status": "operation_conflict", "settlement_id": settlement_id}
        elif any(request_id in coverage["covered"] for request_id in covered):
            return {"ok": False, "status": "operation_conflict", "settlement_id": settlement_id}
        amount = _decimal_amount(settlement.get("amount")) if settlement["state"] == "known" else None
        reported = _usage_amount(settlement.get("usage"))
        if amount is None or reported is None or amount != reported:
            amount = None
        state = "known" if amount is not None else "unknown"
        before = coverage["total"]
        already_stopped = any(row.get("kind") == "run_stop" and row.get("reason") == "spend_threshold" for row in rows)
        event = {
            "schema_version": SCHEMA_VERSION,
            "kind": "settlement",
            "event_id": uuid.uuid4().hex,
            "operation_id": settlement_id,
            "settlement_id": settlement_id,
            "run_id": settlement.get("run_id"),
            "actor_id": settlement.get("actor_id"),
            "session_id": settlement.get("session_id"),
            "covered_request_ids": covered,
            "state": state,
            "counted_amount": _money(amount) if amount is not None else None,
            "reported_amount": settlement.get("amount") if isinstance(settlement.get("amount"), str) else None,
            "usage": settlement.get("usage"),
            "irreconcilable": bool(settlement.get("irreconcilable")),
            "argument_digest": digest,
        }
        if settlement.get("job_id"):
            event["job_id"] = settlement["job_id"]
        if reconciles:
            event["reconciles"] = reconciles
        if settlement.get("transport"):
            event["transport"] = settlement["transport"]
        if settlement.get("candidate_ids"):
            event["candidate_ids"] = list(settlement["candidate_ids"])
        _append_control(directory, event)
        rows = _control_rows(directory)
        coverage = _apply_coverage(rows)
        stop_transition = False
        if (
            state == "known"
            and not already_stopped
            and coverage["total"] >= ACTUAL_COST_THRESHOLD
            and before < ACTUAL_COST_THRESHOLD
        ):
            rows = _ensure_threshold_stop(directory, rows)
            stop_transition = True
        rows = _ensure_accounting_failures(directory, rows)
        coverage = _apply_coverage(rows)
        stops = [row for row in rows if row.get("kind") == "run_stop"]
        reason = stops[-1].get("reason") if stops else None
        _projection(directory, coverage, bool(stops), reason)
        view = _spend_view(rows, stop_transition=stop_transition)
        view["settlement_id"] = settlement_id
        view["state"] = state
        return view


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
