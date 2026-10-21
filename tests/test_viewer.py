"""Offline tests for the run viewer's data shaping and server (no Langfuse network, no live runs)."""

import importlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from arena import campaign, viewer_data
from arena.viewer_data import Langfuse, LangfuseUnavailable, hub_row, run_dashboard, shape_langfuse

server = importlib.import_module("arena.cli.serve")

T0 = 1_791_000_000


def ms(offset: float) -> int:
    return int((T0 + offset) * 1000)


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def evaluation(ts, candidate, mode, proxy, path="session", tokens=100, hb=300):
    metrics = {
        "compiled": True,
        "proxy": proxy if mode == "full" else None,
        "estimated_proxy": proxy if mode != "full" else None,
    }
    return {
        "kind": "evaluation",
        "ts": ts,
        "candidate_id": candidate,
        "mode": mode,
        "result": {
            "tokens": tokens,
            "heartbeat": hb,
            "metrics": metrics,
            "compat": {"v1": {"passed": True, "heartbeats": hb, "lean": {"path": path, "seconds": 1.5}}},
        },
    }


def make_run(root: Path, run_id: str, finished: bool = True, theorem: str = "Core.T") -> Path:
    directory = root / "runs" / "pi-budget" / run_id
    directory.mkdir(parents=True)
    (directory / "run-config.json").write_text(
        json.dumps({"theorem": theorem, "model": "m1", "thinking": "high", "hard_cap_usd": 0.1})
    )
    (directory / "packet.txt").write_text("kickoff packet text")
    write(
        directory / "ledger.jsonl",
        [
            {"kind": "init", "ts": T0 + 0.0, "theorem": theorem},
            {"kind": "candidate", "ts": T0 + 0.1, "candidate_id": "ref", "parents": [], "origin": "reference"},
            {"kind": "idea", "ts": T0 + 1, "id": "i1", "title": "Idea one", "hypothesis": "h", "status": "active"},
            {
                "kind": "candidate",
                "ts": T0 + 2,
                "candidate_id": "c2",
                "parents": ["ref"],
                "origin": "model",
                "idea_id": "i1",
            },
            {
                "kind": "probe",
                "ts": T0 + 3,
                "proof_id": "p1",
                "idea_id": "i1",
                "result": {"compat": {"v1": {"lean": {"path": "cold", "seconds": 4.0}}}},
            },
            evaluation(T0 + 10, "c2", "fast", 60.0),
            evaluation(T0 + 12, "c2", "full", 60.5),
            {"kind": "idea_update", "ts": T0 + 20, "id": "i1", "status": "succeeded", "reason": "worked"},
            {
                "kind": "cold_verification",
                "ts": T0 + 30,
                "candidate_id": "c2",
                "confirmed": True,
                "passed": {"v1": True},
                "recorded_heartbeats": 300,
                "cold_heartbeats": 301,
            },
        ],
    )
    write(
        directory / "cost-ledger.jsonl",
        [
            {
                "ts": ms(5),
                "kind": "settle",
                "id": "a",
                "usd": 0.01,
                "usage_known": True,
                "tokens": {"input": 5, "output": 50, "cache_read": 0, "cache_write": 900},
                "ledger_components_usd": {"input": 0.001, "output": 0.004, "cacheRead": 0, "cacheWrite": 0.005},
            },
            {
                "ts": ms(25),
                "kind": "settle",
                "id": "b",
                "usd": 0.02,
                "usage_known": True,
                "spent_usd": 0.03,
                "limit_usd": 0.025,
                "tokens": {"input": 5, "output": 50, "cache_read": 900, "cache_write": 100},
                "ledger_components_usd": {"input": 0.001, "output": 0.004, "cacheRead": 0.005, "cacheWrite": 0.01},
            },
            {"ts": ms(30), "kind": "finish", "phase": "review"},
            {"ts": ms(31), "kind": "control", "stop": "finished"},
        ],
    )
    write(
        directory / "trace-journal.jsonl",
        [
            {"ts": ms(6), "kind": "tool_call", "tool_call_id": "t1", "name": "compile", "args": {"x": 1}},
            {
                "ts": ms(7.5),
                "kind": "tool_result",
                "tool_call_id": "t1",
                "name": "compile",
                "result": {"isError": False, "content": [{"type": "text", "text": '{"ok":true}'}]},
            },
            {"ts": ms(8), "kind": "tool_call", "tool_call_id": "t2", "name": "compile", "args": {}},
            {
                "ts": ms(8.2),
                "kind": "tool_result",
                "tool_call_id": "t2",
                "name": "compile",
                "result": {"isError": False, "content": [{"type": "text", "text": '{"ok":false}'}]},
            },
        ],
    )
    if finished:
        (directory / "submission.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "candidate": "#2",
                    "proxy": 60.5,
                    "tokens": 100,
                    "heartbeats": 301,
                    "verified_by": "cold compile",
                }
            )
        )
        (directory / "summary.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "theorem": theorem,
                    "model": "m1",
                    "stop_reason": "finished",
                    "cost": {
                        "spent_usd": 0.03,
                        "soft_cap_usd": 0.1,
                        "requests": 2,
                        "spent_after_best_usd": 0.0,
                        "bookkeeping_and_rejected_pct": 10.0,
                        "by_turn_type": {},
                    },
                    "cache": {"reuse_pct": 50.0},
                    "tools": {"results": 2, "error_total": 1},
                    "progress": {
                        "best_verified_candidate": {"candidate": "#2", "tokens": 100, "heartbeats": 301, "proxy": 60.5}
                    },
                }
            )
        )
    (directory / "state.json").write_text(
        json.dumps({"best": {"candidate": "#2", "proxy": 60.5, "tokens": 100, "heartbeats": 301}})
    )
    return directory


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        viewer_data._CACHE.clear()

    def test_hub_row_finished_run(self):
        directory = make_run(self.root, "camp1-Core.T-m1-r1")
        (self.root / "runs" / "pi-budget" / "camp1-campaign").mkdir()
        (self.root / "runs" / "pi-budget" / "camp1-campaign" / "camp1-Core.T-m1-r1.log").write_text("")
        campaign_name = viewer_data.campaign_of("camp1-Core.T-m1-r1", directory.parent)
        row = hub_row("camp1-Core.T-m1-r1", directory, campaign_name, now=T0 + 40.0)
        self.assertEqual(campaign_name, "camp1")
        self.assertEqual(row["status"], "finished")
        self.assertEqual(row["stop_reason"], "finished")
        self.assertEqual(row["best"]["proxy"], 60.5)
        self.assertEqual(row["delta_proxy"], round(60.5 - 33.33, 2))
        self.assertTrue(row["submission_info"]["cold_verified"])
        self.assertEqual((row["spent_usd"], row["requests"], row["tool_errors"]), (0.03, 2, 1))
        self.assertEqual(row["limit_usd"], 0.1)
        self.assertEqual(row["started"], T0)
        self.assertAlmostEqual(row["duration_s"], 31.0)

    def test_hub_row_live_and_stalled(self):
        directory = make_run(self.root, "live-run", finished=False)
        with patch.object(viewer_data, "build_summary", return_value={"tools": {"results": 7, "error_total": 0}}):
            live = hub_row("live-run", directory, None, now=T0 + 100.0)
            viewer_data._CACHE.clear()
            stalled = hub_row("live-run", directory, None, now=T0 + 31 + 3600)
        self.assertEqual((live["status"], live["finished"], live["stop_reason"]), ("live", False, None))
        self.assertEqual(live["tool_results"], 7)
        self.assertEqual(stalled["status"], "stalled")

    def test_hub_row_runtime_phase_and_check_freshness(self):
        directory = make_run(self.root, "runtime-run", finished=False)
        ledger = directory / "ledger.jsonl"
        with ledger.open("a") as handle:
            handle.write(json.dumps({"kind": "phase", "phase": "model", "status": "start", "ts": T0 + 10}) + "\n")
            handle.write(json.dumps({"kind": "evaluation", "mode": "fast", "ts": T0 + 20, "result": {"compat": {"v": {"passed": True}}}}) + "\n")
            handle.write(json.dumps({"kind": "evaluation", "mode": "full", "ts": T0 + 15, "result": {"compat": {"v": {"passed": True}}}}) + "\n")
            handle.write(json.dumps({"kind": "evaluation", "mode": "full", "ts": T0 + 29, "result": {"compat": {"v": {"passed": False}}}}) + "\n")
            handle.write(json.dumps({"kind": "phase", "phase": "autocheck", "phase_id": "ac-1", "status": "start", "ts": T0 + 11}) + "\n")
            handle.write(json.dumps({"kind": "phase", "phase": "autocheck", "phase_id": "ac-1", "status": "end", "ts": T0 + 12}) + "\n")
            handle.write(json.dumps({"kind": "phase", "phase": "autocheck", "phase_id": "ac-2", "status": "start", "ts": T0 + 13}) + "\n")
            handle.write(json.dumps({"kind": "job", "job_id": "j-1", "job": "full", "candidate_id": "x", "status": "start", "ts": T0 + 25}) + "\n")
        row = hub_row("runtime-run", directory, None, now=T0 + 30)
        self.assertEqual(row["phase"], "model")
        self.assertEqual((row["fast_check_age_s"], row["full_check_age_s"]), (10, 15))
        self.assertEqual(row["active_job_elapsed_s"], 5)
        self.assertFalse(row["full_check_stale"])
        self.assertEqual(row["active_checker"]["phase_id"], "ac-2")
        self.assertEqual(row["runtime_events"][-1]["kind"], "job")

    def test_stale_check_warning_requires_live_recent_fast_activity(self):
        finished = make_run(self.root, "old-finished")
        idle = make_run(self.root, "old-idle", finished=False)
        active = make_run(self.root, "active-fast", finished=False)
        with (active / "ledger.jsonl").open("a") as handle:
            handle.write(json.dumps(evaluation(T0 + 3500, "c2", "fast", 60.0)) + "\n")
        finished_row = hub_row("old-finished", finished, None, now=T0 + 3600)
        idle_row = hub_row("old-idle", idle, None, now=T0 + 3600)
        active_row = hub_row("active-fast", active, None, now=T0 + 3600)
        self.assertFalse(finished_row["fast_check_stale"])
        self.assertFalse(finished_row["full_check_stale"])
        self.assertFalse(idle_row["full_check_stale"])
        self.assertTrue(active_row["full_check_stale"])

    def test_hub_row_survives_empty_run_dir(self):
        directory = self.root / "runs" / "pi-budget" / "empty"
        directory.mkdir(parents=True)
        row = hub_row("empty", directory, None, now=5.0)
        self.assertEqual((row["status"], row["best"], row["spent_usd"]), ("live", None, 0))

    def test_dashboard_sections(self):
        directory = make_run(self.root, "r1")
        board = run_dashboard("r1", directory)
        self.assertEqual(
            [(r["mode"], r["proxy"], r["estimated_proxy"], r["best_verified"]) for r in board["scores"]],
            [("fast", None, 60.0, None), ("full", 60.5, None, 60.5)],
        )
        self.assertEqual(
            [(r["n"], r["candidate"], r["candidate_id"]) for r in board["scores"]], [(1, "#2", "c2"), (2, "#2", "c2")]
        )
        self.assertEqual(board["reference"], None)
        points = board["spend"]["points"]
        self.assertEqual([p["n"] for p in points], [1, 2])
        self.assertEqual([p["spent_usd"] for p in points], [0.01, 0.03])
        self.assertEqual(points[1]["parts"]["cache_read"], 0.005)
        self.assertEqual(points[1]["reuse_pct"], 89.6)  # 900 / (5 + 900 + 100)
        self.assertEqual(board["spend"]["limit_usd"], 0.1)
        self.assertEqual(
            [(t["name"], t["is_error"], t["duration_s"]) for t in board["tools"]],
            [("compile", False, 1.5), ("compile", True, 0.2)],
        )
        kinds = [c["kind"] for c in board["controls"]]
        self.assertEqual(kinds, ["limit", "finish", "control"])
        self.assertEqual(board["lean"]["paths"]["session"]["runs"], 2)
        self.assertEqual(board["lean"]["paths"]["cold"]["by_check"], {"probe": 1})
        self.assertTrue(board["lean"]["cold_verification"]["confirmed"])
        self.assertEqual(board["packet"], "kickoff packet text")

    def test_dashboard_builds_from_a_legacy_ledger_with_ideas_and_old_tool_names(self):
        directory = make_run(self.root, "legacy-run")
        old_tool = "arena_" + "probe"
        with (directory / "trace-journal.jsonl").open("a") as handle:
            for event in (
                {"ts": ms(9), "kind": "tool_call", "tool_call_id": "old", "name": old_tool, "args": {}},
                {"ts": ms(9.1), "kind": "tool_result", "tool_call_id": "old", "name": old_tool, "result": {}},
            ):
                handle.write(json.dumps(event) + "\n")
        board = run_dashboard("legacy-run", directory)
        self.assertNotIn("ideas", board)
        self.assertIn(old_tool, [tool["name"] for tool in board["tools"]])
        json.dumps(board)

    def test_tool_text_is_clipped(self):
        directory = make_run(self.root, "r2")
        write(
            directory / "trace-journal.jsonl",
            [
                {"ts": ms(0), "kind": "tool_call", "tool_call_id": "x", "name": "t", "args": {}},
                {
                    "ts": ms(0.1),
                    "kind": "tool_result",
                    "tool_call_id": "x",
                    "name": "t",
                    "text": "z" * 10000,
                    "result": {},
                },
            ],
        )
        tool = run_dashboard("r2", directory)["tools"][0]
        self.assertLess(len(tool["result"]), 4100)
        self.assertIn("more characters", tool["result"])

    def test_dashboard_is_live_until_summary_json(self):
        directory = make_run(self.root, "r3")
        (directory / "summary.json").unlink(missing_ok=True)
        board = run_dashboard("r3", directory)
        self.assertFalse(board["finished"])  # the live summary's default stop_reason must not read as done
        (directory / "summary.json").write_text(json.dumps({"stop_reason": "finished"}))
        self.assertTrue(run_dashboard("r3", directory)["finished"])


