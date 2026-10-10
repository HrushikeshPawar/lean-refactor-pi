"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import itertools
import json
import shutil
import unittest
from datetime import UTC
from pathlib import Path

from arena import models
from arena.skill import SKILL_DIR, skill_hash
from tests.pi_support import LIVE_LANGFUSE, NAME, PI_AVAILABLE, AnthropicWire, FakeRun, message_text
from tests.slow import slow

STOP = [{"text": "done"}]


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SkillAndThinkingTests(unittest.TestCase):
    def tearDown(self):
        for run in getattr(self, "runs", []):
            run.cleanup()

    def start(self, *extra: str) -> FakeRun:
        run = FakeRun(STOP * 6)
        self.runs = [*getattr(self, "runs", []), run]
        return run.run(*extra)

    def test_skill_and_thinking_options_are_recorded_and_reach_the_provider(self):
        default = self.start()
        first = default.requests[0]["messages"][0]
        self.assertIn("Scoring is mechanical", message_text(first))
        self.assertIn("arena_skill_read", message_text(first) + str(first.get("toolsAdded")))
        config = default.json("run-config.json")
        self.assertEqual(config["skill"], {"name": "arena-lean", "sha256": skill_hash()})
        self.assertEqual(config["thinking"], "high")
        self.assertEqual({r["thinking"] for r in default.requests}, {"high"})
        low = self.start("--thinking", "low", "--no-skill")
        self.assertEqual(low.json("run-config.json")["thinking"], "low")
        self.assertEqual({r["thinking"] for r in low.requests}, {"low"})
        self.assertIsNone(low.json("run-config.json")["skill"])
        self.assertNotIn("Scoring is mechanical", message_text(low.requests[0]["messages"][0]))

    def test_skill_content_is_general(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        for phrase in ("InitsUpdatesComm", "induct", "Strata", "simp_all in", "witness"):
            self.assertNotIn(phrase, text)


@slow
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
        run = self.fake(
            [{"text": "done", "usage": {"input": 500, "output": 20, "cacheRead": 0, "cacheWrite": 500}}] * 3
        ).run()
        self.assertEqual(run.result.returncode, 0, run.result.stderr)
        summary = run.json("summary.json")
        self.assertEqual(summary["theorem"], "Core.InitsUpdatesComm")
        self.assertEqual(summary["thinking"], "high")
        self.assertGreater(summary["cost"]["requests"], 0)
        self.assertIn("cache", summary)
        self.assertTrue((run.directory / "summary.txt").read_text().startswith(run.run_id))
        self.assertIn("spent_usd", run.json("cost.json"))

    def test_the_run_stops_after_the_first_call_that_reaches_the_limit_and_never_before(self):
        # Limit $0.1. After the second call $0.09 is spent: below the limit, so a third call is made.
        # The third call's actual cost takes the total past the limit; the fourth must never be requested.
        run = self.fake(
            [
                cheap_tool("arena_state", {}),
                cheap_tool("arena_state", {}, output=SPEND_90_PCT),
                cheap_tool("arena_state", {}, output=20_000),
                {"text": "must not be requested after the limit"},
                {"text": "nor this"},
            ],
        ).run()
        self.assertEqual(len(run.requests), 3, run.result.stdout[-1500:] + run.result.stderr[-1500:])
        settles = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "settle" and row["usage_known"]]
        self.assertEqual(len(settles), 3)
        self.assertTrue(all(row["spent_usd"] < 0.1 for row in settles[:2]), settles)
        self.assertGreaterEqual(settles[2]["spent_usd"], 0.1)
        self.assertAlmostEqual(settles[2]["spent_usd"], sum(row["usd"] for row in settles))
        summary = run.json("summary.json")
        self.assertEqual(summary["stop_reason"], "limit_reached")
        cost = summary["cost"]
        self.assertEqual((cost["limit_usd"], cost["remaining_usd"]), (0.1, 0))
        self.assertAlmostEqual(cost["overshoot_usd"], settles[2]["spent_usd"] - 0.1)
        self.assertEqual(run.result.returncode, 0, run.result.stderr[-1500:])

    def test_the_finish_tool_is_offered_only_in_the_final_ten_percent(self):
        run = self.fake(
            [
                cheap_tool("arena_state", {}),
                cheap_tool("arena_state", {}, output=SPEND_90_PCT),  # leaves 9.8% of the $0.1 limit
                cheap_tool("arena_state", {}),
                {"text": "done"},
                {"text": "done"},
            ],
        ).run()
        offered = [offered_tools(request) for request in run.requests]
        self.assertGreaterEqual(len(offered), 4, run.result.stdout[-1500:])
        self.assertTrue({"arena_state", "arena_evaluate"} <= set(offered[0]))
        self.assertEqual([FINISH in tools for tools in offered[:2]], [False, False])
        self.assertEqual([FINISH in tools for tools in offered[2:]], [True] * (len(offered) - 2))

    def test_sigterm_mid_request_still_leaves_cost_json_and_summary(self):
        import signal

        steps = [{"text": "first", "usage": {"input": 400, "output": 10}}, {"text": "slow", "delay_ms": 30000}]
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


FINISH = "arena_finish"


def offered_tools(request: dict) -> list[str]:
    """The tools the model is offered in a request: Pi declares them as additions and removals in system messages."""
    tools: list[str] = []
    for message in request["messages"]:
        if message["role"] != "system":
            continue
        removed = {tool if isinstance(tool, str) else tool["name"] for tool in message.get("toolsRemoved") or []}
        tools = [name for name in tools if name not in removed] + [
            tool["name"] for tool in message.get("toolsAdded") or []
        ]
    return tools


