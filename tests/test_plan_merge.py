"""Orchestrator notices (no plan tool), merge jobs, the worker compile nudge and packet stability (smoke tests per feature)."""

import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import context, ideas, merge_recipe, orchestration, patterns, reply, team_reply, text
from arena.steps import Step
from tests.test_text import ROWS, _fixture

def node(node_id: str, score: float, job: str | None = None, verified: bool = True, tokens: int = 100,
         heartbeats: int = 50, steps: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=node_id, proof_id=node_id, score=score, verified=verified, status="closed", route="r1",
                           attempts=[{"job_id": job}] if job else [], tokens=tokens, heartbeats=heartbeats,
                           origin="candidate", proof_text=f"by\n  simp {node_id}", steps=steps or [])


class NoticeTests(unittest.TestCase):
    def notice(self, bucket, *, best, merges=(), action=None, digest=()):
        """sol's notices for one tool call, with the run's best, merge jobs and attempt log digest patched."""
        with patch.object(orchestration, "run_best", return_value=best), \
                patch.object(orchestration, "merge_jobs", return_value=list(merges)), \
                patch.object(ideas, "lines_for", return_value=("sol", list(digest))):
            bucket["calls"] = bucket.get("calls", 0) + 1
            return team_reply.notices(Path("run"), bucket, action)

    def test_no_plan_notice_is_ever_said_even_after_delegates(self):
        bucket = {}
        for _ in range(12):
            self.assertEqual(self.notice(bucket, best=node("n5", 70.0), action="delegate"), ([], []))

    def test_a_harness_started_merge_job_is_said_once_and_a_sol_started_one_never(self):
        bucket = {}
        harness = {"job_id": "j9", "label": "job9", "nodes": ["n5", "n2", "n3"], "creator": "harness"}
        own = {"job_id": "j8", "label": "job8", "nodes": ["n5", "n2"], "creator": None}
        first = self.notice(bucket, best=node("n5", 70.0), merges=[harness, own])
        self.assertEqual(first, (["merge_started"], [
            "Merge job job9 started by the harness on n5, n2, n3; message or cancel it as needed."]))
        self.assertEqual(self.notice(bucket, best=node("n5", 70.0), merges=[harness, own]), ([], []))

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
                patch.object(orchestration, "merge_jobs", return_value=[]), \
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
                patch.object(team_reply, "notices", return_value=(["merge_started"], ["Merge job job2 started by the harness on n2, n3; message or cancel it as needed."])), \
                patch.object(team_reply.campaign, "run_dir", return_value=Path("run")):
            result = team_reply.sol_notices("run", "delegate", {"ok": True, "text": "t"})
        self.assertEqual(result, {"ok": True, "text": "t",
                                  "context": {"sections": [["", "Merge job job2 started by the harness on n2, n3; message or cancel it as needed."]],
                                              "kinds": ["merge_started"]}})
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

    objectives: dict = {}

    def auto(self, *, merges=(), states=(), best="n2", state="completed", jobs=("j1", "j2")):
        """_merge_auto_nodes with earlier merge jobs ({job: start ts, nodes}) and their state rows patched."""
        first = {job: {"scope": "merge", "ts": ts, "anchor": {"nodes": list(nodes)}} for job, ts, nodes in merges}
        first.update({job: {"scope": "island", "ts": 0.5} for job in jobs})
        live = {job: {"state": state} for job, *_ in merges}
        with patch.object(orchestration, "_first_delegations", return_value=first), \
                patch.object(orchestration, "_job_snapshot", side_effect=lambda d, job: live.get(job)), \
                patch.object(orchestration, "_states", return_value=list(states)), \
                patch.object(orchestration, "events", return_value=[{"ts": 0.1}]), \
                patch.object(orchestration, "_job_original", side_effect=lambda d, job: {"objective": self.objectives.get(job)}), \
                patch.object(orchestration, "run_best", return_value=self.nodes[best]):
            return orchestration._merge_auto_nodes(Path("run"))

    def add(self, name, score, job, **kwargs):
        self.nodes[name] = node(name, score, job=job, **kwargs)
        self.times[name] = float(len(self.times) + 1)

    def test_the_harness_picks_each_jobs_record_with_the_run_best_first_and_waits_for_new_records_after_a_merge(self):
        self.assertEqual(self.auto(), ["n2", "n3", "n4"])  # first merge: j1's and j2's top-score nodes
        done = [("m1", 4.5, ["n2", "n3", "n4"])]
        ended = [{"job_id": "m1", "state": "completed", "ts": 5.0}]
        self.assertEqual(self.auto(merges=done, states=ended), [])  # nothing new since it ended
        self.add("n8", 64.0, "j2")  # lower than j2's merged n4: no new record
        self.assertEqual(self.auto(merges=done, states=ended), [])
        self.assertEqual(self.auto(merges=done, state="active"), [])  # running merge job: no restart
        for number, job in enumerate(("j3", "j4")):  # new records, below the clear margin: two of three needed
            self.add(f"n2{number}", 50.0 + number, job)
            self.assertEqual(self.auto(merges=done, states=ended, jobs=("j1", "j2", "j3", "j4")), [])
        self.add("n22", 52.0, "j5")
        self.assertEqual(self.auto(merges=done, states=ended, jobs=("j1", "j2", "j3", "j4", "j5")),
                         ["n2", "n3", "n4", "n20", "n21", "n22"])

    def test_a_clear_record_on_an_axis_starts_a_merge_alone_and_an_ordinary_one_does_not(self):
        self.objectives = {"j2": "tokens", "j3": "heartbeats"}
        del self.nodes["n4"], self.nodes["n3"]
        self.nodes["n2"].tokens, self.nodes["n2"].heartbeats = 360, 5000
        done = [("m1", 4.5, ["n2", "n3"])]
        ended = [{"job_id": "m1", "state": "completed", "ts": 5.0}]
        jobs = ("j1", "j2", "j3")
        self.add("n20", 60.0, "j2", tokens=357, heartbeats=5100)  # 3 tokens ahead: not clear
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), [])
        self.add("n21", 60.0, "j2", tokens=355, heartbeats=5400)  # 5 tokens ahead: clear
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), ["n2", "n21"])
        self.add("n22", 58.0, "j3", tokens=420, heartbeats=4950)  # 1 percent fewer heartbeats: not clear
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), ["n2", "n21", "n22"])  # n21 is clear
        done = [("m1", 4.5, ["n2", "n21"])]
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), [])  # n21 is merged; n22 is not clear
        self.add("n23", 58.0, "j3", tokens=424, heartbeats=4710)  # 5.8 percent fewer
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), ["n2", "n21", "n23"])
        done = [("m1", 4.5, ["n2", "n21"]), ("m2", 6.5, ["n2", "n21", "n23"])]
        self.add("n24", 58.0, "j3", tokens=424, heartbeats=4650)  # 1.3 percent past the merged n23: not new
        self.assertEqual(self.auto(merges=done, states=ended + [{"job_id": "m2", "state": "completed", "ts": 7.0}],
                                   jobs=jobs), [])
        self.nodes["n26"] = node("n26", 58.0, "j3", tokens=300, heartbeats=4000)  # a copy of the run best text is no record
        self.nodes["n26"].proof_text = self.nodes["n2"].proof_text
        self.times["n26"] = 30.0
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), [])
        self.add("n25", 40.0, "j3", tokens=300, heartbeats=9000)  # fewer tokens, but j3 is a heartbeat island
        self.assertEqual(self.auto(merges=done, states=ended, jobs=jobs), [])

    def test_start_merge_delegates_a_merge_job_owned_by_sol_and_created_by_the_harness(self):
        with patch.object(orchestration, "_run_status", return_value="running"), \
                patch.object(orchestration, "_merge_auto_nodes", return_value=["n2", "n4"]), \
                patch.object(orchestration, "_slot_open", return_value=True), \
                patch.object(orchestration, "_first_delegations", return_value={}), \
                patch.object(orchestration, "delegate", return_value={"ok": True}) as delegate:
            self.assertEqual(orchestration.start_merge(Path("run"), "opener"), {"ok": True})
            kwargs = delegate.call_args.kwargs
            self.assertEqual((kwargs["scope"], kwargs["anchor"], kwargs["creator"], kwargs["actor_id"]),
                             ("merge", {"nodes": ["n2", "n4"]}, "harness", "sol"))
            self.assertIn("n2, n4", kwargs["task"])
            delegate.reset_mock()
            with patch.object(orchestration, "_slot_open", return_value=False):
                self.assertIsNone(orchestration.start_merge(Path("run"), "opener"))
            delegate.assert_not_called()

    def test_merge_ends_when_its_last_saves_do_not_beat_the_best_at_save_time(self):
        with patch.object(orchestration, "_saved_times", side_effect=lambda directory: {**self.times, "n4": 4.0}):
            self.assertIsNone(orchestration._merge_end(Path("run"), "j1"))  # n2 and n3 are not the last four
        for name, score in (("n5", 61.0), ("n6", 62.0), ("n7", 63.0)):
            self.nodes[name] = node(name, score, job="j1")
            self.times[name] = float(len(self.times) + 1)
        self.assertEqual(orchestration._merge_end(Path("run"), "j1"), "not_beating")