OBSERVATIONS = [
    {
        "id": "o1",
        "traceId": "tr1",
        "parentObservationId": None,
        "type": "SPAN",
        "name": "Conversational Turn",
        "startTime": "2026-10-08T05:00:00.000Z",
        "latency": 12.5,
        "level": "DEFAULT",
    },
    {
        "id": "o2",
        "traceId": "tr1",
        "parentObservationId": "o1",
        "type": "GENERATION",
        "name": "LLM Call",
        "model": "m1",
        "startTime": "2026-10-08T05:00:01.000Z",
        "latency": 4.0,
        "level": "DEFAULT",
        "inputUsage": 100,
        "outputUsage": 20,
        "usageDetails": {"cache_read_input_tokens": 80},
        "costDetails": {"total": 0.002},
        "totalCost": 0.002,
    },
    {
        "id": "o3",
        "traceId": "tr1",
        "parentObservationId": "o1",
        "type": "TOOL",
        "name": "Tool: compile",
        "startTime": "2026-10-08T05:00:06.000Z",
        "latency": 1.0,
        "level": "ERROR",
    },
]


class LangfuseTests(unittest.TestCase):
    def fake(self, calls, fail=False):
        def fetch(path, query):
            calls.append((path, query))
            if fail:
                raise LangfuseUnavailable("Langfuse is not reachable")
            if path == "/api/public/projects":
                return {"data": [{"id": "proj1"}]}
            return {"data": OBSERVATIONS, "meta": {}}

        return fetch

    def test_session_shape_links_and_cache(self):
        calls, now = [], [0.0]
        lf = Langfuse(fetch=self.fake(calls), base_url="http://lf.local", ttl=45, clock=lambda: now[0])
        first = lf.session("run 1", 1_791_000_000)
        self.assertTrue(first["available"])
        self.assertEqual(first["session_url"], "http://lf.local/project/proj1/sessions/run%201")
        trace = first["traces"][0]
        self.assertEqual(
            (trace["name"], trace["generations"], trace["tools"], trace["errors"]), ("Conversational Turn", 1, 1, 1)
        )
        self.assertEqual(trace["url"], "http://lf.local/project/proj1/traces/tr1")
        generation = next(o for o in first["observations"] if o["type"] == "GENERATION")
        self.assertEqual(
            (generation["cost_usd"], generation["cache_read_tokens"], generation["model"]), (0.002, 80, "m1")
        )
        self.assertEqual(first["totals"]["generations"], 1)
        query = next(q for p, q in calls if "observations" in p)
        self.assertEqual(query["sessionId"], "run 1")
        n = len(calls)
        lf.session("run 1")
        self.assertEqual(len(calls), n)  # cached
        now[0] = 100
        lf.session("run 1")
        self.assertGreater(len(calls), n)

    def test_unavailable_is_graceful_and_keeps_stale_data(self):
        calls, now = [], [0.0]
        good = Langfuse(fetch=self.fake(calls), base_url="http://lf.local", ttl=1, clock=lambda: now[0])
        good.session("r")
        good._fetch = self.fake(calls, fail=True)
        now[0] = 10
        stale = good.session("r")
        self.assertTrue(stale["available"] and stale["stale"])
        down = Langfuse(fetch=self.fake([], fail=True), base_url="http://lf.local")
        result = down.session("r")
        self.assertEqual((result["available"], result["error"]), (False, "Langfuse is not reachable"))
        self.assertIsNone(down.session_url("r"))

    def test_missing_config_reports_without_leaking(self):
        lf = Langfuse(config_path=Path("/nonexistent/langfuse.json"))
        result = lf.session("r")
        self.assertFalse(result["available"])
        self.assertNotIn("nonexistent", json.dumps(result))

    def test_shape_without_project(self):
        shaped = shape_langfuse("r", OBSERVATIONS, "http://lf.local", None)
        self.assertIsNone(shaped["session_url"])


