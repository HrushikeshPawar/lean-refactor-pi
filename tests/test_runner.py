"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import json
import shutil
from pathlib import Path
import unittest

from tests.pi_support import PI_AVAILABLE, AnthropicWire, FakeRun, message_text
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


    def test_ctrl_c_to_the_terminal_group_takes_pis_clean_shutdown(self):
        import os
        import signal

        steps = [{"text": "first", "usage": {"input": 400, "output": 10}},
                 {"text": "slow", "delay_ms": 30000}]
        run = self.fake(steps)
        process = run.start(own_group=True)
        self.assertTrue(run.wait_for_requests(2), "the slow request never started")
        os.killpg(process.pid, signal.SIGINT)
        _, stderr = process.communicate(timeout=90)
        self.assertEqual(process.returncode, 128 + signal.SIGINT, stderr)
        report = run.json("cost.json")
        self.assertNotEqual(report.get("written_by"), "runner_ledger_reconstruction", stderr)
        self.assertEqual(run.json("summary.json")["stop_reason"], "interrupted")


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
            cheap_tool("arena_skill_read", {}),
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
        run = self.fake([cheap_tool("arena_idea", {"title": "First"}), cheap_tool("arena_idea", {"title": "An idea"}),
                         {"text": "done"}])
        results = [m for m in run.requests[-1]["messages"] if m["role"] == "toolResult"]
        self.assertTrue(results)
        for result in results:
            self.assertLess(len(json.dumps(result["content"])), 700)

    def test_cache_alarm_fires_when_a_warm_request_writes_more_than_it_reads(self):
        bad = {"input": 100, "output": 10, "cacheRead": 100, "cacheWrite": 5000}
        good = {"input": 100, "output": 10, "cacheRead": 5000, "cacheWrite": 100}
        alarmed = self.fake([cheap_tool("arena_skill_read", {}, **bad)] * 4 + [{"text": "done", "usage": bad}])
        summary = alarmed.json("summary.json")
        self.assertGreaterEqual(summary["cache"]["alarms"], 1)
        kinds = [e["kind"] for e in alarmed.jsonl("cost-ledger.jsonl")]
        self.assertIn("cache_alarm", kinds)
        healthy = self.fake([cheap_tool("arena_skill_read", {}, **good)] * 4 + [{"text": "done", "usage": good}])
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


FIXTURE = Path(__file__).resolve().parents[1] / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"


def tool_texts(request: dict, name: str | None = None) -> list[str]:
    return [message_text(m) for m in request["messages"]
            if m["role"] == "toolResult" and (name is None or m.get("toolName") == name)]


