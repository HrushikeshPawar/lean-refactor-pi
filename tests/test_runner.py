"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import itertools
import json
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
        self.assertIn("compile", offered_tools(default.requests[0]))
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
        assert run.result is not None
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
                cheap_tool("read", {"node": "n1"}),
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                cheap_tool("read", {"node": "n1"}, output=20_000),
                {"text": "must not be requested after the limit"},
                {"text": "nor this"},
            ],
        ).run()
        self.assertEqual(len(run.requests), 3, run.stdout[-1500:])
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
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.result.stderr[-1500:])

    def test_the_finish_tool_is_offered_only_in_the_final_ten_percent(self):
        run = self.fake(
            [
                cheap_tool("read", {"node": "n1"}),
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),  # leaves 9.8% of the $0.1 limit
                cheap_tool("read", {"node": "n1"}),
                {"text": "done"},
                {"text": "done"},
            ],
        ).run()
        offered = [offered_tools(request) for request in run.requests]
        self.assertGreaterEqual(len(offered), 4, run.stdout[-1500:])
        self.assertTrue({"compile", "goal", "search", "read"} <= set(offered[0]))
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


FINISH = "finish"


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
                cheap_tool("read", {"node": "n1"}),
                cheap_tool("read", {"view": "map"}),
                cheap_tool("search", {"queries": ["InitsUpdatesComm"], "kind": "name"}),
                cheap_tool("read", {"node": "n1"}),
                cheap_tool("compile", {"drafts": []}),
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
        self.assertEqual(summary["tools"]["errors"], {"compile": 1})

    def test_cache_alarm_fires_when_a_warm_request_writes_more_than_it_reads(self):
        bad = {"input": 100, "output": 10, "cacheRead": 100, "cacheWrite": 5000}
        good = {"input": 100, "output": 10, "cacheRead": 5000, "cacheWrite": 100}
        alarmed = self.fake([cheap_tool("read", {"node": "n1"}, **bad)] * 4 + [{"text": "done", "usage": bad}])
        summary = alarmed.json("summary.json")
        self.assertGreaterEqual(summary["cache"]["alarms"], 1)
        kinds = [e["kind"] for e in alarmed.jsonl("cost-ledger.jsonl")]
        self.assertIn("cache_alarm", kinds)
        healthy = self.fake([cheap_tool("read", {"node": "n1"}, **good)] * 4 + [{"text": "done", "usage": good}])
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
    """The compile action checks drafts and exposes measured results."""

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps):
        run = FakeRun(steps)
        self.runs.append(run)
        return run.run()

    def test_background_result_arrives_on_a_later_tool_result_without_rewriting_history(self):
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}),
                {**cheap_tool("read", {"node": "n1"}), "delay_ms": 25000},
                cheap_tool("read", {"node": "n1"}),
                {"text": "done"},
            ]
        )
        requests = run.requests
        self.assertGreaterEqual(len(requests), 4, run.stdout)
        compiled = tool_texts(requests[1], "compile")[0]
        self.assertIn("passes all 3 versions", compiled.lower())
        self.assertIn("n2 filed as new root", compiled.lower())
        later = tool_texts(requests[2], "read")[0]
        self.assertNotIn("[arena]", compiled + later)
        for earlier, after in itertools.pairwise(requests):
            before = earlier["messages"]
            self.assertEqual(json.dumps(after["messages"][: len(before)]), json.dumps(before))
        self.assertIsNotNone(run.json("submission.json").get("candidate"))

    def test_each_registered_tool_accepts_its_public_argument_shape(self):
        calls = [
            ("compile", {"drafts": [FIXTURE.read_text()], "check": "tokens"}),
            ("goal", {"node": "n1", "line": 1}),
            ("search", {"queries": ["InitsUpdatesComm"], "kind": "name"}),
            ("read", {"node": "n1"}),
        ]
        steps = [cheap_tool(name, args) for name, args in calls]
        steps += [cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT), cheap_tool("finish", {})]
        run = self.fake(steps)
        summary = run.json("summary.json")
        self.assertEqual(summary["tools"]["errors"], {}, run.stdout[-1500:])
        self.assertTrue({name for name, _ in [*calls, ("finish", {})]} <= set(summary["tools"]["calls"]))
        self.assertEqual(summary["stop_reason"], "finished")
        self.assertEqual(len(run.requests), len(steps))

    def test_checks_queued_when_the_model_stops_are_finished_before_submitting(self):
        run = self.fake([cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}), {"text": "done"}])
        self.assertIsNotNone(run.json("submission.json").get("candidate"), run.stdout)
        self.assertIn("Submission:", run.stdout)