def _request(request_id: str, ts_ms: int) -> dict:
    return {"kind": "request", "id": request_id, "ts": ts_ms, "post_hook": {"messages": []}}


def _call(request_id: str, tool_call_id: str, start_ms: int, end_ms: int, **result) -> list[dict]:
    delivered = result.get("delivered", "delivered body")
    footer = result.get("footer", "footer line")
    untrimmed = result.get("untrimmed", f"{delivered}\n{footer}")
    return [
        {
            "kind": "tool_call",
            "id": request_id,
            "ts": start_ms,
            "tool_call_id": tool_call_id,
            "name": result.get("name", "compile"),
            "args": result.get("args", {"steps": "s1"}),
        },
        {
            "kind": "tool_result",
            "id": request_id,
            "ts": end_ms,
            "tool_call_id": tool_call_id,
            "name": result.get("name", "compile"),
            "trimmed": result.get("trimmed", False),
            "text": untrimmed,
            "delivered_text": delivered,
            "footer": footer,
            "is_error": result.get("is_error", False),
            "result": {
                "isError": result.get("is_error", False),
                "content": [
                    {"type": "text", "text": delivered},
                    {"type": "text", "text": footer},
                ],
            },
        },
    ]


def _response(request_id: str, ts_ms: int) -> dict:
    return {
        "kind": "response",
        "id": request_id,
        "ts": ts_ms,
        "content": [
            {"type": "thinking", "thinking": "because the step is shorter"},
            {"type": "text", "text": "filed the splice"},
        ],
    }