@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class AutomaticChecksTests(unittest.TestCase):
    """The harness checks every version and keeps the model informed without being asked."""

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps) -> FakeRun:
        run = FakeRun(steps)
        self.runs.append(run)
        return run.run()

    def test_background_result_arrives_on_the_next_tool_result_without_rewriting_history(self):
        run = self.fake([
            cheap_tool("arena_evaluate", {"proof": FIXTURE.read_text()}),
            # The provider waits while the background checker runs the other versions.
            {**cheap_tool("arena_skill_read", {}), "delay_ms": 25000},
            cheap_tool("arena_skill_read", {}),
            {"text": "done"}])
        requests = run.requests
        self.assertGreaterEqual(len(requests), 4, run.stdout)
        evaluated = tool_texts(requests[1], "arena_evaluate")[0]
        self.assertIn('"full_check":"queued', evaluated)
        self.assertIn("[arena] best verified: none · leading unverified: #2", evaluated)
        later = tool_texts(requests[2], "arena_skill_read")[0]
        self.assertIn("[arena] #2 passes all 3 versions: proxy 76.72 · best verified: #2 proxy 76.72", later)
        # Nothing changed afterwards, so the next result carries no status line.
        self.assertNotIn("[arena]", tool_texts(requests[3], "arena_skill_read")[-1])
        for earlier, after in zip(requests, requests[1:]):
            before = earlier["messages"]
            self.assertEqual(json.dumps(after["messages"][:len(before)]), json.dumps(before))
        self.assertEqual(run.json("submission.json")["candidate"], "#2")
        self.assertEqual(run.json("summary.json")["submission"]["proxy"], 76.72)

    def test_every_arena_tool_succeeds_with_the_arguments_models_actually_send(self):
        from arena.campaign import problem
        row = problem("Core.InitsUpdatesComm")
        good = FIXTURE.read_text()
        calls = [
            ("arena_idea", {"idea_id": "structural", "title": "Restructure the induction", "region": "lines 3-9"}),
            ("arena_source", {"path": row["file_path"], "first": 950, "last": 960}),
            ("arena_declaration", {"symbol": "InitStatesUpdated"}),
            ("arena_skill_read", {"path": "references/lean-lsp-server.md"}),
            ("arena_probe", {"proof": row["statement"] + " := by\n  intros Hup Hinit\n  sorry", "idea_id": "structural"}),
            ("arena_evaluate", {"proof": good, "idea_id": "structural"}),
            ("arena_probe", {"proof": good + "\n  -- complete draft"}),
            ("arena_candidate", {"candidate": "p1"}),
            ("arena_profile", {"candidate": "#2", "proof": ""}),
            ("arena_polish", {"candidate": "#2"}),
            ("arena_idea", {"idea_id": "structural", "status": "succeeded", "reason": "compiles everywhere"}),
        ]
        run = FakeRun([cheap_tool(name, args) for name, args in calls] + [{"text": "done"}], timeout=900)
        self.runs.append(run)
        run.run()
        summary = run.json("summary.json")
        self.assertEqual(summary["tools"]["errors"], {}, run.stdout[-1500:])
        self.assertEqual(sum(summary["tools"]["calls"].values()), len(calls))
        self.assertEqual(set(summary["tools"]["calls"]), {name for name, _ in calls})
        self.assertEqual(run.json("submission.json")["candidate"] is not None, True)

    def test_checks_queued_when_the_model_stops_are_finished_before_submitting(self):
        run = self.fake([cheap_tool("arena_evaluate", {"proof": FIXTURE.read_text()}), {"text": "done"}])
        self.assertEqual(run.json("submission.json")["candidate"], "#2", run.stdout)
        self.assertIn("Submission: #2 proxy 76.72", run.stdout)


ARENA_TOOLS = {"arena_candidate", "arena_declaration", "arena_evaluate", "arena_idea", "arena_polish",
               "arena_probe", "arena_profile", "arena_skill_read", "arena_source"}
LEAN_TOOLS = {f"mcp__arena_lean__{name}" for name in
              ("lean_goal", "lean_diagnostic_messages", "lean_multi_attempt", "lean_local_search", "lean_hover_info")}


def declared_tools(request: dict) -> set[str]:
    """Tool names declared in a request; Pi carries declarations in the system message sections."""
    import re
    return set(re.findall(r'"name": "((?:mcp__|arena_)[A-Za-z0-9_]+|codemode|tool_search)"', json.dumps(request["messages"][0])))


class SkillToolNamesTests(unittest.TestCase):
    """The skill must not send the model to tools it does not have."""

    def test_skill_mentions_only_tools_the_model_has(self):
        import re
        available = ARENA_TOOLS | {name.removeprefix("mcp__arena_lean__") for name in LEAN_TOOLS}
        for path in sorted(SKILL_DIR.rglob("*.md")):
            if path.name == "PROVENANCE.md":
                continue
            named = set(re.findall(r"\b((?:lean|arena)_[a-z_]+)\b", path.read_text()))
            # Option names such as lean_options are not tools; tool names are what we guard.
            tools = {name for name in named if name.startswith("arena_") or name in available
                     or name.removeprefix("lean_") in TOOL_WORDS}
            self.assertEqual(tools - available, set(), path.name)


TOOL_WORDS = {"build", "code_actions", "completions", "declaration_file", "file_outline", "get_widgets",
              "get_widget_source", "hammer_premise", "leanfinder", "leansearch", "loogle", "minimal_hypotheses",
              "profile_proof", "references", "run_code", "term_goal", "verify", "state_search", "file_contents",
              "goal", "diagnostic_messages", "multi_attempt", "local_search", "hover_info"}


