"""Orchestrator notices (no plan tool), merge jobs, the worker compile nudge and packet stability (smoke tests per feature)."""

import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import context, ideas, orchestration, patterns, reply, team_reply, text
from tests.test_text import ROWS, _fixture

def node(node_id: str, score: float, job: str | None = None, verified: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=node_id, proof_id=node_id, score=score, verified=verified, status="closed", route="r1",
                           attempts=[{"job_id": job}] if job else [], tokens=100, heartbeats=50, origin="candidate",
                           proof_text="by\n  simp", steps=[])


class NoticeTests(unittest.TestCase):
    def notice(self, bucket, *, best, ready=(), action=None, digest=()):
        """sol's notices for one tool call, with the run's best, merge set and attempt log digest patched."""
        with patch.object(orchestration, "run_best", return_value=best), \
                patch.object(orchestration, "merge_ready", return_value=list(ready)), \
                patch.object(ideas, "lines_for", return_value=("sol", list(digest))), \
                patch.object(team_reply, "_jobs_count", return_value=2):
            bucket["calls"] = bucket.get("calls", 0) + 1
            return team_reply.notices(Path("run"), bucket, action)

    def test_no_plan_notice_is_ever_said_even_after_delegates(self):
        bucket = {}
        for _ in range(12):
            self.assertEqual(self.notice(bucket, best=node("n5", 70.0), action="delegate"), ([], []))

    def test_same_merge_set_is_not_said_twice_but_a_changed_one_is(self):
        bucket = {}
        self.assertEqual(self.notice(bucket, best=node("n5", 70.0), ready=["n2", "n3"])[0], ["merge_ready"])
        self.assertEqual(self.notice(bucket, best=node("n5", 70.0), ready=["n2", "n3"]), ([], []))
        self.assertEqual(self.notice(bucket, best=node("n6", 71.0), ready=["n2", "n3", "n4"])[0], ["merge_ready"])

    def test_the_attempt_log_digest_comes_first_under_its_own_kind(self):
        kinds, lines = self.notice({}, best=None, digest=["Kept i3 (n9)"])
        self.assertEqual((kinds, lines), (["ideas"], ["Kept i3 (n9)"]))

    def test_a_shorter_worker_node_is_said_once_per_node(self):
        short = {"node": "n9", "proof_id": "p9", "saved": 12, "best": 100, "tokens": 88, "heartbeats": 40}
        bucket = {}
        with patch.object(orchestration, "token_short", return_value=[short]), \
                patch.object(team_reply, "_costly_steps", return_value="s3 (30 tokens, 9 HB)"):
            first = self.notice(bucket, best=node("n5", 70.0))
            again = self.notice(bucket, best=node("n5", 70.0))
        self.assertEqual(first[0], ["token_short"])
        self.assertIn("n9 is 12 tokens shorter than the run best 100 (88 tokens, 40 HB). Its costliest steps: s3", first[1][0])
        self.assertEqual(again, ([], []))

    def test_await_and_jobs_replies_carry_no_merge_lines(self):
        with patch.object(orchestration, "run_best", return_value=node("n5", 70.0)), \
                patch.object(orchestration, "merge_ready", return_value=["n2", "n3"]), \
                patch.object(team_reply, "open_requests", return_value=[]):
            awaited = team_reply.render("await_results", {"events": [], "jobs": []}, Path("run"))
            listed = team_reply.render("jobs", {"jobs": []}, Path("run"))
        for shown in (awaited, listed):
            self.assertNotIn("Merge ready", shown)

    def test_only_sol_gets_the_notices_in_its_context_and_the_text_is_left_alone(self):
        with patch.object(reply, "current_actor", return_value="job-actor"):
            self.assertNotIn("context", team_reply.sol_notices("run", "delegate", {"ok": True, "text": "t"}))
        with patch.object(reply, "current_actor", return_value="sol"), \
                patch.object(reply, "_delivery_lock", return_value=nullcontext()), \
                patch.object(reply, "_load", return_value={}), patch.object(reply, "_write_actor") as write, \
                patch.object(team_reply, "notices", return_value=(["merge_ready"], ["Merge ready: n2, n3."])), \
                patch.object(team_reply.campaign, "run_dir", return_value=Path("run")):
            result = team_reply.sol_notices("run", "delegate", {"ok": True, "text": "t"})
        self.assertEqual(result, {"ok": True, "text": "t",
                                  "context": {"sections": [["", "Merge ready: n2, n3."]], "kinds": ["merge_ready"]}})
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
    def test_orchestrator_packet_is_byte_identical_and_carries_no_plan_paragraph(self):
        cached, measured = _fixture("ski")
        with patch.object(context, "cached_context", return_value=cached), \
                patch.object(context, "reference_profile", return_value=measured):
            first = context.render_packet(ROWS["ski"], cache_only=True, model="gpt-6.1-sol")
            second = context.render_packet(ROWS["ski"], cache_only=True, model="gpt-6.1-sol")
        self.assertEqual(first, second)
        self.assertNotIn("Plan v", first)
        self.assertNotIn("save a plan", first)
        self.assertIn("keeps an idea log of every attempt", first)


if __name__ == "__main__":
    unittest.main()