def _candidate(ts: float, ident: str, origin: str, **extra) -> dict:
    return {"kind": "candidate", "ts": ts, "candidate_id": ident, "origin": origin, "parents": [], **extra}


class NodeCallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def _write(self, journal: list[dict], ledger: list[dict]) -> None:
        write(self.directory / "trace-journal.jsonl", journal)
        write(self.directory / "ledger.jsonl", ledger)

    def test_v7_node_returns_its_call_reasoning_and_siblings_in_time_order(self):
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "t1", 2000, 4000, delivered="delivered body", untrimmed="delivered body\nfooter line"),
                _response("r1", 4500),
            ],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", parents=["ref"], tool_call_id="t1"),
                _candidate(2.6, "c3", "model", parents=["ref"], tool_call_id="t1"),
            ],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual(found["node"], "n2")
        self.assertEqual(found["turn"], 1)
        self.assertEqual(
            found["call"],
            {
                "tool_call_id": "t1",
                "name": "compile",
                "args": {"steps": "s1"},
                "delivered": "delivered body",
                "untrimmed": "delivered body\nfooter line",
                "trimmed": False,
                "footer": "footer line",
                "is_error": False,
            },
        )
        self.assertEqual(
            found["reasoning"],
            [
                {"type": "thinking", "text": "because the step is shorter"},
                {"type": "text", "text": "filed the splice"},
            ],
        )
        self.assertEqual(found["siblings"], ["c3"])
        self.assertNotIn("reason", found)

    def test_v6_time_window_joins_the_enclosing_call_and_lists_the_batch(self):
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "t1", 2000, 4000, name="arena_probe", args={"draft": "a"}),
                _response("r1", 4500),
                _request("r2", 6000),
                *_call("r2", "t2", 7000, 9000, name="compile", args={}),
                _response("r2", 9500),
            ],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", parents=["ref"]),
                _candidate(2.7, "c3", "model", parents=["ref"]),
                _candidate(8.0, "c4", "model", parents=["c2"]),
            ],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual(found["call"]["tool_call_id"], "t1")
        self.assertEqual(found["call"]["name"], "arena_probe")
        self.assertEqual(found["siblings"], ["c3"])
        self.assertNotIn("origin_line", found)
        self.assertNotIn("holes", found)
        later = viewer_data.node_calls(self.directory, "n4")
        self.assertEqual(later["call"]["tool_call_id"], "t2")
        self.assertEqual(later["siblings"], [])

    def test_trimmed_result_keeps_delivered_and_untrimmed_apart(self):
        self._write(
            [
                _request("r1", 1000),
                *_call(
                    "r1",
                    "t1",
                    2000,
                    4000,
                    trimmed=True,
                    delivered="alpha",
                    untrimmed="alpha\nbeta",
                    footer="budget line",
                ),
                _response("r1", 4500),
            ],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", tool_call_id="t1"),
            ],
        )
        call = viewer_data.node_calls(self.directory, "n2")["call"]
        self.assertTrue(call["trimmed"])
        self.assertEqual(call["delivered"], "alpha")
        self.assertEqual(call["untrimmed"], "alpha\nbeta")
        self.assertEqual(call["footer"], "budget line")

    def test_a_run_without_a_journal_does_not_raise(self):
        write(self.directory / "ledger.jsonl", [_candidate(1.0, "ref", "reference")])
        found = viewer_data.node_calls(self.directory, "n1")
        self.assertEqual(found["reason"], "no journal")
        self.assertIsNone(found["call"])
        self.assertEqual(found["lineage"], "missing")
        self.assertEqual(found["records"], [])
        self.assertEqual(found["artifact"]["missing"], True)

    def test_reference_and_unknown_nodes_have_no_call(self):
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", tool_call_id="t1"),
                _candidate(9.0, "merged", "auto_merge"),
            ],
        )
        reference = viewer_data.node_calls(self.directory, "n1")
        self.assertEqual(reference["reason"], "harness-made")
        self.assertIsNone(reference["call"])
        self.assertEqual(viewer_data.node_calls(self.directory, "n3")["reason"], "harness-made")
        missing = viewer_data.node_calls(self.directory, "n9")
        self.assertEqual(missing["reason"], "no call matched")
        self.assertIsNone(missing["call"])

    def test_two_enclosing_calls_return_the_earliest_and_say_ambiguous(self):
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "early", 2000, 5000, name="compile", delivered="early"),
                *_call("r1", "late", 3000, 4000, name="goal", delivered="late"),
                _response("r1", 5500),
            ],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(3.5, "c2", "model"),
            ],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual(found["reason"], "ambiguous")
        self.assertEqual(found["call"]["tool_call_id"], "early")
        self.assertEqual(found["call"]["name"], "compile")

    def test_v8_node_retains_alternate_actor_attempts(self):
        proof = "theorem t : True := by\n  trivial\n"
        (self.directory / "proofs").mkdir()
        (self.directory / "proofs" / "ref.lean").write_text("theorem t : True := by\n  sorry\n")
        (self.directory / "proofs" / "c2.lean").write_text(proof)
        sol = {
            "kind": "derivation",
            "proof_id": "c2",
            "candidate_id": "c2",
            "actor_id": "sol",
            "session_id": "sol-session",
            "parents": ["ref"],
            "event_id": "der-sol",
            "data": {"relation": "exact", "operation": {"type": "edited_from"}, "inputs": [{"role": "parent", "id": "ref"}]},
        }
        worker = {
            "kind": "derivation",
            "proof_id": "c2",
            "candidate_id": "c2",
            "actor_id": "worker-a",
            "session_id": "worker-session",
            "parents": ["ref"],
            "event_id": "der-worker",
            "data": {"relation": "exact", "operation": {"type": "filled_from"}, "inputs": [{"role": "parent", "id": "ref"}]},
        }
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "call-sol", 2000, 4000, delivered="sol body", untrimmed="sol body\nfull"),
                _response("r1", 4500),
                _request("r2", 5000),
                *_call("r2", "call-worker", 6000, 8000, delivered="worker body", untrimmed="worker body\nfull"),
                _response("r2", 8500),
            ],
            [
                {"kind": "init", "theorem": "T", "ts": 0.1, "versions": ["v1"]},
                _candidate(1.0, "ref", "reference"),
                {
                    "kind": "candidate",
                    "ts": 1.5,
                    "candidate_id": "ghost",
                    "origin": "model",
                    "operation_id": "uncommitted-op",
                    "parents": ["ref"],
                },
                _candidate(2.5, "c2", "model", parents=["ref"], tool_call_id="call-sol"),
                {
                    "kind": "attempt",
                    "proof_id": "c2",
                    "operation_id": "uncommitted-op",
                    "actor_id": "ghost",
                    "session_id": "ghost-session",
                    "event_id": "try-ghost",
                    "tool_call_id": "call-ghost",
                    "data": {"relation": "exact"},
                },
                {
                    "kind": "attempt",
                    "proof_id": "c2",
                    "candidate_id": "c2",
                    "actor_id": "sol",
                    "session_id": "sol-session",
                    "event_id": "try-sol",
                    "tool_call_id": "call-sol",
                    "data": {"relation": "exact"},
                },
                sol,
                {
                    "kind": "attempt",
                    "proof_id": "c2",
                    "candidate_id": "c2",
                    "actor_id": "worker-a",
                    "session_id": "worker-session",
                    "event_id": "try-worker",
                    "tool_call_id": "call-worker",
                    "data": {"relation": "exact"},
                },
                worker,
                {"kind": "job", "job_id": "j-cancel", "status": "cancelled", "actor_id": "worker-a", "candidate_id": "c2"},
                {"kind": "job", "job_id": "j-fail", "status": "failed", "actor_id": "sol", "candidate_id": "c2"},
                {"kind": "job", "job_id": "j-dup", "status": "duplicate", "actor_id": "worker-a", "candidate_id": "c2"},
                {
                    "kind": "scratch",
                    "experiment_id": "ex1",
                    "phase": "input",
                    "actor_id": "sol",
                    "proof_id": "c2",
                    "code": "exact scratch\n",
                },
            ],
        )
        (self.directory / "cost-ledger.jsonl").write_text(
            '{"kind":"settle","id":"req-1","request_id":"req-1","usd":0.2,"actor_id":"sol","job_id":"j-fail"}\n'
            '{"kind":"settle","id":"req-1","request_id":"req-1","usd":0.2,"actor_id":"sol","job_id":"j-fail","candidate_ids":["c2","c2b"]}\n'
            '{"kind":"settle","request_id":"req-unknown","usd":9,"usage_known":false}\n'
            '{"kind":"settle","usd":1\n'
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual(sorted(item["actor_id"] for item in found["attempts"]), ["sol", "worker-a"])
        self.assertEqual(
            sorted(item["actor_id"] for item in found["derivations"] if item.get("source") == "derivation"),
            ["sol", "worker-a"],
        )
        self.assertEqual(found["call"]["delivered"], "sol body")
        self.assertEqual(found["call"]["untrimmed"], "sol body\nfull")
        self.assertEqual(found["artifact"]["bytes"], proof)
        stored = {item["line"] for item in found["records"]}
        ledger = (self.directory / "ledger.jsonl").read_text()
        self.assertIn(json.dumps(sol) + "\n", stored)
        self.assertIn(json.dumps(worker) + "\n", stored)
        self.assertTrue(all(line in ledger for line in stored))
        self.assertEqual([item["actor_id"] for item in found["attempts"]], ["sol", "worker-a"])
        self.assertFalse(any("ghost" in line for line in stored))
        self.assertEqual(
            [(item["tool_call_id"], item["call"]["delivered"]) for item in found["call_refs"]],
            [("call-sol", "sol body"), ("call-worker", "worker body")],
        )
        self.assertIn("job_id", found["call_refs"][0])
        self.assertIn("request_id", found["call_refs"][0])
        self.assertIn("evaluation_id", found["call_refs"][0])
        with patch("arena.campaign.run_dir", return_value=self.directory), patch(
            "arena.cli.serve.run_dir", return_value=self.directory
        ):
            payload = server.graph_payload("served")
        proofs = [node for node in payload["nodes"] if node["id"] == "c2"]
        self.assertEqual(len(proofs), 1)
        self.assertEqual(sorted(item["actor_id"] for item in proofs[0]["attempts"]), ["sol", "worker-a"])
        self.assertEqual(
            [row["status"] for row in payload["job_log"]],
            ["cancelled", "failed", "duplicate"],
        )
        self.assertEqual(payload["experiments"][0]["experiment_id"], "ex1")
        self.assertEqual(payload["spend"]["total"], "0.2")
        self.assertEqual(payload["spend"]["by_actor"], {"sol": "0.2"})
        self.assertEqual(payload["spend"]["by_job"], {"j-fail": "0.2"})
        self.assertEqual(payload["spend"]["accounting"], "unknown")
        self.assertEqual(payload["cost"]["spent_usd"], 0.2)
        self.assertEqual(payload["cost"]["authority"], payload["spend"]["authority"])

    def test_v7_edge_rebuilds_the_filing_line_and_holes(self):
        proof = "theorem t : True := by\n  have h : True := sorry\n"
        (self.directory / "proofs").mkdir()
        (self.directory / "proofs" / "c2.lean").write_text(proof)
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", parents=["ref"], tool_call_id="t1"),
                {
                    "kind": "edge",
                    "proof_id": "c2",
                    "type": "edited_from",
                    "from": ["ref"],
                    "exact": True,
                    "operation": {"type": "edited_from", "from": ["ref"], "steps": "s1"},
                },
                {
                    "kind": "evaluation",
                    "candidate_id": "c2",
                    "mode": "primary",
                    "ts": 2.8,
                    "result": {"compat": {"v1": {"passed": True}}},
                },
            ],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual(found["origin_line"], "n2 made from n1 by replacing steps s1")
        self.assertEqual(found["ids"], {"n2": "c2", "n1": "ref"})
        self.assertEqual(found["holes"], [{"id": "n2.h1", "goal": "True", "status": "open", "fills": []}])

    def test_oversized_call_text_is_cut_with_the_replay_marker(self):
        extra = 10_000
        huge = "u" * (200 * 1024 + extra)
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "t1", 2000, 4000, delivered="short", untrimmed=huge, footer="foot"),
                _response("r1", 4500),
            ],
            [_candidate(1.0, "ref", "reference"), _candidate(2.5, "c2", "model", tool_call_id="t1")],
        )
        call = viewer_data.node_calls(self.directory, "n2")["call"]
        self.assertEqual(call["delivered"], "short")
        self.assertTrue(call["untrimmed"].endswith(f"[truncated: {extra} more characters; use arena replay]"))
        self.assertLess(len(call["untrimmed"]), len(huge))

    def test_tool_call_id_finds_a_node_filed_outside_every_call_window(self):
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "t1", 2000, 4000, name="compile"),
                _response("r1", 4500),
                _request("r2", 6000),
                *_call("r2", "t2", 7000, 9000, name="goal"),
                _response("r2", 9500),
            ],
            # Filed long after both calls returned: no time window encloses it.
            [_candidate(1.0, "ref", "reference"), _candidate(100.0, "c2", "model", tool_call_id="t2")],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        self.assertEqual((found["turn"], found["call"]["tool_call_id"], found["call"]["name"]), (2, "t2", "goal"))
        self.assertNotIn("reason", found)

    def test_a_node_is_found_by_its_proof_id_and_a_unique_prefix(self):
        reference, child = "a" * 64, "0f" * 32
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [_candidate(1.0, reference, "reference"), _candidate(2.5, child, "model", tool_call_id="t1")],
        )
        for ref in (child, child[:8]):
            found = viewer_data.node_calls(self.directory, ref)
            self.assertEqual((found["node"], found["call"]["tool_call_id"]), (ref, "t1"))
        self.assertEqual(viewer_data.node_calls(self.directory, reference)["reason"], "harness-made")

    def test_siblings_follow_ledger_time_not_filing_order(self):
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", tool_call_id="t1"),
                _candidate(2.9, "late", "model", tool_call_id="t1"),
                _candidate(2.7, "early", "model", tool_call_id="t1"),
            ],
        )
        self.assertEqual(viewer_data.node_calls(self.directory, "n2")["siblings"], ["early", "late"])
        self.assertEqual(viewer_data.node_calls(self.directory, "n3")["siblings"], ["c2", "early"])

    def test_oversized_delivered_args_and_reasoning_are_cut_with_the_replay_marker(self):
        extra = 777
        huge = "d" * (200 * 1024 + extra)
        response = _response("r1", 4500)
        response["content"] = [{"type": "thinking", "thinking": huge}, {"type": "text", "text": "short reply"}]
        self._write(
            [
                _request("r1", 1000),
                *_call("r1", "t1", 2000, 4000, delivered=huge, untrimmed="short", args={"steps": huge}),
                response,
            ],
            [_candidate(1.0, "ref", "reference"), _candidate(2.5, "c2", "model", tool_call_id="t1")],
        )
        found = viewer_data.node_calls(self.directory, "n2")
        marker = f"[truncated: {extra} more characters; use arena replay]"
        self.assertTrue(found["call"]["delivered"].endswith(marker))
        self.assertEqual(found["call"]["untrimmed"], "short")
        self.assertTrue(found["reasoning"][0]["text"].endswith(marker))
        self.assertEqual(found["reasoning"][1]["text"], "short reply")
        args = found["call"]["args"]
        self.assertIsInstance(args, str)
        serialized = json.dumps({"steps": huge})
        self.assertTrue(args.endswith(f"[truncated: {len(serialized) - 200 * 1024} more characters; use arena replay]"))
        self.assertTrue(serialized.startswith(args.split("\n[truncated")[0]))

    def test_a_half_written_last_journal_line_is_skipped(self):
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [_candidate(1.0, "ref", "reference"), _candidate(2.5, "c2", "model", tool_call_id="t1")],
        )
        with (self.directory / "trace-journal.jsonl").open("a") as journal:
            journal.write('{"kind": "tool_call", "id": "r2", "ts": 50')
        self.assertEqual(viewer_data.node_calls(self.directory, "n2")["call"]["tool_call_id"], "t1")

    def test_journal_is_read_once_until_it_changes(self):
        journal = self.directory / "trace-journal.jsonl"
        self._write(
            [_request("r1", 1000), *_call("r1", "t1", 2000, 4000), _response("r1", 4500)],
            [
                _candidate(1.0, "ref", "reference"),
                _candidate(2.5, "c2", "model", tool_call_id="t1"),
                _candidate(20.0, "c3", "model", tool_call_id="t2"),
            ],
        )
        original = Path.read_text
        reads = []

        def counting(path, *args, **kwargs):
            if path == journal:
                reads.append(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=counting):
            self.assertEqual(viewer_data.node_calls(self.directory, "n2")["call"]["tool_call_id"], "t1")
            self.assertEqual(viewer_data.node_calls(self.directory, "n3")["reason"], "no call matched")
            self.assertEqual(len(reads), 1)
            with journal.open("a") as handle:
                handle.write(
                    "".join(
                        json.dumps(row) + "\n"
                        for row in [_request("r2", 10_000), *_call("r2", "t2", 11_000, 12_000, name="goal")]
                    )
                )
            later = viewer_data.node_calls(self.directory, "n3")
        self.assertEqual(len(reads), 2)
        self.assertEqual((later["turn"], later["call"]["name"]), (2, "goal"))