@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists() and shutil.which("uvx"), "pi, uvx and the Strata fixture are required")
class LeanMcpTests(unittest.TestCase):
    """The real lean-lsp-mcp server, driven through Pi by the scripted provider."""

    def test_only_the_declared_tools_exist_and_each_lean_tool_works_on_the_candidate_file(self):
        from arena.campaign import problem, run_dir
        run = FakeRun([], timeout=600)
        self.addCleanup(run.cleanup)
        run.command = [item for item in run.command if item != "--no-mcp"]
        path = str(run_dir(run.run_id) / "scratch" / "project" / problem("Core.InitsUpdatesComm")["file_path"])
        calls = [("arena_evaluate", {"proof": FIXTURE.read_text()}),
                 ("mcp__arena_lean__lean_goal", {"file_path": path, "line": 960}),
                 ("mcp__arena_lean__lean_diagnostic_messages", {"file_path": path, "start_line": 950, "end_line": 976}),
                 ("mcp__arena_lean__lean_hover_info", {"file_path": path, "line": 953, "column": 3}),
                 ("mcp__arena_lean__lean_local_search", {"query": "InitStatesUpdated"}),
                 ("mcp__arena_lean__lean_multi_attempt", {"file_path": path, "line": 960, "snippets": ["skip"]})]
        run.script.write_text(json.dumps([cheap_tool(name, args) for name, args in calls] + [{"text": "done"}]))
        run.run()
        requests = run.requests
        self.assertGreaterEqual(len(requests), len(calls) + 1, run.stdout + run.result.stderr[-2000:])
        # The tool list is complete and identical from the first request: nothing appears later
        # (cache prefix), and Pi's codemode sandbox / tool_search never activate.
        for request in requests:
            self.assertEqual(declared_tools(request), ARENA_TOOLS | LEAN_TOOLS)
        results = {m["toolName"]: m for m in requests[-1]["messages"] if m["role"] == "toolResult"}
        for name, _ in calls:
            self.assertFalse(results[name].get("isError"), f"{name}: {message_text(results[name])[:300]}")
        self.assertIn("Hup", message_text(results["mcp__arena_lean__lean_goal"]))
        self.assertIn("InitStatesUpdated", message_text(results["mcp__arena_lean__lean_local_search"]))
        self.assertIn("UpdateStates", message_text(results["mcp__arena_lean__lean_hover_info"]))
        settings = json.loads((run_dir(run.run_id) / "scratch" / "project" / ".pi" / "settings.json").read_text())
        self.assertIs(settings["autoEnableCodemode"], False)


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class AnthropicWireTests(unittest.TestCase):
    """Qwen through Pi's real Anthropic Messages client: what the provider receives is what Pi built."""

    def run_qwen(self, thinking: str, replies: list[dict]) -> tuple[FakeRun, AnthropicWire]:
        wire = AnthropicWire(replies)
        self.addCleanup(wire.close)
        run = FakeRun([], "--thinking", thinking, model="qwen3.8-flash", env={"ARENA_FAKE_WIRE_URL": wire.url})
        self.addCleanup(run.cleanup)
        return run.run(), wire

    def test_every_thinking_level_produces_payloads_the_api_accepts(self):
        for thinking in ("low", "medium", "high"):
            with self.subTest(thinking=thinking):
                run, wire = self.run_qwen(thinking, [{"tool": "arena_idea", "input": {"title": "An idea"}},
                                                     {"text": "done"}])
                self.assertEqual(wire.rejections, [], run.stdout[-800:])
                self.assertGreaterEqual(len(wire.payloads), 2)
                for payload in wire.payloads:
                    self.assertLessEqual(payload["max_tokens"], 16_000)
                    if payload.get("thinking", {}).get("type") == "enabled":
                        self.assertLess(payload["thinking"]["budget_tokens"], payload["max_tokens"])
                self.assertNotEqual(run.json("summary.json")["stop_reason"], "error_loop")
                self.assertEqual(run.json("summary.json")["tools"]["error_total"], 0)
                self.assertEqual(run.result.returncode, 0, run.stdout[-800:])


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
