"""Fast checks for exact submission receipts and interruption safety."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, run_control


class SubmissionReceiptTests(unittest.TestCase):
    def test_exact_replay_partial_commit_and_threshold_repair(self):
        def attempt(operation_id="submit-1", **extra):
            return {
                "operation_id": operation_id,
                "run_id": "run",
                "actor_id": "sol",
                "session_id": "session",
                "proof_id": "proof",
                "proof_sha256": "hash",
                "authorization": "candidate",
                "inputs": {"base": "reference"},
                "evaluation": {"mode": "fast", "key": "evaluation-1", "state": "queued"},
                "candidate": {"kind": "candidate", "candidate_id": "proof"},
                **extra,
            }

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = run_control.submit_candidate(directory, attempt())
            self.assertTrue(first["ok"])
            self.assertEqual(first["receipt"]["status"], "committed")
            run_control._append_control(directory, {"kind": "run_stop", "reason": "operator_interrupt"})
            replay = run_control.submit_candidate(directory, attempt())
            self.assertTrue(replay["ok"])
            self.assertTrue(replay["reused"])
            self.assertFalse(run_control.submit_candidate(directory, attempt("new-invocation"))["ok"])
            self.assertEqual(
                run_control.submit_candidate(directory, attempt("new-invocation", inputs={}))["category"],
                "operation_conflict",
            )
            self.assertFalse(run_control.submit_candidate(directory, attempt("new-actor", actor_id="worker"))["ok"])
            conflict = run_control.submit_candidate(directory, attempt(evaluation={"mode": "full", "key": "other"}))
            self.assertEqual(conflict["category"], "operation_conflict")

        for boundary in ("evaluation_request", "operation_receipt"):
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                append = run_control._append_control

                def interrupt(path, event, boundary=boundary, append=append):
                    if event.get("kind") == boundary and (
                        boundary != "operation_receipt" or event.get("status") == "committed"
                    ):
                        raise OSError("interrupted submission")
                    return append(path, event)

                with (
                    patch.object(run_control, "_append_control", side_effect=interrupt),
                    self.assertRaisesRegex(OSError, "interrupted submission"),
                ):
                    run_control.submit_candidate(directory, attempt())
                run_control._append_control(directory, {"kind": "run_stop", "reason": "operator_interrupt"})
                self.assertFalse(run_control.submit_candidate(directory, attempt())["ok"])
                self.assertFalse(run_control.published_history(directory, campaign.events(directory)))

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # Model a crash after the known charge but before its derived threshold stop.
            run_control.prepare_request(
                directory,
                {
                    "request_id": "call",
                    "run_id": "run",
                    "actor_id": "sol",
                    "session_id": "session",
                    "body": {"prompt": "fixture"},
                },
            )
            with patch.object(run_control, "_ensure_threshold_stop", side_effect=lambda _directory, rows: rows):
                run_control.settle_usage(
                    directory,
                    {
                        "settlement_id": "charge",
                        "run_id": "run",
                        "actor_id": "sol",
                        "session_id": "session",
                        "covered_request_ids": ["call"],
                        "state": "known",
                        "amount": "2.50",
                        "usage": {"cost": {"total": "2.50"}},
                    },
                )
            self.assertFalse(any(row.get("kind") == "run_stop" for row in run_control._control_rows(directory)))
            refused = run_control.submit_candidate(directory, attempt())
            self.assertEqual(refused["status"], "run_stopped")
            self.assertEqual(run_control.read_state(directory)["stop_reason"], "spend_threshold")
