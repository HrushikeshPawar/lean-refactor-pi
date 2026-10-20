"""Recover existing proof work without constructing proofs or acknowledging delivery."""

from __future__ import annotations

import hashlib
from pathlib import Path

from arena import campaign, run_control


def check_mode(proof_id: str, evaluation_id: str, theorem: dict) -> str | None:
    """An execution's mode is established by its existing canonical evaluation key."""
    return next((mode for mode in ("fast", "full")
                 if campaign._evaluation_key(proof_id, mode, theorem) == evaluation_id), None)


def recover(directory: Path, history: list[dict], *, open_sessions: set[str]) -> dict:
    from arena import orchestration

    evaluations = []
    issues = []
    candidates = {row["candidate_id"]: row for row in history if row.get("kind") == "candidate"}
    results = {row["key"]: row for row in history if row.get("kind") == "evaluation" and row.get("key")}
    latest = {}
    for row in history:
        if row.get("type") == "verification":
            identity = (row["job_id"], row.get("check_id") or f"legacy:{row['job_id']}:{row['evaluation_id']}")
            latest[identity] = row
    pending = [row for row in latest.values() if row.get("state") in {"queued", "running"}]
    for row in pending:
        if row.get("session_id") in open_sessions:
            continue
        proof_id = row.get("proof_id")
        result = results.get(row["evaluation_id"])
        if result is None:
            candidate = candidates.get(proof_id)
            failure = _candidate_failure(directory, history, candidate)
            if failure:
                issues.append({"evaluation_id": row["evaluation_id"], "reason": failure})
                continue
            theorem = campaign.problem(history[0]["theorem"])
            if check_mode(proof_id, row["evaluation_id"], theorem) is None:
                issues.append({"evaluation_id": row["evaluation_id"], "reason": "evaluation_context_changed"})
                continue
        state = campaign._verification_outcome(result["result"]) if result is not None else "queued"
        arguments = _check_arguments(row)
        if result is None and row.get("state") == "running":
            arguments["recovery_of"] = row["event_id"]
        orchestration.note_verification(directory, **arguments, state=state)
        evaluations.append(row["evaluation_id"])

    # Filing can crash before either the fast evaluation or its full-check enqueue.
    # The existing queue admits saved candidates; it does not reconstruct their proof.
    eligible = {row["id"] for row in campaign._autocheck_jobs(campaign._summaries(history))}
    for proof_id, candidate in candidates.items():
        if candidate.get("origin") == "reference":
            continue
        if candidate.get("session_id") in open_sessions or any(
            row.get("kind") == "attempt" and (row.get("proof_id") or row.get("candidate_id")) == proof_id
            and row.get("session_id") in open_sessions for row in history
        ):
            continue
        candidate_results = [row for row in results.values() if row.get("candidate_id") == proof_id]
        if candidate_results and proof_id not in eligible:
            continue
        if any(row.get("proof_id") == proof_id for row in pending):
            continue
        failure = _candidate_failure(directory, history, candidate)
        if failure:
            issues.append({"proof_id": proof_id, "reason": failure})
            continue
        theorem = campaign.problem(history[0]["theorem"])
        key = campaign._evaluation_key(proof_id, "full", theorem)
        campaign._queue_full_check(directory, directory.name, proof_id)
        campaign._mark_queued(directory, campaign.events(directory), "recovery", "full", [proof_id])
        evaluations.append(key)

    _recover_findings(directory)
    retained = orchestration._history(directory)
    return {
        "evaluations": sorted(set(evaluations)),
        "delivery_ids": [row["event_id"] for row in retained
                         if row.get("event_id") and orchestration._selectable(row, None)],
        "proof_recovery_issues": issues,
    }


def _check_arguments(row: dict) -> dict:
    return {key: row[key] for key in (
        "job_id", "evaluation_id", "run_id", "actor_id", "session_id", "check_id", "proof_id", "attempt_ids", "recovery_of",
    ) if row.get(key) is not None}


def _candidate_failure(directory: Path, history: list[dict], candidate: dict | None) -> str | None:
    if candidate is None:
        return "candidate_missing"
    name = history[0].get("theorem")
    proof_id = candidate["candidate_id"]
    path = directory / "proofs" / f"{proof_id}.lean"
    if not name or not path.is_file():
        return "proof_artifact_missing"
    if hashlib.sha256((name + "\0" + path.read_text()).encode()).hexdigest() != proof_id:
        return "proof_artifact_mismatch"
    if candidate.get("evaluator_sha256") != campaign._evaluator_sha():
        return "evaluation_context_changed"
    theorem = campaign.problem(name)
    if candidate.get("source_versions") != [list(pair) for pair in campaign.versions(theorem)]:
        return "evaluation_context_changed"
    return None


def _recover_findings(directory: Path) -> None:
    """Join exact committed attempts and results; only normal delivery advances cursors."""
    from arena import orchestration

    with run_control.control_lock(directory):
        history = orchestration._history(directory)
        assignments = {row["activation_id"]: row for row in history if row.get("type") == "delegation"}
        existing = {(row.get("activation_id"), row.get("attempt_id"), row.get("evaluation_id"))
                    for row in history if row.get("type") == "worker_finding"}
        for attempt in history:
            if attempt.get("kind") != "attempt" or not attempt.get("event_id"):
                continue
            assignment = assignments.get(attempt.get("activation_id"))
            if assignment is None or not attempt.get("generation"):
                continue
            if (attempt.get("actor_id"), attempt.get("session_id"), attempt.get("job_id")) != (
                assignment["worker_actor_id"], assignment["worker_session_id"], assignment["job_id"],
            ):
                continue
            proof_id = attempt.get("proof_id") or attempt.get("candidate_id")
            for result in history:
                if (result.get("kind") != "evaluation" or result.get("candidate_id") != proof_id
                        or not result.get("key")
                        or campaign._verification_outcome(result.get("result") or {}) != "passed"):
                    continue
                identity = (assignment["activation_id"], attempt["event_id"], result["key"])
                if identity in existing:
                    continue
                existing.add(identity)
                # The delegation's committed operation is the original ownership authority.
                campaign._append(directory, {
                    "schema_version": run_control.SCHEMA_VERSION,
                    "event_id": run_control.argument_digest(["recovered_finding", *identity]),
                    "type": "worker_finding", "operation_id": assignment["operation_id"],
                    "run_id": assignment["run_id"], "actor_id": attempt["actor_id"],
                    "session_id": attempt["session_id"], "job_id": assignment["job_id"],
                    "activation_id": assignment["activation_id"], "generation": attempt["generation"],
                    "attempt_id": attempt["event_id"], "proof_id": proof_id,
                    "evaluation_id": result["key"], "request_id": attempt.get("request_id"), "late": True,
                })
        orchestration._wake()
