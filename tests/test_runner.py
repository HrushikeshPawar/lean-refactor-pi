"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import json
import unittest

from tests.pi_support import PI_AVAILABLE, FakeRun, message_text
from tools.arena_skill import SKILL_DIR, skill_hash

STOP = [{"text": "done"}]


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SkillAndThinkingTests(unittest.TestCase):
    def tearDown(self):
        for run in getattr(self, "runs", []):
            run.cleanup()

    def start(self, *extra: str) -> FakeRun:
        run = FakeRun(STOP * 6)
        self.runs = [*getattr(self, "runs", []), run]
        return run.run(*extra)

    def test_skill_is_in_the_first_provider_payload_and_hash_is_recorded(self):
        run = self.start()
        first = run.requests[0]["messages"][0]
        self.assertIn("Scoring is mechanical", message_text(first))
        self.assertIn("arena_skill_read", message_text(first) + str(first.get("toolsAdded")))
        config = run.json("run-config.json")
        self.assertEqual(config["skill"], {"name": "arena-lean", "sha256": skill_hash()})

    def test_thinking_level_is_a_recorded_option_and_reaches_the_provider(self):
        default = self.start()
        self.assertEqual(default.json("run-config.json")["thinking"], "high")
        self.assertEqual({r["thinking"] for r in default.requests}, {"high"})
        low = self.start("--thinking", "low")
        self.assertEqual(low.json("run-config.json")["thinking"], "low")
        self.assertEqual({r["thinking"] for r in low.requests}, {"low"})

    def test_skill_can_be_switched_off_for_ab_runs(self):
        run = self.start("--no-skill")
        self.assertIsNone(run.json("run-config.json")["skill"])
        self.assertNotIn("Scoring is mechanical", message_text(run.requests[0]["messages"][0]))

    def test_skill_content_is_general(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        for phrase in ("InitsUpdatesComm", "induct", "Strata", "simp_all in", "witness"):
            self.assertNotIn(phrase, text)


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps, *extra, **kwargs) -> FakeRun:
        run = FakeRun(steps, *extra, **kwargs)
        self.runs.append(run)
        return run

    def test_a_finished_run_writes_cost_report_and_summary(self):
        run = self.fake([{"text": "done", "usage": {"input": 500, "output": 20, "cacheRead": 0, "cacheWrite": 500}}] * 3).run()
        self.assertEqual(run.result.returncode, 0, run.result.stderr)
        summary = run.json("summary.json")
        self.assertEqual(summary["theorem"], "Core.InitsUpdatesComm")
        self.assertEqual(summary["thinking"], "high")
        self.assertGreater(summary["cost"]["requests"], 0)
        self.assertIn("cache", summary)
        self.assertTrue((run.directory / "summary.txt").read_text().startswith(run.run_id))
        self.assertIn("spent_usd", run.json("cost.json"))

    def test_merge_worker_is_off_unless_requested(self):
        off = self.fake([{"text": "done"}] * 2).run()
        self.assertFalse((off.directory / "merge-worker.json").exists())
        self.assertFalse(off.json("run-config.json")["merge_worker"])
        on = self.fake([{"text": "done"}] * 2).run("--merge-worker")
        self.assertTrue(on.json("run-config.json")["merge_worker"])
        self.assertTrue((on.directory / "merge-worker.json").exists() or (on.directory / "merge-worker.log").exists())

    def test_sigterm_mid_request_still_leaves_cost_json_and_summary(self):
        import signal

        steps = [{"text": "first", "usage": {"input": 400, "output": 10}},
                 {"text": "slow", "delay_ms": 30000}]
        run = self.fake(steps)
        process = run.start()
        self.assertTrue(run.wait_for_requests(2), "the slow request never started")
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=90)
        self.assertEqual(process.returncode, 128 + signal.SIGTERM)
        self.assertTrue((run.directory / "cost.json").exists())
        summary = run.json("summary.json")
        self.assertGreaterEqual(summary["cost"]["requests"], 1)
        self.assertTrue((run.directory / "summary.txt").exists())


