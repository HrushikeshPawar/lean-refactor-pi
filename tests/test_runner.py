"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import itertools
import json
import re
import shutil
import tempfile
import unittest
from datetime import UTC
from pathlib import Path

from arena import models
from arena.engine import ROOT, problem, versions
from arena.index import index_path
from arena.scoring import exchange_rates
from arena.skill import SKILL_DIR, skill_hash, skill_prompt
from tests.pi_support import LIVE_LANGFUSE, NAME, PI_AVAILABLE, AnthropicWire, FakeRun, message_text
from tests.slow import slow

# Text-only turns never end a run; only the actual-cost limit does. These two follow a turn that spends to 90%.
STOP = [{"text": "done"}] * 2
# Words that name ending the run; none may reach the model before the final tenth of the spend (plan D42).
STOP_TEXT = re.compile(r"\b(?:finish\w*|stop\w*|threshold\w*|tenth|end(?:s|ing)? the run)\b", re.I)


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SkillAndThinkingTests(unittest.TestCase):
    def tearDown(self):
        for run in getattr(self, "runs", []):
            run.cleanup()

    def start(self, *extra: str) -> FakeRun:
        run = FakeRun([cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT), *STOP])
        self.runs = [*getattr(self, "runs", []), run]
        return run.run(*extra)

    def test_skill_and_thinking_options_are_recorded_and_reach_the_provider(self):
        default = self.start()
        first = default.requests[0]["messages"][0]
        # The skill body is appended to the system prompt; its last line marks that the whole body arrived.
        skill_line = skill_prompt().strip().splitlines()[-1]
        self.assertIn(skill_line, message_text(first))
        self.assertIn("compile", offered_tools(default.requests[0]))
        config = default.json("run-config.json")
        self.assertEqual(config["skill"], {"name": "arena-lean", "sha256": skill_hash()})
        self.assertEqual(config["thinking"], "high")
        self.assertEqual({r["thinking"] for r in default.requests}, {"high"})
        low = self.start("--thinking", "low", "--no-skill")
        self.assertEqual(low.json("run-config.json")["thinking"], "low")
        self.assertEqual({r["thinking"] for r in low.requests}, {"low"})
        self.assertIsNone(low.json("run-config.json")["skill"])
        self.assertNotIn(skill_line, message_text(low.requests[0]["messages"][0]))

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
            [
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                *[{"text": "done", "usage": {"input": 500, "output": 20, "cacheRead": 0, "cacheWrite": 500}}] * 2,
            ]
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

    def test_the_tool_list_never_changes_inside_the_final_ten_percent(self):
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
        self.assertEqual([set(tools) for tools in offered], [ARENA_TOOLS] * len(offered))

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


ARENA_TOOLS = {"compile", "goal", "search", "read", "scratch"}
# The tool list is fixed from the first request: a late tool would change the cached prompt prefix.
START_TOOLS = ARENA_TOOLS


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


def _spend_numbers(spent: float, cap: float) -> list[str]:
    """The spend facts as digits: spent and limit in dollars, whole percent of the limit left."""
    return [f"{spent:.2f}", f"{cap:.2f}", str(round(100 * (1 - spent / cap)))]


def _spend_facts(message: str) -> str:
    """Spend facts in a continuation. A stall or focus line is not part of the continuation."""
    return message


def cheap_tool(name: str, arguments: dict, **usage) -> dict:
    return {
        "tool_calls": [{"name": name, "arguments": arguments}],
        "usage": {"input": 300, "output": 40, "cacheRead": 4000, "cacheWrite": 100, **usage},
    }