ARENA_TOOLS = {"compile", "goal", "search", "read", "finish"}
START_TOOLS = ARENA_TOOLS - {FINISH}


def declared_tools(request: dict) -> set[str]:
    import re

    names = set(re.findall(r'"name": "([a-z_]+)"', json.dumps(request["messages"][0])))
    return names | set(request.get("tools", []))


class SkillToolNamesTests(unittest.TestCase):
    def test_skill_mentions_only_the_five_tools(self):
        import re

        text = "\n".join(path.read_text() for path in sorted(SKILL_DIR.rglob("*.md")))
        self.assertEqual(set(re.findall(r"\b(?:compile|goal|search|read|finish)\b", text)), ARENA_TOOLS)
        self.assertNotRegex(text, r"\barena_[a-z_]+\b")


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class ToolArgumentUxTests(unittest.TestCase):
    def test_empty_and_null_arguments_report_valid_keys(self):
        run = FakeRun(
            [cheap_tool("compile", {}), {"tool_calls": [{"name": "compile", "arguments": None}]}, {"text": "done"}]
        )
        self.addCleanup(run.cleanup)
        run.run()
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.stdout[-1000:])
        results = [
            m for m in run.requests[-1]["messages"] if m.get("role") == "toolResult" and m.get("toolName") == "compile"
        ]
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertTrue(result["isError"])
            self.assertIn("arrived empty or malformed", message_text(result))
            self.assertIn("drafts", message_text(result))
            self.assertNotIn("validation", message_text(result).lower())


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
                    thinking, [{"tool": "search", "input": {"queries": ["Core"]}}, {"text": "done"}]
                )
                assert run.result is not None
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
        run, wire = self.run_wire(
            "low",
            [
                {"tool": "read", "input": {"node": "n1"}, "usage": {"output_tokens": 150_000}},
                {"text": "done"},
            ],
        )
        self.assertEqual(wire.rejections, [], run.stdout[-800:])
        tools = {
            tool["name"]: tool["input_schema"] for tool in wire.payloads[1]["tools"] if tool["name"] in ARENA_TOOLS
        }
        self.assertEqual(set(tools), ARENA_TOOLS)
        for name, schema in tools.items():
            with self.subTest(tool=name):
                self.assertEqual(schema["type"], "object")
                self.assertFalse({"anyOf", "oneOf", "allOf"} & set(schema))
        self.assertEqual(set(tools["search"]["properties"]), {"queries", "kind", "after"})
        self.assertEqual(tools["search"]["required"], ["queries"])
        self.assertEqual(tools["finish"]["properties"], {})

    def test_wire_bytes_retries_and_langfuse_keep_the_post_hook_request(self):
        import hashlib
        from datetime import datetime

        from arena.traces import judge

        pad = "P" * 20001
        text = "Z" * 20001
        wire = AnthropicWire(
            [{"tool": "search", "input": {"queries": [pad]}}, {"text": text, "redacted": "opaque-signature-1"}],
            fail_first=1,
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
        assert run.result is not None
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
            f"traces={sorted(str(row.get('traceId')) for row in observations)}"
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

    def test_failed_request_continuation_names_failure_without_calling_it_text(self):
        run = self.fake(
            [{"error": "brief outage"}, cheap_tool("read", {"node": "n1"}), {"text": "finished"}, {"text": "more"}],
            env={"ARENA_BACKOFF_MS": "10", "ARENA_AUTOCONTINUE": "1"},
        )
        failed = "\n".join(message_text(m) for m in run.requests[1]["messages"])
        self.assertIn("request failed", failed.lower())
        self.assertIn("brief outage", failed)
        self.assertNotIn("turn ended with text", failed)
        completed = "\n".join(message_text(m) for m in run.requests[3]["messages"])
        self.assertIn("turn ended with text", completed)

    def test_continuation_contains_budget_and_best_node_facts(self):
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "tokens"}),
                {"text": "done"},
                {"text": "still done"},
            ]
        )
        later = "\n".join(message_text(m) for m in run.requests[-1]["messages"])
        self.assertIn("turn ended with text", later)
        self.assertIn("finish is available", later)
        self.assertIn("Best node:", later)
        self.assertNotIn("idea", later.lower())
        self.assertNotIn("route", later.lower())

    def test_continuation_inside_the_final_ten_percent_is_the_plain_prompt(self):
        run = self.fake(
            [cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT), {"text": "done"}, {"text": "still done"}],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        later = "\n".join(message_text(m) for m in run.requests[-1]["messages"])
        self.assertIn("turn ended with text", later)
        self.assertNotIn("Do not stop", later)

    def test_one_finish_call_stops_provider_continuations(self):
        run = self.fake(
            [
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                cheap_tool("finish", {}),
                {"text": "must not be requested"},
            ],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        self.assertEqual(len(run.requests), 2, run.stdout)
        self.assertEqual(run.json("summary.json")["stop_reason"], "finished")
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual([row.get("stop") for row in controls].count("finished"), 1)

    def test_compile_drafts_count_as_proof_attempts(self):
        from arena.campaign import problem

        statement = problem(NAME)["statement"]
        turns = []
        for index in range(3):
            drafts = [statement + f" := by\n  {'skip; ' * (index * 2 + k)}sorry" for k in range(2)]
            turns += [cheap_tool("compile", {"drafts": drafts, "check": "lean"}), {"text": f"final {index}"}]
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
        assert run.result is not None
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
                    "tool_calls": [{"name": "read", "arguments": {"node": "n1"}}],
                    "stop_reason": "length",
                    "usage": {"output": ceiling},
                },
                {"text": "done"},
            ],
            timeout=900,
        )
        self.runs.append(run)
        run.run()
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-2000:])
        later = "\n".join(message_text(message) for message in run.requests[1]["messages"])
        self.assertIn(f"The previous turn was cut at {ceiling} tokens.", later)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class FinishReplayTests(unittest.TestCase):
    def test_complete_compile_can_be_submitted_when_the_run_finishes(self):
        fixture = Path(__file__).resolve().parents[1] / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"
        run = FakeRun(
            [cheap_tool("compile", {"drafts": [fixture.read_text()], "check": "lean"}), {"text": "done"}], timeout=1200
        )
        self.addCleanup(run.cleanup)
        run.run()
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-1000:])
        self.assertIsNotNone(run.json("submission.json").get("candidate"), run.stdout)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class CompactionPolicyTests(unittest.TestCase):
    # Distinct views avoid the repeated-read stub; the fake provider usage drives compaction.
    READS = [("n1", 0)] * 6
    READ_VIEWS = ("source", "prices", "map", "outline", "diff", "source")

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def script(self):
        usage = {"input": 14000, "output": 50, "cacheRead": 0, "cacheWrite": 0}
        steps: list[dict] = [
            {
                "tool_calls": [
                    {
                        "name": "read",
                        "arguments": {
                            "node": path,
                            "view": self.READ_VIEWS[offset],
                            **({"against": path} if self.READ_VIEWS[offset] == "diff" else {}),
                        },
                    }
                ],
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
        steps: list[dict[str, object]] = [
            {
                "tool_calls": [
                    {
                        "name": "read",
                        "arguments": {
                            "node": path,
                            "view": self.READ_VIEWS[offset],
                            **({"against": path} if self.READ_VIEWS[offset] == "diff" else {}),
                        },
                    }
                ],
                "usage": {"input": 3000, "output": 50},
            }
            for path, offset in self.READS[:2]
        ]
        steps.extend(
            [
                {"text": "cut off", "stop_reason": "length", "usage": {"input": 3000, "output": 16000}},
                {"text": "done", "usage": {"input": 100, "output": 20}},
            ]
            + [{"text": "done"}] * 3
        )
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
