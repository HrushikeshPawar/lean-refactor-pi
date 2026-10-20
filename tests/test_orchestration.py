"""Offline run-control journeys. No provider, Pi, or Lean process."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import run_control


def _request(directory: Path, request_id: str, actor_id: str, job_id: str) -> None:
    run_control.prepare_request(
        directory,
        {
            "request_id": request_id,
            "run_id": "run-1",
            "actor_id": actor_id,
            "session_id": f"{actor_id}-session",
            "job_id": job_id,
        },
    )


class V8ControlSmokeTests(unittest.TestCase):
    def test_v8_shared_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            identity = {"request_id": "body-check", "run_id": "run-1", "actor_id": "sol", "session_id": "sol-session"}
            prepared = {**identity, "body": {"prompt": "first"}}
            run_control.prepare_request(directory, prepared)
            self.assertTrue(run_control.prepare_request(directory, prepared)["reused"])
            changed = run_control.prepare_request(directory, {**prepared, "body": {"prompt": "changed"}})
            self.assertEqual(changed["status"], "operation_conflict")
            _request(directory, "sol-call", "sol", "sol-job")
            _request(directory, "worker-a", "worker", "job-a")
            _request(directory, "worker-b", "worker", "job-a")
            _request(directory, "worker-missing", "worker", "job-b")
            _request(directory, "worker-zero", "worker", "job-b")
            _request(directory, "worker-cancelled", "worker", "job-c")

            # The worker finishes first. Its grouped compaction covers both of its calls once.
            first = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-worker",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-a",
                    "covered_request_ids": ["worker-b", "worker-a"],
                    "candidate_ids": ["proof-1", "proof-2"],
                    "state": "known",
                    "amount": "1.00",
                    "usage": {"cost": {"total": 1}},
                },
            )
            self.assertEqual(first["total"], "1.00")
            self.assertFalse(first["stopped"])
            self.assertEqual(first["by_actor"]["worker"], "1.00")
            self.assertEqual(first["by_job"]["job-a"], "1.00")

            crossing = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-sol",
                    "run_id": "run-1",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "job_id": "sol-job",
                    "covered_request_ids": ["sol-call"],
                    "state": "known",
                    "amount": "1.50",
                    "usage": {"cost": {"total": 1.5}},
                },
            )
            self.assertEqual(crossing["total"], "2.50")
            self.assertTrue(crossing["stop_transition"])
            self.assertEqual(crossing["stop_reason"], "spend_threshold")

            replayed = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-sol",
                    "run_id": "run-1",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "job_id": "sol-job",
                    "covered_request_ids": ["sol-call"],
                    "state": "known",
                    "amount": "1.50",
                    "usage": {"cost": {"total": 1.5}},
                },
            )
            self.assertTrue(replayed["reused"])
            self.assertEqual(replayed["total"], "2.50")
            self.assertFalse(replayed["stop_transition"])

            overlap = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-overlap",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-a",
                    "covered_request_ids": ["worker-a"],
                    "state": "known",
                    "amount": "1.00",
                    "usage": {},
                },
            )
            self.assertEqual(overlap["status"], "operation_conflict")

            missing = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-missing",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-missing"],
                    "state": "unknown",
                    "amount": "0",
                    "usage": {},
                },
            )
            self.assertEqual(missing["total"], "2.50")
            self.assertEqual(missing["accounting"], "unknown")
            self.assertIn("worker-missing", missing["unknown_requests"])
            self.assertFalse(missing["stop_transition"])

            zero = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-zero",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-zero"],
                    "state": "known",
                    "amount": "0",
                    "usage": {"cost": {"total": 0}},
                },
            )
            self.assertEqual(zero["total"], "2.50")
            self.assertEqual(zero["accounting"], "unknown")
            self.assertNotIn("worker-zero", zero["unknown_requests"])

            cancelled = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "settle-cancelled",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-c",
                    "covered_request_ids": ["worker-cancelled"],
                    "state": "known",
                    "amount": "0.20",
                    "transport": "cancelled",
                    "usage": {"cost": {"total": 0.2}},
                },
            )
            self.assertEqual(cancelled["total"], "2.70")
            self.assertFalse(cancelled["stop_transition"])

            reconciliation = {
                "reconciles": "settle-missing",
                "run_id": "run-1",
                "actor_id": "worker",
                "session_id": "worker-session",
                "job_id": "job-b",
                "covered_request_ids": ["worker-missing"],
                "state": "known",
                "amount": "0.05",
            }
            incomplete = run_control.settle_usage(
                directory,
                {**reconciliation, "settlement_id": "recon-incomplete", "usage": {}},
            )
            self.assertEqual(incomplete["accounting"], "unknown")
            self.assertEqual(incomplete["total"], "2.70")
            reconciled = run_control.settle_usage(
                directory,
                {
                    "settlement_id": "recon-missing",
                    "reconciles": "settle-missing",
                    "run_id": "run-1",
                    "actor_id": "worker",
                    "session_id": "worker-session",
                    "job_id": "job-b",
                    "covered_request_ids": ["worker-missing"],
                    "state": "known",
                    "amount": "0.05",
                    "usage": {"cost": {"total": 0.05}},
                },
            )
            self.assertEqual(reconciled["total"], "2.75")
            self.assertEqual(reconciled["accounting"], "known")
            self.assertEqual(reconciled["unknown_requests"], [])
            self.assertEqual(reconciled["by_actor"]["sol"], "1.50")
            self.assertEqual(reconciled["by_actor"]["worker"], "1.25")

            state = run_control.read_state(directory)
            self.assertEqual(state["total"], "2.75")
            self.assertEqual(state["stops"], ["spend_threshold"])
            self.assertEqual(state["settlements"]["settle-missing"]["state"], "unknown")
            projection = json.loads((directory / "cost.json").read_text())
            self.assertEqual(projection["spent_usd"], "2.75")
            self.assertEqual(projection["projection_of"], "control.jsonl")
            self.assertNotEqual(projection.get("written_by"), "runner_ledger_reconstruction")

            recovery = directory / "recovery"
            _request(recovery, "crossing", "sol", "sol-job")
            crossing_charge = {
                "settlement_id": "crossing-charge",
                "run_id": "run-1",
                "actor_id": "sol",
                "session_id": "sol-session",
                "covered_request_ids": ["crossing"],
                "state": "known",
                "amount": "2.50",
                "usage": {"cost": {"total": "2.50"}},
            }
            append = run_control._append_control

            def interrupt_stop(path, event):
                if event["kind"] == "run_stop":
                    raise RuntimeError("stop append interrupted")
                return append(path, event)

            with (
                patch.object(run_control, "_append_control", side_effect=interrupt_stop),
                self.assertRaisesRegex(RuntimeError, "stop append interrupted"),
            ):
                run_control.settle_usage(recovery, crossing_charge)
            repaired = run_control.settle_usage(recovery, crossing_charge)
            self.assertTrue(repaired["reused"])
            self.assertTrue(repaired["stopped"])
            self.assertEqual(repaired["stops"], ["spend_threshold"])
            self.assertEqual(repaired["total"], "2.50")

            partial = directory / "partial"
            _request(partial, "partial-write", "sol", "sol-job")
            write = run_control.os.write
            with patch.object(
                run_control.os, "write", side_effect=lambda fd, data: write(fd, data[: max(1, len(data) // 2)])
            ):
                settled = run_control.settle_usage(
                    partial,
                    {
                        **crossing_charge,
                        "settlement_id": "partial-charge",
                        "covered_request_ids": ["partial-write"],
                        "amount": "0.01",
                        "usage": {"cost": {"total": "0.01"}},
                    },
                )
            self.assertEqual(settled["total"], "0.01")
            torn = b'{"kind":"settlement","incomplete":"\xc3'
            with (partial / "control.jsonl").open("ab") as ledger:
                ledger.write(torn)
            _request(partial, "after-torn", "sol", "sol-job")
            self.assertIn(torn + b"\n", (partial / "control.jsonl").read_bytes())
            self.assertIn("after-torn", run_control._prepared(run_control._control_rows(partial)))

            failed = directory / "unknown"
            _request(failed, "unknown-call", "worker", "job-a")
            unknown_charge = {
                "settlement_id": "unknown-charge",
                "run_id": "run-1",
                "actor_id": "worker",
                "session_id": "worker-session",
                "covered_request_ids": ["unknown-call"],
                "state": "unknown",
                "irreconcilable": True,
            }

            def interrupt_failure(path, event):
                if event["kind"] == "accounting_failure":
                    raise RuntimeError("failure append interrupted")
                return append(path, event)

            with (
                patch.object(run_control, "_append_control", side_effect=interrupt_failure),
                self.assertRaisesRegex(RuntimeError, "failure append interrupted"),
            ):
                run_control.settle_usage(failed, unknown_charge)
            self.assertTrue(run_control.settle_usage(failed, unknown_charge)["reused"])
            failure = run_control.read_state(failed)
            self.assertEqual(failure["accounting_failures"][0]["category"], "accounting_unknown")
            self.assertEqual(failure["total"], "0")
            self.assertEqual(failure["accounting"], "unknown")
            self.assertEqual(len(failure["accounting_failures"]), 1)
