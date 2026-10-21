"""Fast checks for exact submission receipts and interruption safety."""

import json
import tempfile
import unittest
from decimal import Decimal
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

        # The run's threshold comes from its run-config; a run without one uses 2.50.
        def charge(directory, amount):
            run_control.prepare_request(
                directory,
                {"request_id": "call", "run_id": "run", "actor_id": "sol", "session_id": "session", "body": {"p": 1}},
            )
            return run_control.settle_usage(
                directory,
                {
                    "settlement_id": "charge",
                    "run_id": "run",
                    "actor_id": "sol",
                    "session_id": "session",
                    "covered_request_ids": ["call"],
                    "state": "known",
                    "amount": amount,
                    "usage": {"cost": {"total": amount}},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "run-config.json").write_text('{"limit_usd": 0.3}')
            view = charge(directory, "0.30")
            self.assertEqual((view["stop_reason"], view["limit_usd"]), ("spend_threshold", "0.3"))
            self.assertEqual(json.loads((directory / "cost.json").read_text())["limit_usd"], "0.3")
            self.assertEqual(run_control.run_threshold(directory), Decimal("0.3"))

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            view = charge(directory, "0.30")
            self.assertFalse(view["stopped"])
            self.assertEqual(view["limit_usd"], "2.50")
            (directory / "run-config.json").write_text('{"limit_usd": 9}')
            self.assertEqual(run_control.run_threshold(directory), Decimal("2.50"))