# One scripted response whose 150K output tokens ($0.60/M) spend 90% of the $0.1 test cap.
SPEND_90_PCT = 150_000


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
                cheap_tool("read", {"node": "n1", "view": "source"}, output=SPEND_90_PCT),
                {"text": "done"},
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
        # The packet's rates are this row's own, computed from its pinned denominators.
        rates = exchange_rates(NAME, len(versions(problem(NAME))))
        for field in ("points_per_token", "points_per_100_heartbeats", "points_per_lost_version"):
            self.assertRegex(first, rf"(?<![\d.]){re.escape(str(rates[field]))}(?![\d])", field)
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
        alarmed = self.fake(
            [cheap_tool("read", {"node": "n1"}, **bad)] * 4
            + [{"text": "done", "usage": bad}]
            + [cheap_tool("read", {"node": "n1", "view": "source"}, **{**bad, "output": SPEND_90_PCT})]
            + [{"text": "done", "usage": bad}] * 2
        )
        summary = alarmed.json("summary.json")
        self.assertGreaterEqual(summary["cache"]["alarms"], 1)
        kinds = [e["kind"] for e in alarmed.jsonl("cost-ledger.jsonl")]
        self.assertIn("cache_alarm", kinds)
        healthy = self.fake(
            [cheap_tool("read", {"node": "n1"}, **good)] * 4
            + [{"text": "done", "usage": good}]
            + [cheap_tool("read", {"node": "n1", "view": "source"}, **{**good, "output": SPEND_90_PCT})]
            + [{"text": "done", "usage": good}] * 2
        )
        self.assertEqual(healthy.json("summary.json")["cache"]["alarms"], 0)
        self.assertGreater(healthy.json("summary.json")["cache"]["reuse_pct"], 90)


FIXTURE = Path(__file__).resolve().parents[1] / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"
# What the fixture measures on every listed version: (tokens, heartbeats, proxy).
FIXTURE_SCORE = (126, 578, 76.72)
AGENT_TEXT = ROOT / "agent-text"


def tool_texts(request: dict, name: str | None = None) -> list[str]:
    return [
        message_text(m)
        for m in request["messages"]
        if m["role"] == "toolResult" and (name is None or m.get("toolName") == name)
    ]


def tool_results(request: dict, name: str) -> list[dict]:
    return [m for m in request["messages"] if m["role"] == "toolResult" and m.get("toolName") == name]


def shown_context(details: dict) -> list[str]:
    """The ambient lines a tool reply sends with the turn (its `context` sections), in order."""
    return [line for section in details.get("context", {}).get("sections", []) for line in section]


def compiled_node(run: FakeRun, reply: dict) -> tuple[str, str, float]:
    """The one node a single-draft compile reply filed: its id, its stored candidate label and the map's score for it.

    Replies name nodes by graph id (nK); submission.json keeps the stored label (#k), so map one to the other
    through the run's history."""
    from arena import campaign

    [item] = reply["items"]
    history = campaign.events(run.directory)
    filed = dict.fromkeys(
        str(e.get("candidate_id") or e["proof_id"]) for e in history if e.get("kind") in ("candidate", "probe")
    )
    [proof_id] = [current for current in filed if campaign._graph_node_id(history, current) == item["node"]]
    scores = {
        match[1]: float(match[2])
        for line in shown_context(reply) if (match := re.match(r"best (\S+) score ([\d.]+)", line))
    }
    return item["node"], campaign.node_label(history, proof_id), scores[item["node"]]