def cheap_tool(name: str, arguments: dict, **usage) -> dict:
    return {"tool_calls": [{"name": name, "arguments": arguments}],
            "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100, **usage}}


SOURCE = {"path": "Strata/Languages/Core/StatementSemanticsProps.lean", "first": 950, "last": 960}


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class CacheDisciplineTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps, *extra, **kwargs) -> FakeRun:
        run = FakeRun(steps, *extra, **kwargs)
        self.runs.append(run)
        return run.run()

    def test_history_is_append_only_and_the_first_payload_has_no_dynamic_values(self):
        run = self.fake([
            cheap_tool("arena_idea", {"title": "First idea", "hypothesis": "h"}),
            cheap_tool("arena_frontier", {}),
            cheap_tool("arena_source", SOURCE),
            cheap_tool("arena_skill_read", {"path": "references/profiling-workflows.md"}),
            {"text": "done"}])
        requests = run.requests
        self.assertGreaterEqual(len(requests), 5)
        for earlier, later in zip(requests, requests[1:]):
            before = earlier["messages"]
            self.assertEqual(json.dumps(later["messages"][:len(before)]), json.dumps(before),
                             f"request {later['index']} rewrote history it had already sent")
        first = "\n".join(message_text(m) for m in requests[0]["messages"])
        for dynamic in ("remaining_usd", "Remaining ledger", "spent_usd", "usage cap", "$0.0"):
            self.assertNotIn(dynamic, first)
        self.assertIn("1 token = 0.149 pt", first)

    def test_tool_results_are_compact(self):
        run = self.fake([cheap_tool("arena_frontier", {}), cheap_tool("arena_idea", {"title": "An idea"}),
                         {"text": "done"}])
        results = [m for m in run.requests[-1]["messages"] if m["role"] == "toolResult"]
        self.assertTrue(results)
        for result in results:
            self.assertLess(len(json.dumps(result["content"])), 700)

    def test_cache_alarm_fires_when_a_warm_request_writes_more_than_it_reads(self):
        bad = {"input": 100, "output": 10, "cacheRead": 100, "cacheWrite": 5000}
        good = {"input": 100, "output": 10, "cacheRead": 5000, "cacheWrite": 100}
        alarmed = self.fake([cheap_tool("arena_frontier", {}, **bad)] * 4 + [{"text": "done", "usage": bad}])
        summary = alarmed.json("summary.json")
        self.assertGreaterEqual(summary["cache"]["alarms"], 1)
        kinds = [e["kind"] for e in alarmed.jsonl("cost-ledger.jsonl")]
        self.assertIn("cache_alarm", kinds)
        healthy = self.fake([cheap_tool("arena_frontier", {}, **good)] * 4 + [{"text": "done", "usage": good}])
        self.assertEqual(healthy.json("summary.json")["cache"]["alarms"], 0)
        self.assertGreater(healthy.json("summary.json")["cache"]["reuse_pct"], 90)

    def test_per_request_cache_tokens_and_turn_costs_are_reported(self):
        run = self.fake([cheap_tool("arena_idea", {"title": "An idea"}), cheap_tool("arena_source", SOURCE),
                         cheap_tool("arena_evaluate", {"candidate": "#7"}), {"text": "done"}])
        summary = run.json("summary.json")
        self.assertEqual(len(summary["cache"]["per_request"]), summary["cost"]["requests"])
        kinds = summary["cost"]["by_turn_type"]
        self.assertEqual(kinds["bookkeeping"]["requests"], 1)
        self.assertEqual(kinds["context"]["requests"], 1)
        self.assertEqual(kinds["rejected"]["requests"], 1)
        self.assertEqual(summary["tools"]["errors"], {"arena_evaluate": 1})


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class ErrorLoopAndContinuationTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps, *extra, **kwargs) -> FakeRun:
        run = FakeRun(steps, *extra, **kwargs)
        self.runs.append(run)
        return run.run()

    def test_consecutive_provider_errors_stop_with_error_loop_without_burning_continuations(self):
        run = self.fake([{"error": "provider is down"}] * 20, env={"ARENA_BACKOFF_MS": "10"})
        controls = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "control"]
        self.assertEqual(controls[-1]["stop"], "error_loop")
        self.assertEqual(max(e["continuations"] for e in controls), 0)
        self.assertEqual(run.json("summary.json")["stop_reason"], "error_loop")
        self.assertLess(len(run.requests), 20)

    def test_a_recovered_error_resets_the_streak_and_continuation_work_counts_normally(self):
        steps = [{"error": "blip"}, {"text": "first answer"}] + [{"text": "more"}] * 8
        run = self.fake(steps, env={"ARENA_BACKOFF_MS": "10"})
        controls = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "control"]
        self.assertNotEqual(controls[-1]["stop"], "error_loop")
        self.assertTrue(any(e["continuations"] >= 1 for e in controls))

    def test_continuation_names_the_best_candidate_and_the_models_active_ideas(self):
        from arena.engine import ROOT
        good = (ROOT / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt").read_text()
        run = self.fake([
            cheap_tool("arena_idea", {"title": "Rewrite from scratch", "hypothesis": "h"}),
            cheap_tool("arena_evaluate", {"proof": good, "idea_id": "i1"}),
            {"text": "done for now"}, {"text": "still done"}])
        later = "\n".join(message_text(m) for m in run.requests[-1]["messages"])
        self.assertIn("Continue proof optimization", later)
        self.assertIn('"candidate":"#2"', later)
        self.assertIn("i1 Rewrite from scratch", later)
        for advice in ("seed", "scheduled", "Rotate"):
            self.assertNotIn(advice, later.split("Continue proof optimization")[-1])


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class CompactionPolicyTests(unittest.TestCase):
    READS = [("references/compilation-errors.md", 0), ("references/compilation-errors.md", 24000),
             ("references/performance-optimization.md", 0), ("references/proof-golfing.md", 0),
             ("references/proof-golfing-patterns.md", 0), ("references/tactics-reference.md", 0)]

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def script(self):
        usage = {"input": 14000, "output": 50, "cacheRead": 0, "cacheWrite": 0}
        steps = [{"tool_calls": [{"name": "arena_skill_read", "arguments": {"path": path, "offset": offset}}],
                  "usage": usage} for path, offset in self.READS]
        return steps + [{"text": "done", "usage": {"input": 100, "output": 20}}] * 6

    def fake(self, *extra) -> FakeRun:
        run = FakeRun(self.script())
        self.runs.append(run)
        return run.run(*extra)

    def test_history_is_never_rewritten_below_the_configured_size(self):
        run = self.fake()
        self.assertTrue(all(r["messages"][0].get("sections") for r in run.requests))
        for earlier, later in zip(run.requests, run.requests[1:]):
            self.assertEqual(json.dumps(later["messages"][:len(earlier["messages"])]), json.dumps(earlier["messages"]))
        self.assertEqual(run.json("run-config.json")["compact_at_tokens"], 200_000)

    def test_past_the_threshold_only_the_tail_is_summarized_and_the_prefix_stays_identical(self):
        run = self.fake("--compact-at-tokens", "12000", "--compact-keep-tokens", "300")
        requests = run.requests
        summaries = [r for r in requests if not r["messages"][0].get("sections")]
        self.assertTrue(summaries, "compaction never ran")
        agent = [r for r in requests if r["messages"][0].get("sections")]
        def stable(message):  # Pi regenerates an internal timestamp that no provider receives
            return json.dumps({k: v for k, v in message.items() if k != "timestamp"})
        system = stable(agent[0]["messages"][0])
        self.assertTrue(all(stable(r["messages"][0]) == system for r in agent),
                        "compaction changed the system prompt or tool schemas")
        compacted = [r for r in agent if "compacted" in message_text(r["messages"][1])]
        self.assertTrue(compacted, "no request carried the compaction summary")
        first = compacted[0]
        self.assertNotIn("Reference proof (224 tokens)", message_text(first["messages"][1]),
                         "the summary should replace the old turns, not repeat them")
        # Pi sends summarization requests straight to the provider, so the guard's journal does not
        # see them; the session's recorded usage does, and the cost report takes the larger audit.
        ledger = sum(e["usd"] for e in run.jsonl("cost-ledger.jsonl")
                     if e["kind"] == "settle" and e.get("usage_known") is not False)
        report = run.json("cost.json")
        self.assertEqual(len([e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "settle"]), len(agent))
        self.assertGreater(report["pi_session_spend_usd"], ledger, "summarization usage must be audited")
        self.assertAlmostEqual(report["spent_usd"], max(ledger, report["pi_session_spend_usd"]), places=9)

if __name__ == "__main__":
    unittest.main()