class RecipeTests(unittest.TestCase):
    @staticmethod
    def steps(*pairs):
        return [Step(id=f"s{i}", first_line=i, last_line=i, text=t, hash=h, indent=0) for i, (t, h) in enumerate(pairs, 1)]

    def render(self, nodes, prices):
        table = {item.proof_id: [{"step": k, "tokens": v[0], "heartbeats": v[1], "points": 0} for k, v in prices[item.id].items()]
                 for item in nodes}
        with patch.object(orchestration, "proof_nodes", return_value={item.proof_id: item for item in nodes}), \
                patch.object(orchestration, "job_labels", return_value={"j1": "job1", "j2": "job2"}), \
                patch.object(merge_recipe.campaign, "step_costs", side_effect=lambda d, proof_id: table[proof_id]):
            return merge_recipe.lines(Path("run"), [item.id for item in nodes])

    def test_the_task_lists_each_node_and_only_steps_with_a_real_price_difference_with_the_cheaper_node(self):
        base = node("b", 80.0, "j1", tokens=360, heartbeats=5000,
                    steps=self.steps(("a", "h1"), ("b", "h2"), ("c", "h3"), ("d", "h4")))
        short = node("t", 79.0, "j2", tokens=355, heartbeats=5500,
                     steps=self.steps(("a", "h1"), ("b'", "h2x"), ("c", "h3"), ("d", "h4")))
        prices = {"b": {"s1": (10, 100), "s2": (40, 900), "s3": (30, 500), "s4": (20, 100)},
                  "t": {"s1": (10, 100), "s2": (30, 1500), "s3": (30, 500), "s4": (20, 100)}}
        got = self.render([base, short], prices)
        self.assertEqual(got[0], "Prices of the chosen nodes:")
        self.assertIn("b (run best, base): score 80.0, 360 tokens, 5000 HB, from job1", got[1])
        self.assertIn("t: score 79.0, 355 tokens, 5500 HB, from job2", got[2])
        self.assertEqual(len(got), 5)  # head + one differing step (s2); the equal steps are not listed
        self.assertIn("s2 in b (40 tokens, 900 HB) against s2 in t (30 tokens, 1500 HB): t is cheaper by 10 tokens, b is cheaper by 600 HB", got[4])

    def test_a_node_without_step_prices_is_said_so_instead_of_reading_as_no_difference(self):
        base = node("b", 80.0, "j1", steps=self.steps(("a", "h1")))
        other = node("t", 79.0, "j2", steps=self.steps(("a", "h1")))
        got = self.render([base, other], {"b": {"s1": (10, 100)}, "t": {}})
        self.assertIn("The steps of t have no price yet", got[-1])

    def test_one_node_cheaper_on_both_axes_is_said_once(self):
        self.assertEqual(merge_recipe._verdict("b", "t", (40, 30), (900, 800)), "t is cheaper by 10 tokens and 100 HB")
        self.assertEqual(merge_recipe._verdict("b", "t", (40, 40), (900, None)), "same price")

    def test_nodes_with_no_common_step_are_compared_overall_with_the_cheaper_nodes_steps(self):
        base = node("b", 80.0, "j1", tokens=360, heartbeats=5000, steps=self.steps(("a", "h1")))
        other = node("t", 79.0, "j2", tokens=340, heartbeats=5500, steps=self.steps(("z", "h9")))
        got = self.render([base, other], {"b": {"s1": (360, 5000)}, "t": {"s1": (340, 5500)}})
        self.assertIn("No step of t matches a step of the run best b", got[-1])
        self.assertIn("t is cheaper by 20 tokens, b is cheaper by 500 HB", got[-1])
        self.assertIn("The costliest steps of t: s1 (340 tokens, 5500 HB)", got[-1])


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
    def test_the_orchestrator_guides_a_stalled_job_before_its_own_compile_and_the_harness_starts_merge_jobs(self):
        packet = text.template("packet/team")
        self.assertIn("when your digest reports a job stalled", packet)
        self.assertIn("before your next compile of your own", packet)
        self.assertIn("guide the same way whenever you have no structure of your own to try", packet)
        self.assertIn("the harness starts it itself on those nodes", packet)
        self.assertNotIn("Delegate a merge job", packet)

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
