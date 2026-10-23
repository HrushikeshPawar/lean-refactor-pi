"""Orchestrator plan, merge jobs, the worker compile nudge and packet stability (smoke tests per feature)."""

import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import context, orchestration, patterns, plans, reply, team_reply, text
from tests.test_text import ROWS, _fixture

SHAPE = {"target": "whole proof", "kind": "shape", "expect": "-5 tokens, estimated", "status": "open"}
MERGE = {"target": "n3, n9", "kind": "merge", "expect": "-8 tokens, measured", "status": "open"}
TOKENS = {"target": "n2 lines 8-20", "kind": "tokens", "expect": "-20 tokens, measured", "status": "open"}


def node(node_id: str, score: float, job: str | None = None, verified: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=node_id, proof_id=node_id, score=score, verified=verified, status="closed", route="r1",
                           attempts=[{"job_id": job}] if job else [], tokens=100, heartbeats=50, origin="candidate",
                           proof_text="by\n  simp", steps=[])


class PlanTests(unittest.TestCase):
    def test_open_steps_need_a_shape_and_a_merge_step(self):
        self.assertEqual(plans._problem([TOKENS], None), ("plan_required", {"kind": "shape"}))
        self.assertEqual(plans._problem([SHAPE, TOKENS], None), ("plan_required", {"kind": "merge"}))
        self.assertIsNone(plans._problem([SHAPE, MERGE, TOKENS], None))
        self.assertEqual(plans._problem([{**TOKENS, "kind": "bogus"}], None), ("plan_steps", {}))


class NoticeTests(unittest.TestCase):
    def notice(self, bucket, *, plan, best, ready=(), action=None):
        """sol's notices for one tool call, with the run's plan, best and merge set patched."""
        with patch.object(plans, "current_plan", return_value=plan), \
                patch.object(orchestration, "run_best", return_value=best), \
                patch.object(orchestration, "merge_ready", return_value=list(ready)), \
                patch.object(team_reply, "_jobs_count", return_value=2):
            bucket["calls"] = bucket.get("calls", 0) + 1
            return team_reply.notices(Path("run"), bucket, action)

    def test_missing_plan_is_said_once_after_a_delegate_then_again_every_ten_calls(self):
        bucket = {}
        self.assertEqual(self.notice(bucket, plan=None, best=None), ([], []))
        self.assertEqual(self.notice(bucket, plan=None, best=None, action="delegate"),
                         (["plan_missing"], [text.render("replies/team.plan_missing")]))
        for _ in range(9):
            self.assertEqual(self.notice(bucket, plan=None, best=None), ([], []))
        self.assertEqual(self.notice(bucket, plan=None, best=None)[0], ["plan_missing"])

    def test_stale_plan_saved_before_any_best_says_the_original_proof_and_shows_open_steps(self):
        plan = {"version": 2, "best": None, "steps": [TOKENS]}
        kinds, lines = self.notice({}, plan=plan, best=node("n5", 70.0))
        self.assertEqual(kinds, ["plan_stale"])
        self.assertEqual(lines[0], text.render("replies/team.plan_stale", node="n5",
                                               was=text.render("replies/team.plan_original")))
        self.assertEqual(lines[1:], ["## Plan v2", "- n2 lines 8-20 · tokens · -20 tokens, measured"])

    def test_same_state_is_not_said_twice_but_a_new_best_or_a_changed_merge_set_is_said_again(self):
        bucket = {}
        plan = {"version": 3, "best": "n4", "steps": [TOKENS]}
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n5", 70.0), ready=["n2", "n3"])[0],
                         ["plan_stale", "merge_ready"])
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n5", 70.0), ready=["n2", "n3"]), ([], []))
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n6", 71.0), ready=["n2", "n3"])[0], ["plan_stale"])
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n6", 71.0), ready=["n2", "n3", "n4"])[0],
                         ["merge_ready"])

    def test_a_plan_with_no_open_step_is_said_once_per_version(self):
        plan = {"version": 1, "best": "n5", "steps": [{**TOKENS, "status": "done"}]}
        bucket = {}
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n5", 70.0))[0], ["plan_empty"])
        self.assertEqual(self.notice(bucket, plan=plan, best=node("n5", 70.0)), ([], []))

    def test_await_and_jobs_replies_carry_no_plan_or_merge_lines(self):
        plan = {"version": 2, "best": "n4", "steps": [TOKENS]}
        with patch.object(plans, "current_plan", return_value=plan), \
                patch.object(orchestration, "run_best", return_value=node("n5", 70.0)), \
                patch.object(orchestration, "merge_ready", return_value=["n2", "n3"]), \
                patch.object(team_reply, "open_requests", return_value=[]):
            awaited = team_reply.render("await_results", {"events": [], "jobs": []}, Path("run"))
            listed = team_reply.render("jobs", {"jobs": []}, Path("run"))
        for shown in (awaited, listed):
            self.assertNotIn("Plan v", shown)
            self.assertNotIn("Merge ready", shown)
            self.assertNotIn("this plan was saved against", shown)

    def test_only_sol_gets_the_notices_field_and_the_text_is_left_alone(self):
        with patch.object(reply, "current_actor", return_value="job-actor"):
            self.assertNotIn("notices", team_reply.sol_notices("run", "delegate", {"ok": True, "text": "t"}))
        with patch.object(reply, "current_actor", return_value="sol"), \
                patch.object(reply, "_delivery_lock", return_value=nullcontext()), \
                patch.object(reply, "_load", return_value={}), patch.object(reply, "_write_actor") as write, \
                patch.object(team_reply, "notices", return_value=(["merge_ready"], ["Merge ready: n2, n3."])), \
                patch.object(team_reply.campaign, "run_dir", return_value=Path("run")):
            result = team_reply.sol_notices("run", "delegate", {"ok": True, "text": "t"})
        self.assertEqual(result, {"ok": True, "text": "t",
                                  "notices": {"kinds": ["merge_ready"], "lines": ["Merge ready: n2, n3."]}})
        write.assert_called_once()

class MergeTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {}
        self.times = {}

        def add(item, time):
            self.nodes[item.id] = item
            self.times[item.id] = time

        add(node("n1", 60.0), 1.0)
        add(node("n2", 70.0, job="j1"), 2.0)
        add(node("n3", 68.0, job="j1"), 3.0)
        add(node("n4", 65.0, job="j2"), 4.0)
        self.patches = [
            patch.object(orchestration, "proof_nodes", side_effect=lambda directory: dict(self.nodes)),
            patch.object(orchestration, "_saved_times", side_effect=lambda directory: dict(self.times)),
            patch.object(orchestration, "job_labels", return_value={"j1": "job1", "j2": "job2"}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def test_defaults_are_the_run_best_then_each_jobs_newest_other_node(self):
        self.assertEqual(orchestration.merge_defaults(Path("run")), ["n2", "n3", "n4"])
        self.assertEqual(orchestration._merge_anchor(Path("run"), {"nodes": ["n4"]}), "merge")

    def test_merge_ends_when_its_last_saves_do_not_beat_the_best_at_save_time(self):
        with patch.object(orchestration, "_saved_times", side_effect=lambda directory: {**self.times, "n4": 4.0}):
            self.assertIsNone(orchestration._merge_end(Path("run"), "j1"))  # n2 and n3 are not the last four
        for name, score in (("n5", 61.0), ("n6", 62.0), ("n7", 63.0)):
            self.nodes[name] = node(name, score, job="j1")
            self.times[name] = float(len(self.times) + 1)
        self.assertEqual(orchestration._merge_end(Path("run"), "j1"), "not_beating")


class NudgeTests(unittest.TestCase):
    def test_compile_nudge_fires_at_the_fourth_call_and_restarts_after_a_compile(self):
        bucket = {}
        lines = [reply._compile_nudge("job-actor", bucket, "read") for _ in range(4)]
        self.assertEqual(lines[:3], [[], [], []])
        self.assertEqual(lines[3], [text.render("replies/tools.compile_nudge", calls=4)])
        self.assertEqual(reply._compile_nudge("job-actor", bucket, "compile"), [])
        self.assertEqual(reply._compile_nudge("job-actor", bucket, "read"), [])
        self.assertEqual(reply._compile_nudge("sol", {}, "read"), [])

    def test_an_axis_island_ranks_cards_that_lower_its_measure_first(self):
        favoured = {"effect": {"tokens": "down", "heartbeats": {"middle": "up"}}}
        other = {"effect": {"tokens": "up", "heartbeats": {"middle": "down"}}}
        self.assertTrue(patterns._favoured(favoured, "tokens", "middle"))
        self.assertFalse(patterns._favoured(other, "tokens", "middle"))
        self.assertTrue(patterns._favoured(other, "heartbeats", "middle"))
        self.assertFalse(patterns._favoured(favoured, None, "middle"))


class PacketTests(unittest.TestCase):
    def test_orchestrator_packet_is_byte_identical_and_carries_no_plan(self):
        cached, measured = _fixture("ski")
        with patch.object(context, "cached_context", return_value=cached), \
                patch.object(context, "reference_profile", return_value=measured):
            first = context.render_packet(ROWS["ski"], cache_only=True, model="gpt-6.1-sol")
            second = context.render_packet(ROWS["ski"], cache_only=True, model="gpt-6.1-sol")
        self.assertEqual(first, second)
        self.assertNotIn("Plan v", first)
        self.assertIn("save a plan with `plan`", first)


if __name__ == "__main__":
    unittest.main()