def cheap_tool(name: str, arguments: dict, **usage) -> dict:
    return {
        "tool_calls": [{"name": name, "arguments": arguments}],
        "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100, **usage},
    }


# One scripted response whose 150K output tokens ($0.60/M) spend 90% of the $0.1 test cap.
SPEND_90_PCT = 150_000
SOURCE = {"handle": "Strata/Languages/Core/StatementSemanticsProps.lean", "first": 950, "last": 960}


@slow
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
        run = self.fake(
            [
                cheap_tool("arena_idea", {"title": "First idea", "hypothesis": "h"}),
                cheap_tool("arena_skill_read", {}),
                cheap_tool("arena_source", SOURCE),
                cheap_tool("arena_skill_read", {"path": "SKILL.md"}),
                cheap_tool("arena_evaluate", {"candidate": "#7"}),
                {"text": "done"},
            ]
        )
        requests = run.requests
        self.assertGreaterEqual(len(requests), 6)
        self.assertTrue(all(r["messages"][0].get("sections") for r in requests))
        for earlier, later in itertools.pairwise(requests):
            before = earlier["messages"]
            self.assertEqual(
                json.dumps(later["messages"][: len(before)]),
                json.dumps(before),
                f"request {later['index']} rewrote history it had already sent",
            )
        config = run.json("run-config.json")
        configured = models.load()["models"][config["model"]]["compaction"]["at_tokens"]
        self.assertEqual(config["compact_at_tokens"], configured)  # the runner hands Pi the model's own threshold
        first = "\n".join(message_text(m) for m in requests[0]["messages"])
        for dynamic in ("remaining_usd", "Remaining ledger", "spent_usd", "usage cap", "$0.0"):
            self.assertNotIn(dynamic, first)
        self.assertIn("1 token = 0.149 pt", first)
        summary = run.json("summary.json")
        self.assertEqual(len(summary["cache"]["per_request"]), summary["cost"]["requests"])
        kinds = summary["cost"]["by_turn_type"]
        self.assertEqual(kinds["bookkeeping"]["requests"], 1)
        self.assertGreaterEqual(kinds["context"]["requests"], 1)
        self.assertEqual(kinds["rejected"]["requests"], 1)
        self.assertEqual(summary["tools"]["errors"], {"arena_evaluate": 1})

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


FIXTURE = Path(__file__).resolve().parents[1] / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"


def tool_texts(request: dict, name: str | None = None) -> list[str]:
    return [
        message_text(m)
        for m in request["messages"]
        if m["role"] == "toolResult" and (name is None or m.get("toolName") == name)
    ]


