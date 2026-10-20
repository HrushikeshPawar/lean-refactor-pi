"""Small durable-evidence boundary check, without Lean or providers."""

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from arena import campaign, experiments
from arena.run_control import OperationRejected


class ExperimentEvidenceTests(unittest.TestCase):
    def test_exact_committed_evidence_and_replay(self):
        with tempfile.TemporaryDirectory() as root, patch.object(campaign, "ROOT", Path(root)):
            code = "-- λ\u2028\u2029\r\n#check Nat  \r\n"
            env = {
                "ARENA_ACTOR_ID": "ds1",
                "ARENA_SESSION_ID": "session1",
                "ARENA_JOB_ID": "job1",
                "ARENA_ACTIVATION_ID": "activation1",
                "ARENA_GENERATION": "4",
                "ARENA_REQUEST_ID": "request1",
                "ARENA_TOOL_CALL_ID": "call1",
            }
            with patch.dict("os.environ", env):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    accepted = list(pool.map(lambda _: experiments.accept("run", code, []), range(2)))
                self.assertEqual(accepted[0]["experiment_id"], accepted[1]["experiment_id"])
                self.assertEqual(sorted(row["replayed"] for row in accepted), [False, True])
                other = experiments.accept("run", code, [], operation_id="other-call")
                self.assertNotEqual(other["experiment_id"], accepted[0]["experiment_id"])
                with self.assertRaises(OperationRejected):
                    experiments.accept("run", "different", [])
            chosen = accepted[0]
            experiments.record_raw("run", chosen["experiment_id"], (1, "raw\nλ"), {"version": "v1"})
            self.assertEqual(experiments.retrieve("run", chosen["experiment_id"])["returncode"], 1)
            with patch.dict("os.environ", {"ARENA_ACTOR_ID": "sol"}):
                outcome = {
                    "code": code,
                    "digest": chosen["code_sha256"],
                    "outcome": "failure",
                    "raw": "raw\nλ",
                    "rendered": ["failure"],
                    "elapsed_ms": 2,
                    "input_ref": chosen["input_ref"],
                    "context": {"version": "v1", "commit": "abc"},
                }
                experiments.finish("run", chosen["experiment_id"], **outcome)
                experiments.finish("run", chosen["experiment_id"], **outcome)
                with self.assertRaises(OperationRejected):
                    experiments.finish("run", chosen["experiment_id"], **{**outcome, "code": "changed"})
            result = experiments.retrieve("run", chosen["experiment_id"])
            self.assertEqual(result["code"], code)
            self.assertEqual(result["actor_id"], "ds1")
            self.assertEqual(result["activation_id"], "activation1")
            self.assertEqual(result["generation"], "4")
            self.assertEqual(result["request_id"], "request1")
            self.assertEqual(result["raw"], "raw\nλ")
            self.assertEqual(result["input_ref"], chosen["input_ref"])
            self.assertEqual(result["context"]["version"], "v1")
            self.assertEqual(result["submitted_context"], {"theorem_run": "run"})
            rows = [
                row
                for row in campaign.events(campaign.run_dir("run"))
                if row.get("experiment_id") == chosen["experiment_id"]
            ]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row.get("operation_id") and row.get("event_id") for row in rows))
            campaign._append(
                campaign.run_dir("run"),
                {
                    "kind": "scratch",
                    "experiment_id": "partial",
                    "phase": "accepted",
                    "code": "hidden",
                    "operation_id": "uncommitted",
                },
            )
            self.assertIsNone(experiments.retrieve("run", "partial"))
            digest = hashlib.sha256(code.encode()).hexdigest()
            campaign._append(campaign.run_dir("run"), {"kind": "scratch", "code_sha256": digest, "code": code})
            historical = experiments.retrieve("run", digest)
            self.assertEqual(historical["validity"], "not_a_target_candidate")
            self.assertEqual(historical["code"], code)
