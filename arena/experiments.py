"""Durable scratch experiments: exact input, then a retrievable outcome.

Promotion is a later slice. A local outcome is not target validity, compatibility, or cold status.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from arena import campaign
from arena.run_control import actor_ids


def accept(run_id: str, code: str, helpers: list[str]) -> dict:
    """Store the exact accepted snippet before context construction or Lean."""
    directory = campaign.run_dir(run_id)
    digest = hashlib.sha256(code.encode()).hexdigest()
    prior = sum(1 for row in _scratch(directory) if row.get("phase") == "accepted")
    experiment_id = f"e{prior + 1}-{digest[:8]}"
    identity = actor_ids(run_id)
    receipt = campaign._append(
        directory,
        {
            "kind": "scratch",
            "phase": "accepted",
            "state": "accepted",
            "experiment_id": experiment_id,
            "code_sha256": digest,
            "code": code,
            "helpers": list(helpers),
            "actor_id": identity.get("actor_id"),
            "session_id": identity.get("session_id"),
            "job_id": identity.get("job_id"),
            "tool_call_id": identity.get("tool_call_id"),
            "context": {"theorem_run": run_id},
        },
    )
    return {
        "experiment_id": experiment_id,
        "code_sha256": digest,
        "input_ref": receipt,
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
) -> None:
    campaign._append(
        campaign.run_dir(run_id),
        {
            "kind": "scratch",
            "phase": "outcome",
            "state": outcome,
            "experiment_id": experiment_id,
            "code_sha256": digest,
            "code": code,
            "outcome": outcome,
            "raw": raw,
            "rendered": rendered,
            "diagnostic": diagnostic,
            "elapsed_ms": elapsed_ms,
            "input_ref": input_ref,
            **({"context": context} if context is not None else {}),
            "promotion": {"state": "not_promoted", "reason": "promotion_not_in_slice"},
            "validity": "not_a_target_candidate",
            "compatibility": "not_checked",
            "cold": "not_checked",
        },
    )


def retrieve(run_id: str, reference: str) -> dict | None:
    """Return one experiment, or an explicit missing-code record for a hash-only row."""
    rows = _scratch(campaign.run_dir(run_id))
    matched = [row for row in rows if row.get("experiment_id") == reference]
    if matched:
        return _joined(matched)
    hashed = [row for row in rows if row.get("code_sha256") == reference and not row.get("experiment_id")]
    if not hashed:
        return None
    stored = [row["code"] for row in hashed if "code" in row]
    unique = set(stored)
    if len(unique) > 1:
        return {"experiment_id": reference, "code": None, "code_status": "ambiguous", "outcome": "unavailable"}
    if len(unique) == 1:
        code = stored[0]
        return {"experiment_id": reference, "code": code, "code_status": "retained", "outcome": "recorded"}
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
        "context": accepted.get("context"),
        "outcome": "accepted",
        "raw": None,
        "rendered": [],
        "diagnostic": None,
        "elapsed_ms": None,
        "input_ref": None,
        "promotion": {"state": "not_promoted", "reason": "promotion_not_in_slice"},
        "validity": "not_a_target_candidate",
        "compatibility": "not_checked",
        "cold": "not_checked",
    }
    if outcome:
        for key in (
            "outcome",
            "raw",
            "rendered",
            "diagnostic",
            "elapsed_ms",
            "input_ref",
            "context",
            "promotion",
            "validity",
            "compatibility",
            "cold",
        ):
            if key in outcome:
                result[key] = outcome[key]
    return result


def _scratch(directory: Path) -> list[dict]:
    return [row for row in campaign.events(directory) if row.get("kind") == "scratch"]


def elapsed_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