@slow
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
        run = self.fake(
            [
                cheap_tool("arena_evaluate", {"proof": FIXTURE.read_text()}),
                # The provider waits while the background checker runs the other versions.
                {**cheap_tool("arena_skill_read", {}), "delay_ms": 25000},
                cheap_tool("arena_skill_read", {}),
                {"text": "done"},
            ]
        )
        requests = run.requests
        self.assertGreaterEqual(len(requests), 4, run.stdout)
        evaluated = tool_texts(requests[1], "arena_evaluate")[0]
        self.assertIn('"full_check":"queued', evaluated)
        self.assertIn("[arena] best verified: none · leading unverified: #2", evaluated)
        later = tool_texts(requests[2], "arena_skill_read")[0]
        self.assertIn("[arena] #2 passes all 3 versions: proxy 76.72 · best verified: #2 proxy 76.72", later)
        # Nothing changed afterwards, so the next result carries no status line.
        self.assertNotIn("[arena]", tool_texts(requests[3], "arena_skill_read")[-1])
        for earlier, after in itertools.pairwise(requests):
            before = earlier["messages"]
            self.assertEqual(json.dumps(after["messages"][: len(before)]), json.dumps(before))
        self.assertEqual(run.json("submission.json")["candidate"], "#2")
        self.assertEqual(run.json("summary.json")["submission"]["proxy"], 76.72)

    def test_every_arena_tool_succeeds_with_the_arguments_models_actually_send(self):
        from arena.campaign import problem

        row = problem("Core.InitsUpdatesComm")
        good = FIXTURE.read_text()
        calls = [
            ("arena_idea", {"idea_id": "structural", "title": "Restructure the induction", "region": "lines 3-9"}),
            ("arena_source", {"handle": row["file_path"], "first": 950, "last": 960}),
            ("arena_declarations", {"items": ["decl:InitStatesUpdated", "missing_helper"]}),
            ("arena_find", {"queries": ["InitStatesUpdated", "missing_helper"], "limit": 5}),
            ("arena_skill_read", {"path": "SKILL.md"}),
            (
                "arena_probe",
                {"proof": row["statement"] + " := by\n  intros Hup Hinit\n  sorry", "idea_id": "structural"},
            ),
            ("arena_evaluate", {"proof": good, "idea_id": "structural"}),
            ("arena_probe", {"proof": good + "\n  -- complete draft"}),
            ("arena_candidate", {"candidate": "p1"}),
            ("arena_profile", {"candidate": "#2", "proof": ""}),
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


ARENA_TOOLS = {
    "arena_candidate",
    "arena_declarations",
    "arena_evaluate",
    "arena_find",
    "arena_finish",
    "arena_idea",
    "arena_probe",
    "arena_profile",
    "arena_skill_read",
    "arena_source",
    "arena_state",
}
# Offered from the first request; arena_finish joins them only in the final 10% of the limit.
START_TOOLS = ARENA_TOOLS - {FINISH}
LEAN_TOOLS = {
    f"mcp__arena_lean__{name}"
    for name in ("lean_goal", "lean_diagnostic_messages", "lean_multi_attempt", "lean_local_search", "lean_hover_info")
}


def declared_tools(request: dict) -> set[str]:
    """Tool names exposed by Pi, plus names declared in any system-message sections."""
    import re

    prompt_names = set(
        re.findall(
            r'"name": "((?:mcp__|arena_)[A-Za-z0-9_]+|codemode|tool_search)"', json.dumps(request["messages"][0])
        )
    )
    exposed_names = set(request.get("tools", []))
    return prompt_names | exposed_names


class SkillToolNamesTests(unittest.TestCase):
    """The skill must not send the model to tools it does not have."""

    def test_skill_mentions_only_tools_the_model_has(self):
        import re

        available = ARENA_TOOLS | {name.removeprefix("mcp__arena_lean__") for name in LEAN_TOOLS}
        for path in sorted(SKILL_DIR.rglob("*.md")):
            named = set(re.findall(r"\b((?:lean|arena)_[a-z_]+)\b", path.read_text()))
            # Option names such as lean_options are not tools; tool names are what we guard.
            tools = {
                name
                for name in named
                if name.startswith("arena_") or name in available or name.removeprefix("lean_") in TOOL_WORDS
            }
            self.assertEqual(tools - available, set(), path.name)


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class ToolArgumentUxTests(unittest.TestCase):
    def test_malformed_arena_json_is_rejected_instead_of_running_with_empty_arguments(self):
        run = FakeRun(
            [
                {"tool_calls": [{"name": "arena_skill_read", "arguments": {}, "raw_arguments": "not-json"}]},
                {"text": "done"},
            ]
        )
        self.addCleanup(run.cleanup)
        run.run()
        self.assertEqual(run.result.returncode, 0, run.stdout[-1000:])
        results = [
            message
            for message in run.requests[-1]["messages"]
            if message.get("role") == "toolResult" and message.get("toolName") == "arena_skill_read"
        ]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["isError"])
        self.assertIn("without arguments", message_text(results[0]).lower())
        self.assertNotIn("validation", message_text(results[0]).lower())
        self.assertNotIn("No Arena skill is loaded", message_text(results[0]))

    def test_misnamed_tools_get_the_nearest_registered_name_in_the_next_provider_context(self):
        names = ["probe", "arena_declaraton", "mcp__arena_lean__lean_declaration"]
        run = FakeRun(
            [{"tool_calls": [{"name": name, "arguments": {"symbol": "Missing"}}]} for name in names]
            + [{"text": "done"}]
        )
        self.addCleanup(run.cleanup)
        run.run()
        self.assertEqual(run.result.returncode, 0, run.stdout[-1000:])
        expected = {
            "probe": "arena_probe",
            "arena_declaraton": "arena_declarations",
            "mcp__arena_lean__lean_declaration": "arena_declarations",
        }
        for name, nearest in expected.items():
            results = [
                message
                for message in run.requests[-1]["messages"]
                if message.get("role") == "toolResult" and message.get("toolName") == name
            ]
            self.assertEqual(len(results), 1, name)
            self.assertIn(f"Closest registered tool: {nearest}", message_text(results[0]), name)


TOOL_WORDS = {
    "build",
    "code_actions",
    "completions",
    "declaration_file",
    "file_outline",
    "get_widgets",
    "get_widget_source",
    "hammer_premise",
    "leanfinder",
    "leansearch",
    "loogle",
    "minimal_hypotheses",
    "profile_proof",
    "references",
    "run_code",
    "term_goal",
    "verify",
    "state_search",
    "file_contents",
    "goal",
    "diagnostic_messages",
    "multi_attempt",
    "local_search",
    "hover_info",
}