def schema_keys(request: dict, tool: str) -> list[str]:
    [definition] = [d for d in request["tool_definitions"] if d["name"] == tool]
    return list(definition["parameters"]["properties"])


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class AutomaticChecksTests(unittest.TestCase):
    """The compile action checks drafts and exposes measured results."""

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def fake(self, steps, **kwargs):
        run = FakeRun(steps, **kwargs)
        self.runs.append(run)
        return run.run()

    def test_cross_version_result_arrives_in_the_compile_reply_without_rewriting_history(self):
        # No provider delay: the compile call itself waits for the cross-version check
        # (cross_version_wait_seconds), so the result is in its own reply, not on a later tool result.
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}),
                cheap_tool("read", {"node": "n1"}),
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ]
        )
        requests = run.requests
        self.assertGreaterEqual(len(requests), 3, run.stdout)
        [compiled] = tool_results(requests[1], "compile")
        node, label, score = compiled_node(run, compiled["details"])
        self.assertEqual(score, FIXTURE_SCORE[2])
        # The cross-version fact names the filed node by its graph id and carries its score.
        facts = [*compiled["details"]["facts"], *shown_context(compiled["details"])]
        self.assertTrue(any(re.search(rf"\b{node}\b", fact) and str(score) in fact for fact in facts), facts)
        self.assertIn(node, compiled["details"]["handles"])
        for earlier, after in itertools.pairwise(requests):
            before = earlier["messages"]
            self.assertEqual(json.dumps(after["messages"][: len(before)]), json.dumps(before))
        submission = run.json("submission.json")
        self.assertEqual(submission["candidate"], label, run.stdout)
        self.assertEqual((submission["tokens"], submission["heartbeats"], submission["proxy"]), FIXTURE_SCORE)

    def test_every_arena_tool_succeeds_with_the_arguments_models_actually_send(self):
        fixture = FIXTURE.read_text()
        calls = [
            # `draft` for `drafts`, a bare string for a list, and empty optional fields.
            ("compile", {"draft": fixture, "check": "tokens", "note": "", "base": ""}),
            # A list sent as JSON text.
            ("compile", {"drafts": json.dumps([fixture + "\n"]), "check": "tokens", "from": ""}),
            ("goal", {"node": "n1", "line": 12, "hole": "", "try": [""]}),
            ("search", {"queries": '["InitsUpdatesComm", "UpdateStates"]', "kind": "name", "after": ""}),
            ("search", {"queries": "['InitStatesUpdated']", "kind": ""}),
            ("read", {"node": "n1", "view": "", "against": "", "hole": ""}),
        ]
        steps = [cheap_tool(name, args) for name, args in calls]
        # A text-only turn at 90% continues; the final read crosses the limit and ends the run.
        steps += [cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), {"text": "done"},
                  cheap_tool("read", {"view": "map"}, output=20_000)]
        run = self.fake(steps, session=True, timeout=900)  # goal needs the Lean session's LSP lane
        summary = run.json("summary.json")
        self.assertEqual(summary["tools"]["errors"], {}, run.stdout[-1500:])
        self.assertEqual(set(summary["tools"]["calls"]), ARENA_TOOLS - {"scratch"})  # the script never calls scratch
        self.assertEqual(summary["tools"]["calls"]["compile"], 2)
        self.assertEqual(summary["stop_reason"], "limit_reached")
        self.assertEqual(len(run.requests), len(steps))
        # Item errors too: only a missing search index (a machine cache, built by `arena index build`) is allowed.
        allowed = {"no_index"} if index_path(NAME) is None else set()
        results = [m for m in run.requests[-1]["messages"] if m["role"] == "toolResult"]
        # The crossing read's result is never delivered: the run ends at the limit before another request.
        self.assertEqual([m["toolName"] for m in results], [name for name, _ in calls] + ["read"])
        for result in results:
            with self.subTest(tool=result["toolName"], call=result["toolCallId"]):
                self.assertFalse(result["isError"], message_text(result))
                codes = {item["error"]["code"] for item in result["details"].get("items", []) if item.get("error")}
                self.assertEqual(codes - allowed, set(), message_text(result))
        # Each shape reached the handler intact: one draft per compile, every query of a stringified list.
        compiled = [result["details"]["items"] for result in tool_results(run.requests[-1], "compile")]
        self.assertEqual([len(items) for items in compiled], [1, 1])
        searched = [[item["ref"] for item in r["details"]["items"]] for r in tool_results(run.requests[-1], "search")]
        self.assertEqual(searched, [["InitsUpdatesComm", "UpdateStates"], ["InitStatesUpdated"]])

    def test_checks_queued_when_the_model_stops_are_finished_before_submitting(self):
        # With no in-call wait the cross-version check is still queued when the model stops;
        # the runner must finish it before it chooses the submission.
        texts = Path(self.enterContext(tempfile.TemporaryDirectory())) / "agent-text"
        shutil.copytree(AGENT_TEXT, texts)
        numbers = texts / "numbers.yaml"
        numbers.write_text(
            re.sub(r"(?m)^cross_version_wait_seconds: .*$", "cross_version_wait_seconds: 0", numbers.read_text())
        )
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}),
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ],
            env={"ARENA_TEXT_DIR": str(texts)},
        )
        [compiled] = tool_results(run.requests[-1], "compile")
        [item] = compiled["details"]["items"]
        _, label, _ = compiled_node(run, compiled["details"])
        node = re.compile(rf"\b{item['node']}\b")
        facts = [*compiled["details"]["facts"], *shown_context(compiled["details"])]
        self.assertFalse(any(node.search(fact) for fact in facts), "the check did not stay queued")
        submission = run.json("submission.json")
        self.assertEqual(submission["candidate"], label, run.stdout)
        self.assertEqual((submission["tokens"], submission["heartbeats"], submission["proxy"]), FIXTURE_SCORE)
        self.assertIn(f"Submission: {label} proxy {FIXTURE_SCORE[2]}", run.stdout)

    def test_a_second_compile_on_the_first_compiles_node_succeeds_through_the_lean_session(self):
        # Session-checked results carry the Lean path, which once crashed every compile reply.
        fixture = FIXTURE.read_text()
        variant = fixture.replace("intros Hup Hinit", "intro Hup Hinit")
        self.assertNotEqual(variant, fixture)
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [fixture], "check": "lean"}),
                cheap_tool("compile", {"base": "n2", "drafts": [variant], "check": "lean"}),
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ],
            session=True,
            timeout=900,
        )
        results = tool_results(run.requests[-1], "compile")
        self.assertEqual(len(results), 2, run.stdout[-1500:])
        for result in results:
            with self.subTest(call=result["toolCallId"]):
                self.assertFalse(result["isError"], message_text(result))
                [item] = result["details"]["items"]
                self.assertIsNone(item["error"], message_text(result))
        first, second = (result["details"]["items"][0]["node"] for result in results)
        self.assertEqual(first, "n2")
        self.assertNotEqual(second, first)
        self.assertFalse((run.directory / "tool-errors.log").exists())

    def test_a_compile_starts_the_full_check_without_another_tool_call(self):
        # No in-call wait: only the background checker the compile kicks can run the full check
        # while the model is still thinking (the delayed final reply), before the run's closing drain.
        texts = Path(self.enterContext(tempfile.TemporaryDirectory())) / "agent-text"
        shutil.copytree(AGENT_TEXT, texts)
        numbers = texts / "numbers.yaml"
        numbers.write_text(
            re.sub(r"(?m)^cross_version_wait_seconds: .*$", "cross_version_wait_seconds: 0", numbers.read_text())
        )
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}),
                {"text": "done", "delay_ms": 150_000},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ],
            env={"ARENA_TEXT_DIR": str(texts)},
            timeout=600,
        )
        [compiled] = tool_results(run.requests[-1], "compile")
        self.assertFalse(compiled["isError"], message_text(compiled))
        full = [
            row
            for row in run.jsonl("ledger.jsonl")
            if row.get("kind") == "evaluation" and (row.get("result") or {}).get("mode") == "full"
        ]
        self.assertTrue(full, run.stdout[-1500:])
        responses = [row["ts"] for row in run.jsonl("trace-journal.jsonl") if row.get("kind") == "response"]
        self.assertLess(full[0]["ts"], responses[-1] / 1000, "the full check waited for the closing drain")
        self.assertNotIn("Background checks after Pi exited", run.stdout)


