"""Cold certification contract with injected compiler outcomes, no CLI/Pi/Lean."""

import contextlib
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from arena import campaign, run_control


def admit_fixture_proof(directory, proof_id):
    """Give human-readable fixture ids a real exact-byte submission receipt."""
    result = run_control.submit_candidate(directory, {
        "operation_id": f"fixture-submit-{proof_id}",
        "run_id": "run", "actor_id": "sol", "session_id": "fixture-session",
        "proof_id": proof_id,
        "proof_sha256": hashlib.sha256((directory / "proofs" / f"{proof_id}.lean").read_bytes()).hexdigest(),
        "authorization": "candidate", "inputs": {},
        "evaluation": {"mode": "full", "key": f"fixture-evaluation-{proof_id}", "state": "queued"},
    })
    assert result["ok"], result


class ColdOutcomeTests(unittest.TestCase):
    def test_exact_retry_fallback_and_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            directory = Path(temporary)
            (directory / "proofs").mkdir()
            benchmark = {"name": "T", "version_info": [{"v1": "pin1"}], "statement": "theorem t : True"}
            history = [{"kind": "init", "theorem": "T", "versions": [["v1", "pin1"]]}]
            (directory / "ledger.jsonl").write_text(json.dumps(history[0]) + "\n")
            higher = {
                "id": "higher",
                "heartbeats": 10,
                "verified": True,
                "status": "full",
                "score": 90,
                "n": 1,
                "origin": "model",
                "tokens": 4,
            }
            lower = {**higher, "id": "lower", "score": 70, "n": 2}
            high_bytes = b"theorem t : True := by\r\n  trivial  \r\n"
            low_bytes = b"theorem t : True := by\r\n  exact True.intro\r\n"
            (directory / "proofs/higher.lean").write_bytes(high_bytes)
            (directory / "proofs/lower.lean").write_bytes(low_bytes)
            admit_fixture_proof(directory, "higher")
            admit_fixture_proof(directory, "lower")
            for name, value in (("run_dir", directory), ("problem", benchmark), ("_evaluator_sha", "evaluator")):
                stack.enter_context(mock.patch.object(campaign, name, return_value=value))
            stack.enter_context(mock.patch.object(campaign.lean_health, "tripped", return_value=None))
            stack.enter_context(
                mock.patch.object(campaign, "lean_lock", side_effect=lambda *_: contextlib.nullcontext())
            )
            stack.enter_context(mock.patch.object(campaign, "force_cold", side_effect=contextlib.nullcontext))
            stack.enter_context(mock.patch.object(campaign, "_runtime_event"))
            stack.enter_context(mock.patch.object(campaign, "_summaries", return_value=[higher, lower]))
            stack.enter_context(mock.patch("arena.scoring.local_proxy", return_value=70))
            seen = []

            def evaluate(_name, proof, _mode, **_kwargs):
                seen.append(proof.encode())
                if proof.encode() == low_bytes:
                    return {"compat": {"v1": {"passed": True, "exit_code": 0}}, "heartbeat": 10}
                return {"compat": {"v1": {"passed": False, "timeout": True, "error": "clock"}}}

            stack.enter_context(mock.patch.object(campaign, "_evaluate", side_effect=evaluate))
            certified = campaign.cold_verify("run", lower)
            self.assertTrue(certified["confirmed"])
            # Concurrent finalizers cannot create two attempt-1 checks or exceed the cap.
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: campaign.cold_verify("run", higher), range(2)))
            result = campaign.submission("run")
            self.assertEqual(result["candidate_id"], "lower")
            self.assertEqual(result["pending_checks"][0]["cause"], "timeout")
            self.assertEqual((directory / "submission.lean").read_bytes(), low_bytes)
            self.assertEqual(seen, [low_bytes, high_bytes, high_bytes])
            attempts = campaign._cold_events(campaign.events(directory), "higher")
            self.assertEqual([event["attempt"] for event in attempts], [1, 2])
            self.assertEqual(len({event["check_id"] for event in attempts}), 1)
            self.assertEqual(attempts[-1]["proof_sha256"], hashlib.sha256(high_bytes).hexdigest())
            self.assertFalse(attempts[-1]["retryable"])
            # Certification for old bytes cannot authorize changed bytes or leave stale output.
            (directory / "proofs/lower.lean").write_bytes(low_bytes + b"-- changed\n")
            absent = campaign.submission("run")
            self.assertIsNone(absent["candidate"])
            self.assertEqual(absent["reason"], "no certified submission exists")
            self.assertFalse((directory / "submission.lean").exists())
            self.assertEqual(len(seen), 3)  # fallback is never newly searched or checked

            # Structured infrastructure is never a proof failure; completed exit 1 is.
            for info, expected in (
                ({"passed": False, "exit_code": 1, "cause": "context"}, "context"),
                ({"passed": False, "exit_code": 1, "error": "not found; denied"}, "proof_error"),
                ({"passed": False, "error": "Lean timed out"}, "timeout"),
            ):
                self.assertEqual(campaign._pin_cause(info), expected)
            # Missing bytes and health trips retain bounded, attributable evidence too.
            missing = campaign.cold_verify("run", {"id": "missing", "heartbeats": 10})
            self.assertEqual(missing["cause"], "context")
            retained = campaign._cold_events(campaign.events(directory), "missing")
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["check_id"], missing["check_id"])
            self.assertIsNone(retained[0]["proof_sha256"])
            (directory / "proofs/health.lean").write_bytes(low_bytes)
            admit_fixture_proof(directory, "health")
            with mock.patch.object(campaign.lean_health, "tripped", return_value={"reason": "memory"}):
                blocked = campaign.cold_verify("run", {**lower, "id": "health"})
            self.assertEqual(blocked["outcome"], "inconclusive")
            self.assertEqual(blocked["cause"], "resource_denial")
            self.assertEqual(len(seen), 3)

            with self.subTest("interrupted attempt consumes its original identity"):
                interrupted = {"id": "interrupted", "heartbeats": 10}
                (directory / "proofs/interrupted.lean").write_bytes(high_bytes)
                admit_fixture_proof(directory, "interrupted")
                with (
                    mock.patch.object(campaign, "_evaluate", side_effect=KeyboardInterrupt),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    campaign.cold_verify("run", interrupted)
                started = campaign._cold_events(campaign.events(directory), "interrupted")
                self.assertEqual(started[0]["state"], "running")
                retried = campaign.cold_verify("run", interrupted)
                final = campaign._cold_events(campaign.events(directory), "interrupted")
                self.assertEqual([attempt["attempt"] for attempt in final], [1, 2])
                self.assertEqual(final[0]["cause"], "worker_crash")
                self.assertEqual(final[0]["attempt_id"], started[0]["attempt_id"])
                self.assertEqual(retried["attempt"], 2)
                self.assertFalse(retried["retryable"])
                self.assertEqual(campaign.cold_verify("run", interrupted)["attempt_id"], retried["attempt_id"])
            with self.subTest("a retained proof error is terminal rather than an infrastructure retry"):
                failed = {"id": "proof-error", "heartbeats": 10}
                (directory / "proofs/proof-error.lean").write_bytes(high_bytes)
                admit_fixture_proof(directory, "proof-error")
                raw = {"compat": {"v1": {"passed": False, "exit_code": 1,
                                         "outcome": "proof_error", "cause": "proof_error"}}}
                with mock.patch.object(campaign, "_evaluate", return_value=raw) as check:
                    first = campaign.cold_verify("run", failed)
                    repeated = campaign.cold_verify("run", failed)
                self.assertEqual(check.call_count, 1)
                self.assertEqual(repeated["attempt_id"], first["attempt_id"])
                self.assertEqual(repeated["outcome"], "proof_error")
                self.assertFalse(repeated["retryable"])
