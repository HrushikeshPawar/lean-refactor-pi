"""Orchestrator plan, merge jobs, the worker compile nudge and packet stability (smoke tests per feature)."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import context, orchestration, patterns, plans, reply, text
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

    def test_plan_lines_say_missing_then_show_open_steps_and_stale_best(self):
        best = node("n5", 70.0)
        with patch.object(plans.orchestration, "run_best", return_value=best), \
                patch.object(plans, "current_plan", return_value=None):
            self.assertEqual(plans.lines(Path("run")), [text.render("replies/team.plan_missing")])
        plan = {"version": 2, "best": "n4", "steps": [TOKENS]}
        with patch.object(plans.orchestration, "run_best", return_value=best), \
                patch.object(plans, "current_plan", return_value=plan):
            lines = plans.lines(Path("run"))
        self.assertEqual(lines[0], "## Plan v2")
        self.assertEqual(lines[1], "- n2 lines 8-20 · tokens · -20 tokens, measured")
        self.assertIn(text.render("replies/team.plan_stale", node="n5", was="n4"), lines)


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