class SkillToolNamesTests(unittest.TestCase):
    def test_skill_mentions_the_offered_tools_and_never_finish(self):
        text = "\n".join(path.read_text() for path in sorted(SKILL_DIR.rglob("*.md")))
        self.assertEqual(set(re.findall(r"\b(?:compile|goal|search|read|scratch|finish)\b", text)), START_TOOLS)
        self.assertNotRegex(text, STOP_TEXT)
        self.assertNotRegex(text, r"\barena_[a-z_]+\b")


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class ToolArgumentUxTests(unittest.TestCase):
    def fake(self, steps) -> FakeRun:
        run = FakeRun(steps)
        self.addCleanup(run.cleanup)
        run.run()
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.stdout[-1000:])
        return run

    def assert_rejected_before_running(self, run: FakeRun, results: list[dict]) -> None:
        """Each result is an error that lists every compile key, and no Lean ran."""
        valid = schema_keys(run.requests[-1], "compile")
        self.assertIn("drafts", valid)
        for result in results:
            text = message_text(result)
            self.assertTrue(result["isError"], text)
            self.assertEqual([key for key in valid if not re.search(rf"\b{key}\b", text)], [], text)
            self.assertNotIn("validation", text.lower())
        summary = run.json("summary.json")
        self.assertEqual(summary["evaluations"], 0)
        self.assertEqual(summary["progress"]["best_verified_candidate"], None)
        self.assertNotEqual(summary["stop_reason"], "error_loop")

    def test_empty_and_null_arguments_report_valid_keys(self):
        run = self.fake(
            [
                cheap_tool("compile", {}),
                {"tool_calls": [{"name": "compile", "arguments": None}]},
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ]
        )
        results = tool_results(run.requests[-1], "compile")
        self.assertEqual(len(results), 2)
        self.assert_rejected_before_running(run, results)

    def test_malformed_json_arguments_are_rejected_instead_of_running(self):
        # The provider streams text that is not a JSON object; Pi would parse it as {} and run the tool.
        draft = FIXTURE.read_text()
        run = self.fake(
            [
                {"tool_calls": [{"name": "compile", "arguments": {}, "raw_arguments": '{"drafts": ["' + draft[:40]}]},
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ]
        )
        results = tool_results(run.requests[-1], "compile")
        self.assertEqual(len(results), 1)
        self.assert_rejected_before_running(run, results)

    def test_a_misnamed_tool_gets_the_nearest_registered_name(self):
        run = self.fake(
            [
                cheap_tool("compil", {"drafts": [FIXTURE.read_text()]}),
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ]
        )
        [result] = tool_results(run.requests[-1], "compil")
        self.assertTrue(result["isError"])
        named = set(re.findall(r"\b(?:compile|goal|search|read|finish)\b", message_text(result)))
        self.assertEqual(named, {"compile"}, message_text(result))
        self.assertEqual(run.json("summary.json")["evaluations"], 0)


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
                    thinking,
                    [
                        {"tool": "search", "input": {"queries": ["Core"]}},
                        {"tool": "read", "input": {"view": "map"}, "usage": {"output_tokens": 150_000}},
                        {"text": "done"},
                        {"text": "done"},
                    ],
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
                {"text": "done"},
            ],
        )
        self.assertEqual(wire.rejections, [], run.stdout[-800:])
        self.assertEqual({tool["name"] for tool in wire.payloads[0]["tools"]}, START_TOOLS)
        tools = {tool["name"]: tool["input_schema"] for tool in wire.payloads[1]["tools"]}
        self.assertEqual(set(tools), ARENA_TOOLS)
        for name, schema in tools.items():
            with self.subTest(tool=name):
                self.assertEqual(schema["type"], "object")
                self.assertFalse({"anyOf", "oneOf", "allOf"} & set(schema))
        self.assertEqual(set(tools["search"]["properties"]), {"queries", "kind", "after"})
        # No key is schema-required: an empty call reaches the handler, which names the valid keys.
        self.assertEqual({name: schema.get("required") for name, schema in tools.items() if schema.get("required")}, {})

    def test_wire_bytes_retries_and_langfuse_keep_the_post_hook_request(self):
        import hashlib
        from datetime import datetime

        from arena.traces import judge

        pad = "P" * 20001
        text = "Z" * 20001
        wire = AnthropicWire(
            [
                {"tool": "search", "input": {"queries": [pad]}},
                {"text": text, "redacted": "opaque-signature-1"},
                {"tool": "read", "input": {"view": "map"}, "usage": {"output_tokens": 150_000}},
                {"text": "done"},
                {"text": "done"},
            ],
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
        steps = (
            [{"error": "blip", "usage": {"input": 10, "output": 1}}, {"text": "first answer"}]
            + [{"text": "more"}] * 8
            + [cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), {"text": "more"}, {"text": "more"}]
        )
        run = self.fake(steps, env={"ARENA_BACKOFF_MS": "10"})
        controls = [e for e in run.jsonl("cost-ledger.jsonl") if e["kind"] == "control"]
        self.assertNotEqual(controls[-1]["stop"], "error_loop")
        self.assertTrue(any(e["continuations"] >= 1 for e in controls))

    def test_failed_request_continuation_names_failure_without_calling_it_text(self):
        from arena import text

        # Outputs stay under the stall restart (0.12 of the $0.1 limit spent with no new best), which would replace
        # the failure continuation with a restart packet.
        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}, output=10_000),
                {"error": "brief outage"},
                cheap_tool("read", {"node": "n1"}, output=5_000),
                {"text": "finished"},
                {"text": "more"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "last"},
                {"text": "last"},
            ],
            env={"ARENA_BACKOFF_MS": "10", "ARENA_AUTOCONTINUE": "1", "ARENA_ISLANDS": "0"},
        )
        # Every user message after the packet is a continuation: the first after the failure, then after text turns.
        failed, *completed = [message_text(m) for m in run.requests[-1]["messages"][2:] if m["role"] == "user"]
        self.assertTrue(completed)
        # Which template rendered: each key's fixed opening, read from agent-text rather than copied here.
        opening = {
            key: text.template(f"messages/continuation.{key}").split("{")[0].strip()
            for key in ("request_failed", "turn_ended_with_text")
        }
        self.assertTrue(failed.startswith(opening["request_failed"]), failed)
        self.assertNotIn(opening["turn_ended_with_text"], failed)
        self.assertIn("brief outage", failed)
        for later in completed:
            self.assertTrue(later.startswith(opening["turn_ended_with_text"]), later)
            self.assertNotIn("brief outage", later)

        # The numbers are the run's own: spend at each continuation from the ledger, points left from the best.
        rows = run.jsonl("cost-ledger.jsonl")
        spent_at = []
        for index, row in enumerate(rows):
            if row["kind"] == "control" and not row.get("stop"):
                spent_at.append(next(r["spent_usd"] for r in reversed(rows[:index]) if r["kind"] == "settle"))
        self.assertEqual(len(spent_at), 1 + len(completed), rows)
        self.assertGreater(spent_at[1], spent_at[0])
        submission = run.json("submission.json")
        self.assertEqual((submission["tokens"], submission["heartbeats"]), FIXTURE_SCORE[:2])

        cap = float(run.json("run-config.json")["limit_usd"])
        for message, spent in zip([failed, *completed], spent_at, strict=True):
            with self.subTest(message=message[:40]):
                numbers = re.findall(r"\d+(?:\.\d+)?", _spend_facts(message))
                self.assertEqual([n for n in _spend_numbers(spent, cap) if n not in numbers], [], (message, rows))

    def continuations(self, run: FakeRun) -> list[tuple[str, float]]:
        """Each continuation the model read, with the settled spend when it was sent (from the ledger)."""
        messages = [message_text(m) for m in run.requests[-1]["messages"][2:] if m["role"] == "user"]
        rows = run.jsonl("cost-ledger.jsonl")
        spent_at = [
            next(r["spent_usd"] for r in reversed(rows[:index]) if r["kind"] == "settle")
            for index, row in enumerate(rows)
            if row["kind"] == "control" and not row.get("stop")
        ]
        self.assertTrue(messages)
        self.assertEqual(len(messages), len(spent_at), rows)
        return list(zip(messages, spent_at, strict=True))

    def test_continuation_before_the_final_tenth_states_only_spend_and_points_left(self):
        from arena import text

        run = self.fake(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}),
                {"text": "done"},
                {"text": "still done"},
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
                {"text": "done"},
            ],
            env={"ARENA_AUTOCONTINUE": "1", "ARENA_ISLANDS": "0"},
        )
        pct = text.numbers()["finish_remaining_pct"]
        cap = float(run.json("run-config.json")["limit_usd"])
        submission = run.json("submission.json")
        self.assertEqual((submission["tokens"], submission["heartbeats"]), FIXTURE_SCORE[:2])
        # Only continuations sent before spend reached the final tenth; those after it are checked elsewhere.
        before_tenth = [(m, s) for m, s in self.continuations(run) if 1 - s / cap > pct / 100]
        self.assertGreaterEqual(len(before_tenth), 2)
        for message, spent in before_tenth:
            with self.subTest(message=message):
                self.assertGreater(1 - spent / cap, pct / 100)
                self.assertNotRegex(message, STOP_TEXT)
                self.assertNotRegex(message, rf"(?<![\d.]){pct}(?!\d|\.\d)")
                numbers = re.findall(r"\d+(?:\.\d+)?", _spend_facts(message))
                self.assertEqual(sorted(numbers), sorted(_spend_numbers(spent, cap)))

    def test_continuation_inside_the_final_tenth_states_finish_available_once(self):
        from arena import text

        # Inside the final tenth a text-only turn finishes the run, so the continuations come from failed requests.
        run = self.fake(
            [
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                {"error": "brief outage"},
                {"error": "brief outage"},
                {"text": "done"},
            ],
            env={"ARENA_AUTOCONTINUE": "1", "ARENA_ISLANDS": "0", "ARENA_BACKOFF_MS": "10"},
        )
        pct = text.numbers()["finish_remaining_pct"]
        cap = float(run.json("run-config.json")["limit_usd"])
        for message, spent in self.continuations(run):
            with self.subTest(message=message):
                self.assertLessEqual(1 - spent / cap, pct / 100)
                self.assertNotRegex(message, STOP_TEXT)
                self.assertIn(_spend_numbers(spent, cap)[0], message)

    def test_a_text_only_turn_in_the_final_tenth_continues_until_the_limit(self):
        run = self.fake(
            [
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                {"text": "done"},
                cheap_tool("read", {"node": "n1"}, output=20_000),
                {"text": "must not be requested"},
            ],
            env={"ARENA_AUTOCONTINUE": "1"},
        )
        self.assertEqual(len(run.requests), 3, run.stdout)
        self.assertEqual(run.json("summary.json")["stop_reason"], "limit_reached")
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertTrue(controls, run.stdout)
        self.assertEqual({row["stop"] for row in controls if row.get("stop")} - {"limit_reached"}, set())

    def test_compile_drafts_count_as_proof_attempts(self):
        from arena.campaign import problem

        statement = problem(NAME)["statement"]
        turns = []
        for index in range(3):
            drafts = [statement + f" := by\n  {'skip; ' * (index * 2 + k)}sorry" for k in range(2)]
            turns += [cheap_tool("compile", {"drafts": drafts}), {"text": f"final {index}"}]
        turns += [cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT), {"text": "final 3"}, {"text": "final 4"}]
        run = self.fake(turns, env={"ARENA_AUTOCONTINUE": "1"})
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertTrue(controls, run.stdout)
        self.assertTrue(all(row["proof_attempt"] for row in controls[:3]), controls)
        self.assertFalse(any(row.get("stop") == "no_work_fallback" for row in controls[:3]), controls)

    def test_an_identical_read_is_stubbed_and_turns_without_work_never_end_the_run_before_the_limit(self):
        # v8: a turn without work, early or inside the final tenth, never ends the run; only the actual-cost limit does.
        early = 3
        read = cheap_tool("read", {"node": "n1"})
        script: list = [read, {"text": "first final"}]
        for index in range(early):
            script += [read, {"text": f"final {index}"}]
        # Two more no-work turns inside the final tenth continue; the last read crosses the limit.
        script += [cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT), {"text": ""}]
        script += [cheap_tool("read", {"node": "n1"}, output=20_000), {"text": "must not be requested"}]
        run = self.fake(script, env={"ARENA_AUTOCONTINUE": "1", "ARENA_ISLANDS": "0"})
        # Two turns without work in a row restart the context before the final tenth, so the reads are gathered
        # across every request: each scripted read reaches the model once, in full or as a stub.
        reads, previous = [], []
        for request in run.requests:
            current = tool_texts(request, "read")
            if len(current) < len(previous):
                previous = []
            reads += current[len(previous) :]
            previous = current
        self.assertEqual(len(reads), early + 2)
        first = reads[0]
        longest = max(first.splitlines(), key=len)
        repeats = [read for read in reads if read != first]
        self.assertTrue(repeats)
        for repeat in repeats:
            self.assertNotIn(longest, repeat)
            self.assertLess(len(repeat), len(first) / 2)
        # The first read of each context is new context; every stubbed repeat is a turn without work.
        controls = [row for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "control"]
        self.assertEqual({row["stop"] for row in controls if row.get("stop")} - {"limit_reached"}, set())
        self.assertFalse(any(row.get("stop") for row in controls[:-1]))
        cap = float(run.json("run-config.json")["limit_usd"])
        settled = [row["spent_usd"] for row in run.jsonl("cost-ledger.jsonl") if row.get("kind") == "settle"]
        self.assertGreaterEqual(settled[-1] / cap, 0.9)
        self.assertEqual(run.json("summary.json")["stop_reason"], "limit_reached")
        self.assertEqual(len(run.requests), 2 * (early + 2) + 1)


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
            [{"error": "brief outage"}] * 5
            + [{"text": "recovered"}]
            + [{"text": "more"}] * 8
            + [cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), {"text": "more"}, {"text": "more"}],
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
                cheap_tool("read", {"node": "n1"}, output=SPEND_90_PCT),
                {"text": "done"},
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
                cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT),
                {"text": "done"},
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
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class FinishReplayTests(unittest.TestCase):
    def test_one_finishing_turn_submits_the_candidate_verified_before_it(self):
        # A text-only turn in the final tenth continues; the run ends at the limit, and the submission is the
        # node the earlier compile verified.
        run = FakeRun(
            [
                cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}, output=SPEND_90_PCT),
                {"text": "done"},
                cheap_tool("read", {"view": "map"}, output=20_000),
                {"text": "must not be requested"},
            ],
            timeout=1200,
        )
        self.addCleanup(run.cleanup)
        run.run()
        assert run.result is not None
        self.assertEqual(run.result.returncode, 0, run.stdout + run.result.stderr[-1000:])
        self.assertEqual(len(run.requests), 3, run.stdout)
        [compiled] = tool_results(run.requests[1], "compile")
        _, label, _ = compiled_node(run, compiled["details"])
        summary = run.json("summary.json")
        self.assertEqual(summary["stop_reason"], "limit_reached")
        submission = run.json("submission.json")
        self.assertEqual(submission["candidate"], label, run.stdout)
        self.assertEqual((submission["tokens"], submission["heartbeats"], submission["proxy"]), FIXTURE_SCORE)
        self.assertEqual(
            summary["progress"]["best_verified_candidate"],
            dict(zip(("candidate", "tokens", "heartbeats", "proxy"), (label, *FIXTURE_SCORE), strict=True)),
        )


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class CompactionPolicyTests(unittest.TestCase):
    # Six distinct reads, so none is stubbed as a repeat; the fake provider usage drives compaction.
    READS = (
        {"node": "n1", "view": "source"},
        {"node": "n1", "view": "prices"},
        {"node": "n1", "view": "outline"},
        {"node": "n1", "view": "map"},
        {"view": "map"},
        {"node": "n1", "view": "diff", "against": "n1"},
    )

    def setUp(self):
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.cleanup()

    def script(self):
        usage = {"input": 14000, "output": 50, "cacheRead": 0, "cacheWrite": 0}
        steps = [{"tool_calls": [{"name": "read", "arguments": arguments}], "usage": usage} for arguments in self.READS]
        # The last read also carries the run into its final tenth (the reads spent ~13%; 133K output adds 80%),
        # where two text turns end it (D42).
        steps[-1] = {**steps[-1], "usage": {**usage, "output": 133_000}}
        return steps + [{"text": "done", "usage": {"input": 100, "output": 20}}] * 2

    def fake(self, *extra) -> FakeRun:
        run = FakeRun(self.script())
        self.runs.append(run)
        return run.run(*extra)

    def test_past_the_threshold_only_the_tail_is_summarized_and_the_prefix_stays_identical(self):
        run = self.fake("--compact-at-tokens", "12000", "--compact-keep-tokens", "300")
        requests = run.requests
        summaries = [r for r in requests if not r["messages"][0].get("sections")]
        self.assertTrue(summaries, "compaction never ran")
        self.assertEqual(run.json("summary.json")["tools"]["errors"], {}, "every distinct read must be a valid view")
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
        # Pi compacts after a length stop below the model's output ceiling (it reads that as context
        # pressure); a turn cut at the ceiling itself must stay in history.
        ceiling = models.load()["models"]["deepseek-v4.1-flash"]["request_output_tokens"]
        steps: list[dict] = [
            {"tool_calls": [{"name": "read", "arguments": arguments}], "usage": {"input": 3000, "output": 50}}
            for arguments in self.READS[:2]
        ]
        spend = {
            "tool_calls": [{"name": "read", "arguments": {"node": "n1"}}],
            "usage": {"input": 3000, "output": SPEND_90_PCT},
        }
        steps = [
            *steps,
            {"text": "cut off", "stop_reason": "length", "usage": {"input": 3000, "output": ceiling}},
            {"text": "done", "usage": {"input": 100, "output": 20}},
            spend,
            {"text": "done"},
            {"text": "done"},
        ]
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
