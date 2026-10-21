"""One offline journey through scratch promotion's immutable-input boundaries."""

import os
from unittest.mock import patch

from arena import campaign, tools
from tests.test_tools_read_goal_search import ToolCase


class ScratchPromotionBoundaryTests(ToolCase):
    def test_saved_parent_dependencies_and_verification(self):
        parent = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
        anchor = {"node": parent, "steps": [1, 1]}
        parent_proof = tools._node("logic", parent).proof_id
        with self.subTest("target detection failures retain the exact input"):
            code = "-- exact λ\r\n#check Nat\r\n"
            with patch.object(campaign, "problem", side_effect=RuntimeError("target context unavailable")):
                failed = tools.scratch_tool("T", "logic", {"code": code})["items"][0]
            retained = tools.experiments.retrieve("logic", failed["experiment_id"])
            self.assertEqual(retained["code"], code)
            self.assertEqual(retained["outcome"], "construction_error")
        with self.subTest("caller metadata cannot select files or bypass the graph"):
            resolved = tools._scratch_anchor("logic", {
                "at": {**anchor, "path": "/tmp/arbitrary-proof", "proof_sha256": "caller supplied"}
            })
            self.assertEqual(resolved["proof_id"], parent_proof)
            self.assertEqual(resolved["path"], f"proofs/{parent_proof}.lean")
            self.assertEqual(tools._scratch_anchor("logic", {"at": {
                "node": "missing", "steps": [1, 1], "path": resolved["path"],
                "proof_sha256": resolved["proof_sha256"],
            }}), "node")
        with self.subTest("indented and transitive declarations do not become local helpers"):
            unsafe = tools.experiments.accept("logic", "  theorem hidden : True := by trivial", [])
            dependent = tools.experiments.accept("logic", "have h : True := trivial", [unsafe["experiment_id"]])
            with patch.object(campaign, "compile_operation", side_effect=AssertionError("must not submit")):
                item = tools.scratch_tool("T", "logic", {
                    "replacement": "trivial", "at": anchor, "helpers": [dependent["experiment_id"]],
                })["items"][0]
            self.assertEqual(item["promotion"]["reason"], "helper_not_embeddable")
        with self.subTest("durable job cancellation prevents submission"):
            frozen = tools._scratch_anchor("logic", {"at": anchor})
            job = {"job_id": "j1", "anchor": frozen,
                   "activations": [{"activation_id": "a1", "state": "cancelling"}]}
            with (
                patch.dict(os.environ, {"ARENA_JOB_ID": "j1", "ARENA_ACTIVATION_ID": "a1"}),
                patch("arena.orchestration.jobs", return_value={"jobs": [job]}),
                patch.object(campaign, "compile_operation", side_effect=AssertionError("must not submit")),
            ):
                item = tools.scratch_tool("T", "logic", {"replacement": "trivial"})["items"][0]
            self.assertEqual(item["outcome"], "cancelled")
        with self.subTest("a complete exact target uses one compile and its frozen parent"):
            original = "theorem t : True := by\r\n  trivial\r\n"
            # Current Sol focus is intentionally different from the named replacement parent.
            tools.compile_tool("T", "logic", {"drafts": ["by\n  exact True.intro"]})
            with patch.object(campaign, "compile_operation", wraps=campaign.compile_operation) as compile_call:
                item = tools.scratch_tool("T", "logic", {
                    "replacement": "trivial", "at": anchor,
                })["items"][0]
            self.assertEqual(compile_call.call_args.kwargs["named_parent"], parent_proof)
            promotion = item["promotion"]
            self.assertTrue(promotion["attempt_id"])
            self.assertTrue(promotion["evaluation_id"])
            self.assertEqual(item["compatibility"], "not_checked")
            self.assertEqual(item["cold"], "not_checked")
            attempt = next(row for row in campaign.events(self.directory)
                           if row.get("event_id") == promotion["attempt_id"])
            self.assertEqual(attempt["data"]["named_parent"], parent_proof)
            self.assertEqual(attempt["data"]["operation"]["experiment_id"], item["experiment_id"])
            with (
                patch.object(campaign, "compile_operation", wraps=campaign.compile_operation) as compile_call,
                patch.object(tools.engine, "run_lean", side_effect=AssertionError("no scratch compile")),
            ):
                complete = tools.scratch_tool("T", "logic", {"code": original})["items"][0]
            self.assertEqual(compile_call.call_count, 1)
            self.assertEqual(complete["code"], original)
            self.assertEqual(complete["promotion"]["state"], "promoted")
            self.assertEqual(complete["context"]["form"], "full_target")
        with self.subTest("replay keeps the first full-target parent after focus moves"):
            request = {"code": "theorem t : True := by\n  exact True.intro"}
            with patch.dict(os.environ, {"ARENA_TOOL_CALL_ID": "scratch-full-replay"}):
                first = tools.scratch_tool("T", "logic", request)["items"][0]
                tools.reply.set_actor_focus("logic", parent_proof)
                with patch.object(campaign, "compile_operation", side_effect=AssertionError("replay must not compile")):
                    replay = tools.scratch_tool("T", "logic", request)["items"][0]
            self.assertEqual(replay["experiment_id"], first["experiment_id"])
            self.assertEqual(replay["promotion"], first["promotion"])
        with self.subTest("hole fillings keep experiment links in every construction"):
            for _ in range(2):
                filled = tools.scratch_tool("T", "logic", {
                    "replacement": "trivial", "at": {"node": parent, "hole": f"{parent}.h1"},
                })["items"][0]
                attempt = next(row for row in campaign.events(self.directory)
                               if row.get("event_id") == filled["promotion"]["attempt_id"])
                self.assertEqual(attempt["data"]["operation"]["experiment_id"], filled["experiment_id"])
        with self.subTest("cached full failure and unconfirmed cold checks stay visible"):
            child = tools._node("logic", promotion["node"])
            full = self.fake_eval("T", child.proof_text, "full")
            full["compat"]["v2"] = {"passed": False, "exit_code": 1}
            campaign.record_evaluation("T", "logic", child.proof_text, "full", precomputed=full)
            campaign._append(self.directory, {
                "kind": "cold_verification", "candidate_id": child.proof_id, "confirmed": False,
                "compat": {"v1": {"passed": True}, "v2": {"passed": True}},
            })
            repeated = tools.scratch_tool("T", "logic", {"replacement": "trivial", "at": anchor})["items"][0]
            self.assertEqual(repeated["promotion"]["verification"]["full"], "proof_error")
            self.assertEqual(repeated["promotion"]["verification"]["cold"], "inconclusive")
            self.assertNotEqual(repeated["promotion"]["attempt_id"], promotion["attempt_id"])
        with self.subTest("holes and unavailable execution are not promoted successes"):
            with patch.object(campaign, "_has_hole", return_value=True):
                item = tools.scratch_tool("T", "logic", {"replacement": "sorry", "at": anchor})["items"][0]
            self.assertEqual(item["promotion"]["reason"], "incomplete")
            self.assertEqual(item["promotion"]["verification"]["fast"], "incomplete")
            raw = {"ok": True, "timeout": True, "compat": {
                "v1": {"passed": False, "timeout": True, "exit_code": None},
            }}
            with patch.object(campaign, "_compile_probe", return_value=raw):
                item = tools.scratch_tool("T", "logic", {"replacement": "exact ?_", "at": anchor})["items"][0]
            self.assertEqual(item["promotion"]["verification"]["fast"], "inconclusive")
            self.assertEqual(item["promotion"]["reason"], "inconclusive")
