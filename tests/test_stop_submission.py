"""Fast stop-boundary journeys with fake Lean and committed graph replay."""

import hashlib
from unittest.mock import patch

from arena import campaign, graph, run_control
from tests.graph_support import FakeRunCase


class StopSubmissionTests(FakeRunCase):
    def setUp(self):
        super().setUp()
        problem = patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t"})
        problem.start()
        self.addCleanup(problem.stop)

    def stop(self):
        with run_control.control_lock(self.directory):
            run_control._append_control(
                self.directory,
                {
                    "kind": "run_stop",
                    "event_id": "operator-stop",
                    "reason": "operator_interrupt",
                },
            )

    def projection(self):
        return graph.Graph.from_history(
            campaign.events(self.directory),
            campaign._proof_reader(self.directory),
            committed_operations=run_control.committed_operation_ids(self.directory),
        )

    def test_stopped_new_probe_never_calls_lean_or_publishes_a_node(self):
        self.stop()
        proof = "theorem t := by\n  bad"
        proof_id = hashlib.sha256(("T\0" + proof).encode()).hexdigest()
        with patch.object(campaign, "evaluate") as lean, self.assertRaises(run_control.SubmissionRefused):
            campaign.probe("T", "logic", proof)
        lean.assert_not_called()
        self.assertNotIn(proof_id, [node.proof_id for node in self.projection().nodes])
        self.assertFalse(
            any(
                row.get("proof_id") == proof_id and row.get("kind") == "probe"
                for row in campaign.events(self.directory)
            )
        )

    def test_uncommitted_candidate_cannot_be_grandfathered_after_stop(self):
        proof = "theorem t := by\n  interrupted"
        proof_id = hashlib.sha256(("T\0" + proof).encode()).hexdigest()
        campaign._snapshot(self.directory, proof_id, proof)
        campaign._append(
            self.directory,
            {"kind": "candidate", "candidate_id": proof_id, "operation_id": "uncommitted-submission", "parents": []},
        )
        self.stop()
        with patch.object(campaign, "evaluate") as lean, self.assertRaises(run_control.SubmissionRefused):
            campaign.record_evaluation("T", "logic", proof, "full")
        lean.assert_not_called()
        self.assertNotIn(proof_id, [node.proof_id for node in self.projection().nodes])

    def test_admitted_failed_probe_finishes_after_stop_without_authorizing_a_retry(self):
        proof = "theorem t := by\n  bad"

        def lean(name, submitted, mode, **_kwargs):
            self.stop()
            return self.fake_eval(name, submitted, mode)

        with patch.object(campaign, "evaluate", side_effect=lean) as checks:
            campaign.probe("T", "logic", proof)
        self.assertEqual(checks.call_count, 1)
        node = next(node for node in self.projection().nodes if node.proof_text == proof)
        self.assertEqual(node.status, "broken")
        history = campaign.events(self.directory)
        attempts = [row for row in history if row.get("kind") == "attempt" and row.get("proof_id") == node.proof_id]
        self.assertEqual(len(attempts), 1)
        with patch.object(campaign, "evaluate") as checks:
            campaign.probe("T", "logic", proof)
        checks.assert_not_called()
        self.assertEqual(
            len(
                [
                    row
                    for row in campaign.events(self.directory)
                    if row.get("kind") == "attempt" and row.get("proof_id") == node.proof_id
                ]
            ),
            1,
        )

    def test_batch_admits_each_exact_proof_before_parallel_lean(self):
        drafts = ["theorem t := by\n  bad", "theorem t := by\n  bad\n  sorry"]
        expected = {hashlib.sha256(("T\0" + proof).encode()).hexdigest() for proof in drafts}

        def lean(name, proof, mode, **_kwargs):
            submitted = {
                row["proof_id"]
                for row in run_control._control_rows(self.directory)
                if row.get("kind") == "candidate_submission"
            }
            self.assertTrue(expected <= submitted)
            self.stop()
            return self.fake_eval(name, proof, mode)

        with patch.object(campaign, "evaluate", side_effect=lean) as checks:
            outcome = campaign.probe_batch("T", "logic", drafts)
        self.assertEqual(checks.call_count, 2)
        self.assertTrue(all(not item.get("error") for item in outcome["drafts"]))
        self.assertTrue(expected <= {node.proof_id for node in self.projection().nodes})

    def test_salvage_cannot_publish_a_new_unsubmitted_sketch_after_stop(self):
        parent = self.projection().nodes[0]
        sketch = "theorem t := by\n  have h : True := sorry\n  exact h"

        def constructed(*args, **kwargs):
            self.stop()
            return {
                "status": "salvaged",
                "compiles": 0,
                "rounds": [],
                "text": sketch,
                "result": {"compat": {"v1": {"passed": True}}},
                "kept": 0.5,
            }

        with patch.object(campaign, "salvage_proof", side_effect=constructed):
            outcome = campaign._run_salvage("T", "logic", parent)
        self.assertEqual(outcome["status"], "run_stopped")
        self.assertFalse(any(node.proof_text == sketch for node in self.projection().nodes))
        self.assertFalse(any(row.get("kind") == "probe" for row in campaign.events(self.directory)))

    def test_known_harness_proof_adoption_commits_before_its_check(self):
        proof = "theorem t := by\n  existing"
        result = campaign.record_evaluation("T", "logic", proof, "fast", origin="assembly")
        proof_id = result["candidate_id"]
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), proof_id), "ineligible")

        def lean(name, submitted, mode, known=None, **_kwargs):
            self.stop()
            return self.fake_eval(name, submitted, mode, known=known)

        with campaign.compile_authorization(), patch.object(campaign, "evaluate", side_effect=lean):
            campaign.record_evaluation("T", "logic", proof, "full")
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), proof_id), "eligible")