@slow
@unittest.skipUnless(
    PI_AVAILABLE and FIXTURE.exists() and shutil.which("uvx"), "pi, uvx and the Strata fixture are required"
)
class LeanMcpTests(unittest.TestCase):
    """The real lean-lsp-mcp server, driven through Pi by the scripted provider."""

    def test_only_the_declared_tools_exist_and_each_lean_tool_works_on_the_candidate_file(self):
        from arena.campaign import problem, run_dir

        run = FakeRun([], timeout=600)
        self.addCleanup(run.cleanup)
        run.command = [item for item in run.command if item != "--no-mcp"]
        path = str(run_dir(run.run_id) / "scratch" / "project" / problem("Core.InitsUpdatesComm")["file_path"])
        malformed = {
            "tool_calls": [{"name": "mcp__arena_lean__lean_goal", "arguments": {}, "raw_arguments": '{"line": '}]
        }
        unprefixed = {"tool_calls": [{"name": "lean_goal", "arguments": {}}]}
        calls = [
            ("arena_evaluate", {"proof": FIXTURE.read_text()}),
            ("mcp__arena_lean__lean_goal", {"file_path": path, "line": 960}),
            ("mcp__arena_lean__lean_diagnostic_messages", {"file_path": path, "start_line": 950, "end_line": 976}),
            ("mcp__arena_lean__lean_hover_info", {"file_path": path, "line": 953, "column": 3}),
            ("mcp__arena_lean__lean_local_search", {"query": "InitStatesUpdated"}),
            ("mcp__arena_lean__lean_multi_attempt", {"file_path": path, "line": 960, "snippets": ["skip"]}),
        ]
        run.script.write_text(
            json.dumps([malformed, unprefixed] + [cheap_tool(name, args) for name, args in calls] + [{"text": "done"}])
        )
        run.run()
        requests = run.requests
        self.assertGreaterEqual(len(requests), len(calls) + 3, run.stdout + run.result.stderr[-2000:])
        # The tool list is complete and identical from the first request: nothing appears later
        # (cache prefix), and Pi's codemode sandbox / tool_search never activate.
        for request in requests:
            self.assertEqual(declared_tools(request), START_TOOLS | LEAN_TOOLS)
        everything = [m for m in requests[-1]["messages"] if m["role"] == "toolResult"]
        results = {m["toolName"]: m for m in everything}  # the later, valid lean_goal call wins
        rejected = next(m for m in everything if m["toolName"] == "mcp__arena_lean__lean_goal")
        self.assertTrue(rejected["isError"])
        self.assertIn("object", message_text(rejected).lower())
        self.assertIn("Closest registered tool: mcp__arena_lean__lean_goal", message_text(results["lean_goal"]))
        for name, _ in calls:
            self.assertFalse(results[name].get("isError"), f"{name}: {message_text(results[name])[:300]}")
        self.assertIn("Hup", message_text(results["mcp__arena_lean__lean_goal"]))
        self.assertIn("InitStatesUpdated", message_text(results["mcp__arena_lean__lean_local_search"]))
        self.assertIn("UpdateStates", message_text(results["mcp__arena_lean__lean_hover_info"]))
        settings = json.loads((run_dir(run.run_id) / "scratch" / "project" / ".pi" / "settings.json").read_text())
        self.assertIs(settings["autoEnableCodemode"], False)
        self.assertEqual(settings["httpIdleTimeoutMs"], 120_000)
        self.assertEqual(settings["retry"]["provider"]["timeoutMs"], 120_000)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class AnthropicWireTests(unittest.TestCase):
    """The model through Pi's real Anthropic Messages client: what the provider receives is what Pi built."""

    def run_wire(self, thinking: str, replies: list[dict]) -> tuple[FakeRun, AnthropicWire]:
        wire = AnthropicWire(replies)
        self.addCleanup(wire.close)
        run = FakeRun([], "--thinking", thinking, model="deepseek-v4.1-flash", env={"ARENA_FAKE_WIRE_URL": wire.url})
        self.addCleanup(run.cleanup)
        return run.run(), wire

    def test_every_thinking_level_produces_payloads_the_api_accepts(self):
        for thinking in ("low", "medium", "high"):
            with self.subTest(thinking=thinking):
                run, wire = self.run_wire(
                    thinking, [{"tool": "arena_idea", "input": {"title": "An idea"}}, {"text": "done"}]
                )
                self.assertEqual(wire.rejections, [], run.stdout[-800:])
                self.assertGreaterEqual(len(wire.payloads), 2)
                for payload in wire.payloads:
                    self.assertLessEqual(payload["max_tokens"], 64_000)
                    if payload.get("thinking", {}).get("type") == "enabled":
                        self.assertLess(payload["thinking"]["budget_tokens"], payload["max_tokens"])
                self.assertNotEqual(run.json("summary.json")["stop_reason"], "error_loop")
                self.assertEqual(run.json("summary.json")["tools"]["error_total"], 0)
                self.assertEqual(run.result.returncode, 0, run.stdout[-800:])

    def test_every_arena_tool_schema_is_a_top_level_object(self):
        run, wire = self.run_wire("low", [{"text": "done"}])
        self.assertEqual(wire.rejections, [], run.stdout[-800:])
        tools = {
            tool["name"]: tool["input_schema"]
            for tool in wire.payloads[0]["tools"]
            if tool["name"].startswith("arena_")
        }
        self.assertTrue(set(tools) >= START_TOOLS, set(tools))
        for name, schema in tools.items():
            with self.subTest(tool=name):
                self.assertEqual(schema["type"], "object")
                self.assertFalse({"anyOf", "oneOf", "allOf"} & set(schema))
        self.assertEqual(set(tools["arena_declarations"]["properties"]), {"items", "cursor"})
        self.assertFalse(tools["arena_declarations"].get("required"))

    def test_wire_bytes_retries_and_langfuse_keep_the_post_hook_request(self):
        import hashlib
        from datetime import datetime

        from arena.traces import judge

        pad = "P" * 20001
        text = "Z" * 20001
        wire = AnthropicWire(
            [{"tool": "arena_trace_pad", "input": {}}, {"text": text, "redacted": "opaque-signature-1"}], fail_first=1
        )
        self.addCleanup(wire.close)
        started = datetime.now(UTC)
        run = FakeRun(
            [],
            "--thinking",
            "high",
            model="deepseek-v4.1-flash",
            timeout=300,
            langfuse=LIVE_LANGFUSE,
            env={"ARENA_FAKE_WIRE_URL": wire.url, "ARENA_TRACE_PAD": "20001"},
        )
        self.addCleanup(run.cleanup)
        run.run()
        journal = run.jsonl("trace-journal.jsonl")
        requests = [row for row in journal if row["kind"] == "request"]
        wires = [row for row in journal if row["kind"] == "wire"]
        responses = [row for row in journal if row["kind"] == "response"]
        detail = (
            f"session={run.run_id} exit={run.result.returncode} "
            f"wires={len(wires)} raw={len(wire.raw_bodies)} requests={len(requests)} "
            f"wire_sha={[hashlib.sha256(body).hexdigest()[:12] for body in wire.raw_bodies]}"
        )
        self.assertEqual(run.result.returncode, 0, detail + "\n" + run.stdout[-500:])
        self.assertEqual(wires, [], detail)
        self.assertEqual(wire.raw_bodies[0], wire.raw_bodies[1], detail)
        self.assertEqual(
            [row["post_hook"]["model"] for row in requests], ["deepseek-v4.1-flash"] * len(requests), detail
        )
        self.assertIn(200, [row["status"] for row in journal if row["kind"] == "http_response"], detail)
        self.assertGreater(sum(row.get("retry_of") is not None for row in requests), 0, detail)
        self.assertIsNone(requests[0]["retry_of"], detail)
        self.assertEqual(requests[1]["retry_of"], requests[0]["id"], detail)
        probe = run.directory / ".mode-probe"
        probe.write_bytes(b"x")
        probe.chmod(0o600)
        if (probe.stat().st_mode & 0o777) == 0o600:
            self.assertEqual((run.directory / "trace-journal.jsonl").stat().st_mode & 0o777, 0o600, detail)
        probe.unlink()
        self.assertTrue(
            any(
                block.get("thinkingSignature") == "opaque-signature-1" and block.get("redacted") is True
                for row in responses
                for block in row.get("content") or []
                if isinstance(block, dict)
            ),
            detail,
        )
        settles = {row["id"]: row["usd"] for row in run.jsonl("cost-ledger.jsonl") if row["kind"] == "settle"}
        for row in responses:
            if row.get("settled_usd") is not None:
                self.assertAlmostEqual(row["settled_usd"], settles[row["id"]], msg=detail)
        journal_text = (run.directory / "trace-journal.jsonl").read_text().lower()
        for marker in ("offline-test", "x-api-key", "authorization"):
            self.assertNotIn(marker, journal_text, f"trace journal contains {marker}; {detail}")
        if not LIVE_LANGFUSE:
            return

        observations = _wait_for_trace(run.run_id, started, pad, text)
        generations = [row for row in observations if row.get("name") == "LLM Call"]
        detail += (
            f" generations={len(generations)} tools={sum(row.get('type') == 'TOOL' for row in observations)} "
            f"traces={sorted({row.get('traceId') for row in observations})}"
        )
        for marker in ("offline-test", "x-api-key", "authorization"):
            for generation in generations:
                self.assertNotIn(
                    marker, str(generation.get("input") or "").lower(), f"Langfuse input contains {marker}; {detail}"
                )
        for generation in generations:
            output = generation.get("output")
            self.assertNotIn("opaque-signature-1", str(output), detail)
            parsed = json.loads(output) if isinstance(output, str) else output
            if isinstance(parsed, dict):
                self.assertTrue(set(parsed) <= {"role", "content", "tool_calls"}, detail)
        self.assertIn(
            pad, "".join(str(row.get("output") or "") for row in observations if row.get("type") == "TOOL"), detail
        )
        self.assertIn(text, "".join(str(row.get("output") or "") for row in generations), detail)
        self.assertEqual(judge(journal, observations), [], detail)