class ServerTests(unittest.TestCase):
    def test_endpoints_and_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            viewer_data._CACHE.clear()
            make_run(root, "v6x-Core.T-m1-r1")
            lf = Langfuse(
                fetch=lambda path, query: (
                    {"data": [{"id": "proj1"}]} if "projects" in path else {"data": OBSERVATIONS, "meta": {}}
                ),
                base_url="http://lf.local",
            )
            with patch.object(campaign, "ROOT", root):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(server.Runs([], "v6x*"), lf))
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                self.addCleanup(httpd.server_close)
                self.addCleanup(httpd.shutdown)
                base = f"http://127.0.0.1:{httpd.server_port}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        return response.read().decode()

                rows = json.loads(get("/runs.json"))
                self.assertEqual([r["run_id"] for r in rows], ["v6x-Core.T-m1-r1"])
                self.assertEqual(rows[0]["langfuse_url"], "http://lf.local/project/proj1/sessions/v6x-Core.T-m1-r1")
                run = "/run/v6x-Core.T-m1-r1/"
                self.assertEqual(json.loads(get(run + "dashboard.json"))["packet"], "kickoff packet text")
                self.assertTrue(json.loads(get(run + "langfuse.json"))["available"])
                for page in (
                    "",
                    "dashboard.html",
                    "dashboard.js",
                    "charts.js",
                    "dashboard.css",
                    "app.js",
                    "style.css",
                    "highlight.js",
                ):
                    self.assertTrue(get(run + page))
                for page in ("", "hub.js", "hub.css"):
                    self.assertTrue(get("/" + page))
                with self.assertRaises(urllib.error.HTTPError):
                    get("/run/nope/dashboard.json")

    def test_node_endpoint_serves_a_call_and_rejects_a_bad_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            viewer_data._CACHE.clear()
            directory = make_run(root, "v6x-Core.T-m1-r1")
            # A second candidate sits inside the only tool call, so the endpoint has a real call to return.
            write(
                directory / "trace-journal.jsonl",
                [
                    _request("r1", ms(1)),
                    *_call("r1", "t1", ms(1.5), ms(4), delivered="ok", untrimmed="ok\nfoot", footer="foot"),
                    _response("r1", ms(5)),
                ],
            )
            with patch.object(campaign, "ROOT", root):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(server.Runs([], "v6x*")))
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                self.addCleanup(httpd.server_close)
                self.addCleanup(httpd.shutdown)
                base = f"http://127.0.0.1:{httpd.server_port}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        return response.status, response.headers["Content-Type"], response.read().decode()

                status, content_type, body = get("/run/v6x-Core.T-m1-r1/node/n2.json")
                self.assertEqual(status, 200)
                self.assertEqual(content_type, "application/json; charset=utf-8")
                payload = json.loads(body)
                self.assertEqual(payload["call"]["name"], "compile")
                self.assertEqual(payload["node"], "n2")
                missing_status, _, missing_body = get("/run/v6x-Core.T-m1-r1/node/n9.json")
                self.assertEqual(missing_status, 200)
                self.assertEqual(json.loads(missing_body)["reason"], "no call matched")
                for path in (
                    "/run/v6x-Core.T-m1-r1/node/a/b.json",
                    "/run/v6x-Core.T-m1-r1/node/n..2.json",
                    "/run/v6x-Core.T-m1-r1/node/%232.json",
                ):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        get(path)
                    self.assertEqual(caught.exception.code, 404)

    def test_single_run_server_serves_node_calls_at_the_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = make_run(root, "v6x-Core.T-m1-r1")
            write(
                directory / "trace-journal.jsonl",
                [_request("r1", ms(1)), *_call("r1", "t1", ms(1.5), ms(4), name="goal"), _response("r1", ms(5))],
            )
            with patch.object(campaign, "ROOT", root):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(server.Runs(["v6x-Core.T-m1-r1"])))
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                self.addCleanup(httpd.server_close)
                self.addCleanup(httpd.shutdown)
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/node/n2.json") as response:
                    payload = json.loads(response.read().decode())
        self.assertEqual((payload["node"], payload["call"]["name"]), ("n2", "goal"))


