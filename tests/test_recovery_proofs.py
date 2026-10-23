"""Saved proof recovery through the real queue and delivery, without Lean."""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena import campaign, orchestration, recovery_proofs, run_control


def test_recover_proof_intents_and_unacknowledged_findings():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "run-1"
        directory.mkdir()
        (directory / "proofs").mkdir()
        theorem = {"name": "demo"}
        pins = [["v1", "pin1"], ["v2", "pin2"]]
        with patch.object(campaign, "problem", return_value=theorem), patch.object(
            campaign, "versions", return_value=pins,
        ), patch.object(campaign, "_evaluator_sha", return_value="evaluator"), patch.object(
            campaign, "run_dir", return_value=directory,
        ):
            campaign._append(directory, {"kind": "init", "theorem": "demo", "versions": pins})

            def candidate(proof):
                proof_id = hashlib.sha256(("demo\0" + proof).encode()).hexdigest()
                (directory / "proofs" / f"{proof_id}.lean").write_text(proof)
                campaign._append(directory, {
                    "kind": "candidate", "candidate_id": proof_id, "origin": "model",
                    "evaluator_sha256": "evaluator", "source_versions": pins,
                })
                return proof_id

            persisted = candidate("by trivial")
            interrupted = candidate("by exact True.intro")
            complete = candidate("by constructor")
            identity = {"run_id": "run-1", "actor_id": "worker", "session_id": "worker-session", "job_id": "job"}
            delegation = {
                "type": "delegation", "activation_id": "activation", "state": "completed",
                "job_id": "job", "worker_actor_id": "worker", "worker_session_id": "worker-session",
                "scope": "proof", "anchor": {"proof_id": complete}, "tools": [], "task": "hypothesis",
            }
            run_control.apply_operation(directory, {
                "operation_id": "delegation", "kind": "delegation", "arguments": {"fixture": True},
                "run_id": "run-1", "actor_id": "sol", "session_id": "sol-session",
            }, lambda writer: writer.append_ledger(delegation))
            run_control.apply_operation(directory, {
                "operation_id": "attempt", "kind": "attempt", "arguments": {"fixture": True}, **identity,
                "activation_id": "activation",
            }, lambda writer: writer.append_ledger({
                "kind": "attempt", "event_id": "attempt", "proof_id": complete,
                "generation": "original-generation", "request_id": "original-request",
            }))
            fast = campaign._evaluation_key(interrupted, "fast", theorem)
            full = campaign._evaluation_key(complete, "full", theorem)
            orchestration.note_verification(directory, **identity, evaluation_id=fast, state="queued",
                                            check_id="original-check", proof_id=interrupted)
            orchestration.note_verification(directory, **identity, evaluation_id=fast, state="running",
                                            check_id="original-check", proof_id=interrupted)
            orchestration.note_verification(directory, **identity, evaluation_id=full, state="running",
                                            check_id="completed-check", proof_id=complete)
            campaign._append(directory, {
                "kind": "evaluation", "candidate_id": complete, "key": full, "mode": "full",
                "result": {"ok": True, "compat": {"v1": {"passed": True}, "v2": {"passed": True}}},
            })

            def recover():
                return recovery_proofs.recover(directory, orchestration._history(directory), open_sessions=set())

            first = recover()
            second = recover()
            assert first["proof_recovery_issues"] == second["proof_recovery_issues"] == []
            assert first["delivery_ids"] == second["delivery_ids"]
            assert orchestration._delivery_rows(directory, "sol") == []
            assert orchestration._delivery_rows(directory, "worker") == []
            history = orchestration._history(directory)
            findings = [row for row in history if row.get("type") == "worker_finding"]
            assert len(findings) == 1
            assert findings[0]["evaluation_id"] == full
            assert findings[0]["generation"] == "original-generation"
            checks = [row for row in history if row.get("type") == "verification"]
            assert any(row.get("check_id") == "original-check" and row["state"] == "queued" for row in checks)
            assert any(row.get("check_id") == "completed-check" and row["state"] == "passed" for row in checks)
            queued = campaign._submitted_full_jobs(directory, history, campaign._summaries(history), closing=False)
            assert {row["id"] for row in queued} == {persisted, interrupted}
            with patch.object(campaign, "record_evaluation") as evaluate, patch.object(campaign, "write_state"):
                campaign._run_full_check("demo", "run-1", next(row for row in queued if row["id"] == interrupted))
            assert evaluate.call_args.args[3] == "fast"
            assert evaluate.call_args.kwargs["verification_checks"][0]["check_id"] == "original-check"
            assert evaluate.call_args.kwargs["verification_checks"][0]["evaluation_id"] == fast
            resumed = evaluate.call_args.kwargs["verification_checks"][0]
            assert resumed["recovery_of"]
            orchestration.note_verification(directory, **resumed, state="running")
            latest = next(row for row in reversed(orchestration._history(directory))
                          if row.get("check_id") == "original-check")
            assert latest["state"] == "running"
            assert latest["recovery_of"] == resumed["recovery_of"]

            delivered = orchestration.await_results(directory, actor_id="sol", job_ids=["job"])
            assert findings[0]["event_id"] in {row["event_id"] for row in delivered["events"]}
            recover()
            assert orchestration._delivery_rows(directory, "sol")[-1]["event_id"] == delivered["next_cursor"]
            # A second actor has not consumed Sol's cursor or evidence.
            other = orchestration.await_results(directory, actor_id="planner", job_ids=["job"])
            assert {row["event_id"] for row in other["events"]} == {row["event_id"] for row in delivered["events"]}