def _wait_for_trace(session_id: str, started, pad: str, text: str) -> list[dict]:
    import time

    from arena.traces import list_observations

    deadline = time.monotonic() + 30
    rows: list[dict] = []
    while time.monotonic() < deadline:
        try:
            rows = list_observations(session_id, started)
        except RuntimeError:
            time.sleep(2)
            continue
        outputs = "".join(str(row.get("output") or "") for row in rows)
        if pad in outputs and text in outputs:
            return rows
        time.sleep(2)
    return rows


@slow
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
        billed = {"input": 10, "output": 1}
        run = self.fake([{"error": "model failed", "usage": billed}] * 20, env={"ARENA_BACKOFF_MS": "10"})
        controls = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "control"]
        self.assertEqual(controls[-1]["stop"], "error_loop")
        self.assertEqual(controls[-1]["failure"], "model")
        self.assertEqual(max(e["continuations"] for e in controls), 0)
        self.assertEqual(run.json("summary.json")["stop_reason"], "error_loop")
        self.assertLess(len(run.requests), 20)

    def test_a_recovered_error_resets_the_streak_and_continuation_work_counts_normally(self):
        steps = [{"error": "blip", "usage": {"input": 10, "output": 1}}, {"text": "first answer"}] + [
            {"text": "more"}
        ] * 8
        run = self.fake(steps, env={"ARENA_BACKOFF_MS": "10"})
        controls = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "control"]
        self.assertNotEqual(controls[-1]["stop"], "error_loop")
        self.assertTrue(any(e["continuations"] >= 1 for e in controls))

    def test_continuation_names_the_best_candidate_and_the_models_active_ideas(self):
        from arena.engine import ROOT

        good = (ROOT / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt").read_text()
        run = self.fake(
            [
                cheap_tool("arena_idea", {"title": "Rewrite from scratch", "hypothesis": "h"}),
                cheap_tool("arena_evaluate", {"proof": good, "idea_id": "i1"}),
                {"text": "done for now"},
                {"text": "still done"},
            ]
        )
        later = "\n".join(message_text(m) for m in run.requests[-1]["messages"])
        # More than 10% of the cap is left, so a plain final answer is pushed back to work. The push states
        # only what the harness credits (ROUTE_RULE); it never suggests which strategy to try.
        self.assertIn("Do not stop", later)
        self.assertIn("fingerprints each attempt's compiled proof term", later)
        self.assertNotIn("structurally new idea", later)
        self.assertIn("no value", later)
        self.assertIn('"candidate":"#2"', later)
        self.assertIn("i1 Rewrite from scratch", later)
        for advice in ("seed", "scheduled", "Rotate"):
            self.assertNotIn(advice, later.split("Do not stop")[-1])

    def test_continuation_inside_the_final_ten_percent_is_the_plain_prompt(self):
        run = self.fake(
            [cheap_tool("arena_state", {}, output=SPEND_90_PCT), {"text": "done"}, {"text": "still done"}],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        later = "\n".join(message_text(m) for m in run.requests[-1]["messages"])
        self.assertIn("Continue proof optimization", later)
        self.assertNotIn("Do not stop", later)

    def test_state_finish_review_and_confirmation_stop_provider_continuations(self):
        run = self.fake(
            [
                cheap_tool("arena_state", {}, output=SPEND_90_PCT),  # 10% or less of the $0.1 cap remains
                cheap_tool("arena_finish", {}),
                cheap_tool("arena_finish", {}),
                {"text": "must not be requested"},
            ],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        self.assertEqual(len(run.requests), 3, run.stdout)
        state_text = tool_texts(run.requests[1], "arena_state")[0]
        self.assertIn('"best_verified"', state_text)
        self.assertNotIn('"hypothesis"', state_text)
        review = tool_texts(run.requests[2], "arena_finish")[0]
        self.assertIn('"phase":"review"', review)
        facts = json.loads(review.splitlines()[0])
        self.assertTrue({"remaining_usd", "used_pct", "best_verified", "routes_tried"} <= set(facts))
        self.assertNotIn("baseline", facts)
        self.assertIn("% of the $", facts["next"])
        self.assertIn("final 10%", facts["next"])
        self.assertNotIn("refused", facts)
        confirmation = next(
            row["text"]
            for row in run.jsonl("trace-journal.jsonl")
            if row.get("kind") == "tool_result"
            and row.get("name") == "arena_finish"
            and '"phase":"confirmed"' in row.get("text", "")
        )
        self.assertIn('"phase":"confirmed"', confirmation)
        self.assertEqual(run.json("summary.json")["stop_reason"], "finished")
        self.assertEqual(
            len(
                [
                    row
                    for row in run.jsonl("cost-ledger.jsonl")
                    if row.get("kind") == "control" and row.get("stop") == "finished"
                ]
            ),
            1,
        )

    def test_search_first_discovery_is_not_stalled_and_identical_reads_cannot_extend_run(self):
        reads = [
            cheap_tool("arena_source", {"handle": SOURCE["handle"], "first": line, "last": line})
            for line in range(950, 969)
        ]
        repeated = cheap_tool("arena_source", {"handle": SOURCE["handle"], "first": 950, "last": 950})
        run = self.fake(
            [
                *reads,
                {"text": "first final"},
                repeated,
                {"text": "second final"},
                repeated,
                {"text": "third final"},
                {"text": "must not be requested"},
            ],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual(controls[-1]["stop"], "no_work_fallback")
        self.assertEqual(controls[-1]["no_work_turns"], 2)
        self.assertFalse(any(row.get("stop") == "no_work_fallback" for row in controls[:-1]))
        self.assertEqual(len(run.requests), len(reads) + 5)

    def test_search_first_replay_allows_nineteen_source_requests_before_fallback(self):
        reads = [
            {"tool": "arena_source", "input": {"handle": SOURCE["handle"], "first": line, "last": line}}
            for line in range(950, 969)
        ]
        repeated = {"tool": "arena_source", "input": {"handle": SOURCE["handle"], "first": 950, "last": 950}}
        wire = AnthropicWire(
            [
                *reads,
                {"text": "first final"},
                repeated,
                {"text": "second final"},
                repeated,
                {"text": "third final"},
                {"text": "must not be requested"},
            ]
        )
        self.addCleanup(wire.close)
        run = FakeRun([], "--thinking", "low", model="deepseek-v4.1-flash", env={"ARENA_FAKE_WIRE_URL": wire.url})
        self.runs.append(run)
        run.run()
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-2000:])
        self.assertEqual(controls[-1]["stop"], "no_work_fallback")
        self.assertEqual(controls[-1]["no_work_turns"], 2)
        self.assertFalse(any(row.get("stop") == "no_work_fallback" for row in controls[:-1]))
        self.assertEqual(len(wire.payloads), len(reads) + 5)
        self.assertEqual({payload["model"] for payload in wire.payloads}, {"deepseek-v4.1-flash"})

    def test_failed_skeleton_is_an_attempt_and_does_not_remind_or_abandon_idea(self):
        from arena.campaign import problem

        row = problem("Core.InitsUpdatesComm")
        run = self.fake(
            [
                cheap_tool("arena_idea", {"title": "Restructure the induction"}),
                cheap_tool("arena_probe", {"proof": row["statement"] + " := by\n  sorry"}, output=SPEND_90_PCT),
                cheap_tool("arena_finish", {}),
                cheap_tool("arena_finish", {}),
            ]
        )
        review = next(
            json.loads(row["text"].splitlines()[0])
            for row in run.jsonl("trace-journal.jsonl")
            if row.get("kind") == "tool_result"
            and row.get("name") == "arena_finish"
            and '"phase":"review"' in row.get("text", "")
        )
        self.assertNotIn("reminder", review)
        self.assertEqual([row for row in run.jsonl("ledger.jsonl") if row.get("kind") == "idea_update"], [])

    def test_declaring_a_new_idea_closes_the_previous_one_from_known_outcomes(self):
        from arena.campaign import problem

        row = problem("Core.InitsUpdatesComm")
        run = self.fake(
            [
                cheap_tool("arena_idea", {"title": "First route"}),
                cheap_tool("arena_probe", {"proof": row["statement"] + " := by\n  sorry"}),
                cheap_tool("arena_idea", {"title": "Second route"}),
                cheap_tool("arena_idea", {"title": "Third route"}),
            ]
        )
        replies = [
            json.loads(item["text"].splitlines()[0])
            for item in run.jsonl("trace-journal.jsonl")
            if item.get("kind") == "tool_result" and item.get("name") == "arena_idea"
        ]
        self.assertEqual([reply["id"] for reply in replies], ["i1", "i2", "i3"])
        self.assertNotIn("hypothesis", replies[0])
        self.assertEqual(replies[1]["closed"], ["i1 abandoned"])  # one attempt, no best candidate
        self.assertEqual(replies[2]["closed"], ["i2 parked"])  # nothing attempted
        updates = {item["id"]: item for item in run.jsonl("ledger.jsonl") if item.get("kind") == "idea_update"}
        self.assertIn("superseded by i2", updates["i1"]["reason"])
        self.assertEqual(updates["i2"]["status"], "parked")

    def test_batch_probe_turns_count_as_proof_attempts(self):
        from arena.campaign import problem

        statement = problem(NAME)["statement"]
        turns = []
        for index in range(3):
            drafts = [statement + f" := by\n  {'skip; ' * (index * 2 + k)}sorry" for k in range(2)]
            turns += [cheap_tool("arena_probe", {"drafts": drafts}), {"text": f"final {index}"}]
        run = self.fake(turns, env={"ARENA_AUTOCONTINUE": "1"})
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertTrue(controls, run.stdout)
        self.assertTrue(all(row["proof_attempt"] for row in controls[:3]), controls)
        self.assertFalse(any(row.get("stop") == "no_work_fallback" for row in controls[:3]), controls)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class OutageTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def run_fake(self, steps, env):
        run = FakeRun(steps, env=env, timeout=900).run()
        self.runs.append(run)
        return run

    def test_transport_outage_stops_at_wall_clock_limit_and_reports_error(self):
        run = self.run_fake(
            [{"error": "gateway offline"}] * 25,
            {
                "ARENA_BACKOFF_MS": "10",
                "ARENA_RETRY_BASE_MS": "10",
                "ARENA_OUTAGE_LIMIT_MS": "300",
            },
        )
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual(controls[-1]["stop"], "provider_unreachable")
        self.assertEqual(run.json("summary.json")["stop_reason"], "provider_unreachable")
        self.assertTrue(any(row.get("error_message") == "gateway offline" for row in controls))
        self.assertEqual([row.get("stop") for row in controls].count("error_loop"), 0)

    def test_recovered_transport_errors_do_not_end_the_run(self):
        run = self.run_fake(
            [{"error": "brief outage"}] * 5 + [{"text": "recovered"}] + [{"text": "more"}] * 8,
            {
                "ARENA_BACKOFF_MS": "10",
                "ARENA_RETRY_BASE_MS": "10",
                "ARENA_OUTAGE_LIMIT_MS": "10000",
            },
        )
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertNotEqual(controls[-1].get("stop"), "provider_unreachable")
        self.assertTrue(any(row.get("continuations", 0) > 0 for row in controls))
        self.assertTrue(any(row.get("failure") == "transport" for row in controls))

    def test_billed_model_failures_reach_error_loop_after_three_failed_turns(self):
        run = self.run_fake(
            [{"error": "model failed", "usage": {"input": 10, "output": 1}}] * 20,
            {
                "ARENA_BACKOFF_MS": "10",
                "ARENA_RETRY_BASE_MS": "10",
                "ARENA_OUTAGE_LIMIT_MS": "10000",
            },
        )
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual(controls[-1]["stop"], "error_loop")
        self.assertEqual(controls[-1]["error_streak"], 3)
        self.assertEqual(max(row.get("continuations", 0) for row in controls), 0)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class TruncationTests(unittest.TestCase):
    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def test_cut_turn_is_kept_without_compaction_and_the_next_message_names_the_cut(self):
        ceiling = models.load()["models"]["deepseek-v4.1-flash"]["request_output_tokens"]
        run = FakeRun(
            [
                {"text": "reasoning before the cut", "stop_reason": "length", "usage": {"output": ceiling}},
                {"text": "done"},
            ],
            timeout=900,
        )
        self.runs.append(run)
        run.run()
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-2000:])
        self.assertFalse(any(not request["messages"][0].get("sections") for request in run.requests))
        later = run.requests[1]
        transcript = "\n".join(message_text(message) for message in later["messages"])
        self.assertIn("reasoning before the cut", transcript)
        self.assertIn(f"The previous turn was cut at {ceiling} tokens.", transcript)

    def test_cut_turn_tool_errors_also_name_the_cut(self):
        ceiling = models.load()["models"]["deepseek-v4.1-flash"]["request_output_tokens"]
        run = FakeRun(
            [
                {
                    "text": "reasoning before the cut",
                    "tool_calls": [{"name": "arena_state", "arguments": {}}],
                    "stop_reason": "length",
                    "usage": {"output": ceiling},
                },
                {"text": "done"},
            ],
            timeout=900,
        )
        self.runs.append(run)
        run.run()
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-2000:])
        later = "\n".join(message_text(message) for message in run.requests[1]["messages"])
        self.assertIn(f"The previous turn was cut at {ceiling} tokens.", later)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class FinishReplayTests(unittest.TestCase):
    FIXTURES = Path(__file__).resolve().parent / "fixtures/arena_finish_replays"

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def test_historical_first_finals_keep_later_verified_candidates(self):
        replays = [
            (
                "v5 r2",
                "Core.InitsUpdatesComm",
                "deepseek-v4.1-flash",
                "model-a-first.lean",
                "model-a-later.lean",
                (155, 361, 74.11),
            ),
            (
                "v5 CSLib",
                "Cslib.CCS.bisimilarity_congr_choice",
                "deepseek-v4.1-flash",
                "model-b-first.lean",
                "model-b-later.lean",
                (139, 358, 78.45),
            ),
        ]
        for label, theorem, model, first, later, expected in replays:
            with self.subTest(replay=label):
                run = FakeRun(
                    [
                        cheap_tool(
                            "arena_evaluate", {"proof": (self.FIXTURES / first).read_text()}, output=SPEND_90_PCT
                        ),
                        cheap_tool("arena_finish", {}),
                        cheap_tool("arena_evaluate", {"proof": (self.FIXTURES / later).read_text()}),
                        cheap_tool("arena_finish", {}),
                    ],
                    theorem=theorem,
                    model=model,
                    session=True,
                    timeout=1200,
                )
                self.runs.append(run)
                run.run()
                self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-2000:])
                submission = run.json("submission.json")
                self.assertEqual(submission["candidate"], "#3", run.stdout)
                self.assertEqual((submission["tokens"], submission["heartbeats"], submission["proxy"]), expected)
                phases = [row.get("phase") for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "finish"]
                self.assertEqual(phases.count("review"), 1)
                self.assertEqual(phases.count("confirmed"), 1)
                self.assertEqual(
                    run.json("summary.json")["progress"]["best_verified_candidate"],
                    {"candidate": "#3", "tokens": expected[0], "heartbeats": expected[1], "proxy": expected[2]},
                )


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class CompactionPolicyTests(unittest.TestCase):
    # The fake provider reports the usage that drives compaction; what each read returns does not matter.
    READS = [("SKILL.md", 0)] * 6

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def script(self):
        usage = {"input": 14000, "output": 50, "cacheRead": 0, "cacheWrite": 0}
        steps = [
            {
                "tool_calls": [{"name": "arena_skill_read", "arguments": {"path": path, "offset": offset}}],
                "usage": usage,
            }
            for path, offset in self.READS
        ]
        return steps + [{"text": "done", "usage": {"input": 100, "output": 20}}] * 6

    def fake(self, *extra) -> FakeRun:
        run = FakeRun(self.script())
        self.runs.append(run)
        return run.run(*extra)

    def test_past_the_threshold_only_the_tail_is_summarized_and_the_prefix_stays_identical(self):
        run = self.fake("--compact-at-tokens", "12000", "--compact-keep-tokens", "300")
        requests = run.requests
        summaries = [r for r in requests if not r["messages"][0].get("sections")]
        self.assertTrue(summaries, "compaction never ran")
        agent = [r for r in requests if r["messages"][0].get("sections")]

        def stable(message):  # Pi regenerates an internal timestamp that no provider receives
            return json.dumps({k: v for k, v in message.items() if k != "timestamp"})

        system = stable(agent[0]["messages"][0])
        self.assertTrue(
            all(stable(r["messages"][0]) == system for r in agent),
            "compaction changed the system prompt or tool schemas",
        )
        compacted = [r for r in agent if "compacted" in message_text(r["messages"][1])]
        self.assertTrue(compacted, "no request carried the compaction summary")
        first = compacted[0]
        self.assertNotIn(
            "Reference proof (224 tokens)",
            message_text(first["messages"][1]),
            "the summary should replace the old turns, not repeat them",
        )
        # Compaction summaries are provider requests with no agent message_end. Their cost comes from the
        # compaction entry on session_compact, one settle row per compaction, so the ledger matches Pi's session.
        settles = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "settle"]
        compactions = [e for e in settles if e.get("source") == "compaction"]
        self.assertGreaterEqual(len(compactions), 1)
        self.assertLessEqual(len(compactions), len(summaries))
        self.assertTrue(all(e["usage_known"] and e["usd"] > 0 for e in compactions))
        self.assertEqual(len(settles) - len(compactions), len(agent))
        recon = run.json("summary.json")["cost"]["reconciliation"]
        self.assertEqual(recon["gap_usd"], 0, recon)
        self.assertAlmostEqual(run.json("cost.json")["spent_usd"], sum(e["usd"] for e in settles), places=9)

    def test_a_length_stop_does_not_compact_after_the_output_ceiling(self):
        steps = [
            {
                "tool_calls": [{"name": "arena_skill_read", "arguments": {"path": path, "offset": offset}}],
                "usage": {"input": 3000, "output": 50},
            }
            for path, offset in self.READS[:2]
        ]
        steps += [
            {"text": "cut off", "stop_reason": "length", "usage": {"input": 3000, "output": 16000}},
            {"text": "done", "usage": {"input": 100, "output": 20}},
        ] + [{"text": "done"}] * 3
        run = FakeRun(steps)
        self.runs.append(run)
        run.run("--compact-keep-tokens", "300")
        requests = run.requests
        summaries = [r for r in requests if not r["messages"][0].get("sections")]
        self.assertFalse(summaries, "a cut turn at the configured output ceiling stays in history")
        events = run.jsonl("cost-ledger.jsonl")
        compactions = [e for e in events if e["kind"] == "settle" and e.get("source") == "compaction"]
        self.assertEqual(compactions, [])
        cost = run.json("summary.json")["cost"]
        self.assertEqual(cost["reconciliation"]["gap_usd"], 0, cost["reconciliation"])
        self.assertAlmostEqual(cost["spent_usd"], run.json("cost.json")["spent_usd"], places=5)
        self.assertEqual(cost["by_turn_type"].get("compaction", {}).get("requests", 0), 0)


if __name__ == "__main__":
    unittest.main()