class AssetTests(unittest.TestCase):
    """The viewer is desktop only and must never fail silently into an empty chart."""

    ASSETS = Path(server.__file__).resolve().parents[1] / "graph_viewer"

    def test_no_mobile_breakpoints(self):
        for name in ("hub.css", "dashboard.css", "style.css"):
            self.assertNotIn(
                "max-width:",
                "".join(line for line in (self.ASSETS / name).read_text().splitlines() if "@media" in line),
                name,
            )

    def test_charts_report_draw_failures_and_scripts_parse(self):
        self.assertIn("Chart failed to draw", (self.ASSETS / "charts.js").read_text())
        node = shutil.which("node")
        if node:
            for name in ("charts.js", "dashboard.js", "hub.js", "app.js", "highlight.js"):
                result = subprocess.run([node, "--check", str(self.ASSETS / name)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_lean_highlighter_marks_keywords_comments_and_blocks(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        script = (
            "global.window = {}; require(process.argv[1]); "
            "console.log(window.LeanHL.block('theorem t : 1 = 1 := by\\n  exact ⟨rfl⟩ -- ok\\n  /- a\\n b -/ sorry'))"
        )
        result = subprocess.run([node, "-e", script, str(self.ASSETS / "highlight.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in (
            'tk-kw">theorem',
            'tk-tac">exact',
            'tk-br">⟨',
            'tk-cm">-- ok',
            'tk-sorry">sorry',
            'tk-cm"> b -/',
        ):
            self.assertIn(expected, result.stdout)


class GraphViewerUpgradeTests(unittest.TestCase):
    """Probe rows for the graph and the static-asset rules (CSP, no rebuilt dropdowns)."""

    ASSETS = server.ASSETS

    def probe(self, ident, parent, passed, message, goals=0):
        diagnostics = [{"severity": "warning" if passed else "error", "message": message}]
        compat = {
            "v1": {
                "passed": passed,
                "heartbeats": 5,
                "diagnostics": diagnostics,
                "diagnostic_counts": {"errors": 0 if passed else 1},
                "goals": [{"goals": "x : Nat"}] * goals,
            }
        }
        return {
            "proof_id": ident,
            "parent": parent,
            "ts": 1.0,
            "result": {"tokens": 12, "compat": compat},
        }

    def test_slim_probes_classify_route_and_drop_diagnostics(self):
        payload = {
            "nodes": [{"id": "c1"}],
            "probes": [
                self.probe("p1", "c1", True, "declaration uses `sorry`", goals=2),
                self.probe("p2", "c1", False, "type mismatch"),
                self.probe("p3", "c1", True, "unused variable"),
                self.probe("c1", None, True, "x"),
            ],
        }
        history = [{"kind": "route", "proof_id": "p3", "route": "r2"}]
        rows = {row["proof_id"]: row for row in server.slim_probes(payload, history)}
        self.assertEqual(set(rows), {"p1", "p2", "p3"})  # a probe that became a candidate is the node's job
        self.assertEqual((rows["p1"]["status"], rows["p1"]["goals"]), ("skeleton", 2))
        self.assertEqual((rows["p2"]["status"], rows["p2"]["errors"]), ("fail", 1))
        self.assertEqual((rows["p3"]["status"], rows["p3"]["route"]), ("pass", "r2"))
        self.assertEqual(rows["p2"]["headlines"], ["type mismatch"])
        self.assertNotIn("diagnostics", rows["p1"]["result"]["compat"]["v1"])

    def test_assets_keep_csp_rules_and_do_not_rebuild_open_selects(self):
        for name in ("index.html", "dashboard.html", "hub.html"):
            self.assertNotRegex((self.ASSETS / name).read_text(), r"\sstyle\s*=", name)
        for name in ("app.js", "dashboard.js", "hub.js"):
            self.assertNotRegex((self.ASSETS / name).read_text(), r'style\s*=\s*\\?"', name)
        graph = (self.ASSETS / "index.html").read_text()
        self.assertNotIn("<select", graph)  # route/idea/kind/status filters are chips and a legend, not dropdowns
        hub = (self.ASSETS / "hub.js").read_text()
        self.assertIn("dataset.sig", hub)
        self.assertIn("document.activeElement !== select", hub)
        self.assertIn("document.activeElement", (self.ASSETS / "dashboard.js").read_text())

    # app.js's IIFE needs a DOM and stops at its first `location` access; the top-level helpers are declared before.
    CALLS = (
        "const vm = require('vm'), fs = require('fs'), ctx = vm.createContext({});"
        "try { vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx); } catch {}"
        "ctx.payload = JSON.parse(process.argv[2]);"
        "ctx.go = process.argv[3] === 'link' ? id => `<b class=go>${id}</b>` : () => '';"
        "console.log(vm.runInContext('callsHtml(payload, go)', ctx));"
    )

    def calls_html(self, payload: dict, link: bool = False) -> str:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        argv = [node, "-e", self.CALLS, str(self.ASSETS / "app.js"), json.dumps(payload), "link" if link else ""]
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_calls_tab_escapes_every_fetched_field(self):
        bad = "<img src=x onerror=1>"
        payload = {
            "node": bad,
            "turn": bad,
            "reason": bad,
            "origin_line": f"n2 <- n1 {bad}",
            "ids": {"n1": bad},
            "reasoning": [{"type": "thinking", "text": bad}],
            "call": {
                "name": bad,
                "args": {"steps": bad},
                "delivered": bad,
                "untrimmed": bad,
                "trimmed": True,
                "footer": bad,
            },
            "holes": [{"id": bad, "goal": bad, "status": bad, "fills": [bad]}],
            "siblings": [bad],
        }
        html = self.calls_html(payload)
        self.assertNotIn("<img", html)
        # turn, reason, origin line, thinking, name, args, delivered, untrimmed, footer, 4 hole cells, sibling
        self.assertEqual(html.count("&lt;img"), 14)

    def test_calls_tab_links_graph_ids_it_can_resolve(self):
        payload = {
            "turn": 1,
            "origin_line": "n2 <- n1, n7 splice s1",
            "ids": {"n1": "proof-one", "n7": "proof-seven"},
            "holes": [{"id": "n2.h1", "goal": "True", "status": "filled", "fills": ["n7", "n9"]}],
            "siblings": ["proof-sib"],
        }
        html = self.calls_html(payload, link=True)
        self.assertIn("n2 &lt;- <b class=go>proof-one</b>, <b class=go>proof-seven</b> splice s1", html)
        self.assertIn("<td><b class=go>proof-seven</b> n9</td>", html)
        self.assertIn("<b class=go>proof-sib</b>", html)
        self.assertIn("<td>n2.h1</td>", html)

    def test_a_node_with_only_a_fast_check_is_labelled_not_checked_below_best(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        # `stat` and the status labels live inside app.js's IIFE, past its first `location` access: lift them out.
        script = (
            "const fs = require('fs'), source = fs.readFileSync(process.argv[1], 'utf8');"
            "const pick = re => source.match(re)[0];"
            "const code = [pick(/const STATUSES = .*/), pick(/const isProbe = .*/),"
            " pick(/function stat\\(it\\) \\{[\\s\\S]*?\\n  \\}/)].join('\\n');"
            "const nodes = JSON.parse(process.argv[2]);"
            "const run = new Function('nodes', code + '; return [nodes.map(stat), STATUSES];');"
            "console.log(JSON.stringify(run(nodes)));"
        )
        nodes = [
            {"status": "primary", "proof": "exact h", "evaluations": [{"mode": "fast"}]},
            {"status": "primary", "proof": "exact h", "evaluations": [{"mode": "fast"}, {"mode": "full"}]},
            {"status": "primary", "proof": "sorry", "evaluations": [{"mode": "fast"}]},
            {"status": "full", "proof": "exact h", "evaluations": [{"mode": "full"}]},
        ]
        result = subprocess.run(
            [node, "-e", script, str(self.ASSETS / "app.js"), json.dumps(nodes)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        statuses, labels = json.loads(result.stdout)
        self.assertEqual(statuses, ["unchecked", "compiled", "compiled", "verified"])
        self.assertIn(["unchecked", "Not checked: below best"], labels)

    def test_viewer_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        for name in ("app.js", "dashboard.js", "hub.js", "charts.js"):
            result = subprocess.run([node, "--check", str(self.ASSETS / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
