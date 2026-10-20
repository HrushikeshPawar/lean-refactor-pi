"""Submitted full-check ownership and retry smoke, using the existing fake Lean seam."""

import os
from unittest.mock import patch

from arena import campaign, orchestration, run_control
from tests.graph_support import FakeRunCase


class VerificationWaitTests(FakeRunCase):
    def test_submitted_check_owners_and_retry(self):
        for job in ("a", "b"):
            def record(writer, job=job):
                return [writer.append_ledger({
                    "type": "delegation", "job_id": job, "activation_id": f"activation-{job}",
                    "worker_actor_id": f"worker-{job}", "worker_session_id": f"session-{job}",
                })]

            run_control.apply_operation(self.directory, {
                "operation_id": f"delegate-{job}", "kind": "delegation", "arguments": {"job": job},
                "run_id": "logic", "actor_id": "sol", "session_id": "sol-session", "job_id": job,
            }, record)

        proof = "theorem t : True := by\n  exact True.intro"
        for job in ("a", "b"):
            with patch.dict(os.environ, {"ARENA_ACTOR_ID": f"worker-{job}",
                                         "ARENA_SESSION_ID": f"session-{job}", "ARENA_JOB_ID": job}):
                result = campaign.record_evaluation(
                    "T", "logic", proof, "fast", materialize_live=False,
                    operation={"type": "rewritten_from", "from": []},
                )
            self.assertTrue(orchestration._open_checks(self.directory, [job]))

        queued = [row for row in orchestration._history(self.directory)
                  if row.get("type") == "verification" and row["state"] == "queued"]
        self.assertEqual({row["job_id"] for row in queued}, {"a", "b"})
        self.assertEqual(len({row["check_id"] for row in queued}), 1)
        self.assertTrue(all(row["attempt_ids"] for row in queued))
        candidate = next(row for row in campaign._summaries(campaign.events(self.directory))
                         if row["id"] == result["candidate_id"])
        inconclusive = {"ok": False, "compat": {}, "tokens": None, "heartbeat": None, "timeout": True}
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol", "ARENA_SESSION_ID": "sol-session", "ARENA_JOB_ID": ""}), patch.object(
            campaign, "_evaluate", return_value=inconclusive,
        ), patch.object(campaign, "write_state"):
            campaign._run_full_check("T", "logic", candidate)
        self.assertFalse(orchestration._open_checks(self.directory, ["a", "b"]))

        entered = []

        def evaluate(*args, **kwargs):
            self.assertTrue(orchestration._open_checks(self.directory, ["a"]))
            self.assertTrue(orchestration._open_checks(self.directory, ["b"]))
            entered.append(True)
            return self.fake_eval(*args, **{key: value for key, value in kwargs.items() if key != "lane"})

        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol", "ARENA_SESSION_ID": "sol-session", "ARENA_JOB_ID": ""}), patch.object(
            campaign, "_evaluate", side_effect=evaluate,
        ), patch.object(campaign, "write_state"):
            campaign._run_full_check("T", "logic", candidate)
        self.assertEqual(entered, [True])
        self.assertFalse(orchestration._open_checks(self.directory, ["a", "b"]))
        history = campaign.events(self.directory)
        terminal = [row for row in orchestration._history(self.directory)
                    if row.get("type") == "verification" and row["state"] == "passed"
                    and row.get("proof_id") == result["candidate_id"]
                    and row.get("evaluation_id") == queued[0]["evaluation_id"]]
        self.assertEqual({row["job_id"] for row in terminal}, {"a", "b"})
        self.assertEqual(len({row["check_id"] for row in terminal}), 1)
        self.assertNotEqual(terminal[0]["check_id"], queued[0]["check_id"])
        evaluation = next(row for row in reversed(history) if row.get("kind") == "evaluation"
                          and row.get("key") == terminal[0]["evaluation_id"])
        self.assertLess(history.index(evaluation), history.index(terminal[0]))
        self.assertIn("check_id", orchestration._public_event(terminal[0]))
        self.assertEqual(campaign._verification_owners(self.directory, "unrelated-proof"), [])

        campaign._append(self.directory, {
            "type": "verification", "job_id": "legacy-job", "evaluation_id": "legacy-eval", "state": "running",
        })
        orchestration.note_verification(
            self.directory, job_id="legacy-job", evaluation_id="legacy-eval", state="passed",
            run_id="logic", actor_id="sol", session_id="sol-session",
        )
        self.assertFalse(orchestration._open_checks(self.directory, ["legacy-job"]))
