"""Offline tests for the run viewer's data shaping and server (no Langfuse network, no live runs)."""

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
from tools import serve_candidate_graph as server


T0 = 1_791_000_000


def ms(offset: float) -> int:
    return int((T0 + offset) * 1000)


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def evaluation(ts, candidate, mode, proxy, path="session", tokens=100, hb=300):
    metrics = {"compiled": True, "proxy": proxy if mode == "full" else None,
               "estimated_proxy": proxy if mode != "full" else None}
    return {"kind": "evaluation", "ts": ts, "candidate_id": candidate, "mode": mode, "result": {
        "tokens": tokens, "heartbeat": hb, "metrics": metrics,
        "compat": {"v1": {"passed": True, "heartbeats": hb, "lean": {"path": path, "seconds": 1.5}}}}}


def make_run(root: Path, run_id: str, finished: bool = True, theorem: str = "Core.T") -> Path:
    directory = root / "runs" / "pi-budget" / run_id
    directory.mkdir(parents=True)
    (directory / "run-config.json").write_text(json.dumps(
        {"theorem": theorem, "model": "m1", "thinking": "high", "hard_cap_usd": 0.1}))
    (directory / "packet.txt").write_text("kickoff packet text")
    write(directory / "ledger.jsonl", [
        {"kind": "init", "ts": T0 + 0.0, "theorem": theorem},
        {"kind": "candidate", "ts": T0 + 0.1, "candidate_id": "ref", "parents": [], "origin": "reference"},
        {"kind": "idea", "ts": T0 + 1, "id": "i1", "title": "Idea one", "hypothesis": "h", "status": "active"},
        {"kind": "candidate", "ts": T0 + 2, "candidate_id": "c2", "parents": ["ref"], "origin": "model", "idea_id": "i1"},
        {"kind": "probe", "ts": T0 + 3, "proof_id": "p1", "idea_id": "i1", "result": {"compat": {
            "v1": {"lean": {"path": "cold", "seconds": 4.0}}}}},
        evaluation(T0 + 10, "c2", "fast", 60.0), evaluation(T0 + 12, "c2", "full", 60.5),
        {"kind": "idea_update", "ts": T0 + 20, "id": "i1", "status": "succeeded", "reason": "worked"},
        {"kind": "cold_verification", "ts": T0 + 30, "candidate_id": "c2", "confirmed": True,
         "passed": {"v1": True}, "recorded_heartbeats": 300, "cold_heartbeats": 301}])
    write(directory / "cost-ledger.jsonl", [
        {"ts": ms(0.5), "kind": "gate", "id": "a", "decision": "allow"},
        {"ts": ms(5), "kind": "settle", "id": "a", "usd": 0.01, "usage_known": True,
         "tokens": {"input": 5, "output": 50, "cache_read": 0, "cache_write": 900},
         "ledger_components_usd": {"input": 0.001, "output": 0.004, "cacheRead": 0, "cacheWrite": 0.005}},
        {"ts": ms(20), "kind": "gate", "id": "b", "decision": "stop", "reason": "too big"},
        {"ts": ms(25), "kind": "settle", "id": "b", "usd": 0.02, "usage_known": True, "soft_overshoot_usd": 0.01,
         "tokens": {"input": 5, "output": 50, "cache_read": 900, "cache_write": 100},
         "ledger_components_usd": {"input": 0.001, "output": 0.004, "cacheRead": 0.005, "cacheWrite": 0.01}},
        {"ts": ms(30), "kind": "finish", "phase": "review"},
        {"ts": ms(31), "kind": "control", "stop": "finished"}])
    write(directory / "trace-journal.jsonl", [
        {"ts": ms(6), "kind": "tool_call", "tool_call_id": "t1", "name": "arena_evaluate", "args": {"x": 1}},
        {"ts": ms(7.5), "kind": "tool_result", "tool_call_id": "t1", "name": "arena_evaluate",
         "result": {"isError": False, "content": [{"type": "text", "text": "{\"ok\":true}"}]}},
        {"ts": ms(8), "kind": "tool_call", "tool_call_id": "t2", "name": "arena_probe", "args": {}},
        {"ts": ms(8.2), "kind": "tool_result", "tool_call_id": "t2", "name": "arena_probe",
         "result": {"isError": False, "content": [{"type": "text", "text": "{\"ok\":false}"}]}}])
    if finished:
        (directory / "submission.json").write_text(json.dumps(
            {"ok": True, "candidate": "#2", "proxy": 60.5, "tokens": 100, "heartbeats": 301, "verified_by": "cold compile"}))
        (directory / "summary.json").write_text(json.dumps({
            "run_id": run_id, "theorem": theorem, "model": "m1", "stop_reason": "finished",
            "cost": {"spent_usd": 0.03, "soft_cap_usd": 0.1, "requests": 2, "spent_after_best_usd": 0.0,
                     "bookkeeping_and_rejected_pct": 10.0, "by_turn_type": {}},
            "cache": {"reuse_pct": 50.0}, "tools": {"results": 2, "error_total": 1},
            "progress": {"best_verified_candidate": {"candidate": "#2", "tokens": 100, "heartbeats": 301, "proxy": 60.5}}}))
    (directory / "state.json").write_text(json.dumps(
        {"best": {"candidate": "#2", "proxy": 60.5, "tokens": 100, "heartbeats": 301}}))
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
        self.assertEqual((row["soft_cap_usd"], row["hard_cap_usd"]), (0.1, 3.0))
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

    def test_hub_row_survives_empty_run_dir(self):
        directory = self.root / "runs" / "pi-budget" / "empty"
        directory.mkdir(parents=True)
        row = hub_row("empty", directory, None, now=5.0)
        self.assertEqual((row["status"], row["best"], row["spent_usd"]), ("live", None, 0))

    def test_dashboard_sections(self):
        directory = make_run(self.root, "r1")
        board = run_dashboard("r1", directory)
        self.assertEqual([(r["mode"], r["proxy"], r["estimated_proxy"], r["best_verified"]) for r in board["scores"]],
                         [("fast", None, 60.0, None), ("full", 60.5, None, 60.5)])
        self.assertEqual([(r["n"], r["candidate"], r["candidate_id"]) for r in board["scores"]], [(1, "#2", "c2"), (2, "#2", "c2")])
        self.assertEqual(board["reference"], None)
        points = board["spend"]["points"]
        self.assertEqual([p["n"] for p in points], [1, 2])
        self.assertEqual([p["spent_usd"] for p in points], [0.01, 0.03])
        self.assertEqual(points[1]["parts"]["cache_read"], 0.005)
        self.assertEqual(points[1]["reuse_pct"], 89.6)  # 900 / (5 + 900 + 100)
        self.assertEqual((board["spend"]["soft_cap_usd"], board["spend"]["hard_cap_usd"]), (0.1, 3.0))
        self.assertEqual([(t["name"], t["is_error"], t["duration_s"]) for t in board["tools"]],
                         [("arena_evaluate", False, 1.5), ("arena_probe", True, 0.2)])
        idea = board["ideas"][0]
        self.assertEqual((idea["status"], idea["probes"], idea["best_proxy"], idea["reason"]), ("succeeded", 1, 60.5, "worked"))
        self.assertEqual(idea["attempts"], [{"candidate": "#2", "parents": ["#1"]}])
        kinds = [c["kind"] for c in board["controls"]]
        self.assertEqual(kinds, ["gate", "soft_cap", "finish", "control"])
        self.assertEqual(board["lean"]["paths"]["session"]["runs"], 2)
        self.assertEqual(board["lean"]["paths"]["cold"]["by_check"], {"probe": 1})
        self.assertTrue(board["lean"]["cold_verification"]["confirmed"])
        self.assertEqual(board["packet"], "kickoff packet text")
        json.dumps(board)

    def test_tool_text_is_clipped(self):
        directory = make_run(self.root, "r2")
        write(directory / "trace-journal.jsonl", [
            {"ts": ms(0), "kind": "tool_call", "tool_call_id": "x", "name": "t", "args": {}},
            {"ts": ms(0.1), "kind": "tool_result", "tool_call_id": "x", "name": "t", "text": "z" * 10000, "result": {}}])
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
    {"id": "o1", "traceId": "tr1", "parentObservationId": None, "type": "SPAN", "name": "Conversational Turn",
     "startTime": "2026-10-08T05:00:00.000Z", "latency": 12.5, "level": "DEFAULT"},
    {"id": "o2", "traceId": "tr1", "parentObservationId": "o1", "type": "GENERATION", "name": "LLM Call", "model": "m1",
     "startTime": "2026-10-08T05:00:01.000Z", "latency": 4.0, "level": "DEFAULT", "inputUsage": 100, "outputUsage": 20,
     "usageDetails": {"cache_read_input_tokens": 80}, "costDetails": {"total": 0.002}, "totalCost": 0.002},
    {"id": "o3", "traceId": "tr1", "parentObservationId": "o1", "type": "TOOL", "name": "Tool: arena_probe",
     "startTime": "2026-10-08T05:00:06.000Z", "latency": 1.0, "level": "ERROR"}]


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
        self.assertEqual((trace["name"], trace["generations"], trace["tools"], trace["errors"]),
                         ("Conversational Turn", 1, 1, 1))
        self.assertEqual(trace["url"], "http://lf.local/project/proj1/traces/tr1")
        generation = next(o for o in first["observations"] if o["type"] == "GENERATION")
        self.assertEqual((generation["cost_usd"], generation["cache_read_tokens"], generation["model"]), (0.002, 80, "m1"))
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


class ServerTests(unittest.TestCase):
    def test_endpoints_and_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            viewer_data._CACHE.clear()
            make_run(root, "v6x-Core.T-m1-r1")
            lf = Langfuse(fetch=lambda path, query: {"data": [{"id": "proj1"}]} if "projects" in path
                          else {"data": OBSERVATIONS, "meta": {}}, base_url="http://lf.local")
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
                for page in ("", "dashboard.html", "dashboard.js", "charts.js", "dashboard.css", "app.js", "style.css", "highlight.js"):
                    self.assertTrue(get(run + page))
                for page in ("", "hub.js", "hub.css"):
                    self.assertTrue(get("/" + page))
                with self.assertRaises(urllib.error.HTTPError):
                    get("/run/nope/dashboard.json")


class AssetTests(unittest.TestCase):
    """The viewer is desktop only and must never fail silently into an empty chart."""

    ASSETS = Path(server.__file__).resolve().parent / "graph_viewer"

    def test_no_mobile_breakpoints(self):
        for name in ("hub.css", "dashboard.css", "style.css"):
            self.assertNotIn("max-width:", "".join(
                line for line in (self.ASSETS / name).read_text().splitlines() if "@media" in line), name)

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
        script = ("global.window = {}; require(process.argv[1]); "
                  "console.log(window.LeanHL.block('theorem t : 1 = 1 := by\\n  exact ⟨rfl⟩ -- ok\\n  /- a\\n b -/ sorry'))")
        result = subprocess.run([node, "-e", script, str(self.ASSETS / "highlight.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ('tk-kw">theorem', 'tk-tac">exact', 'tk-br">⟨', 'tk-cm">-- ok', 'tk-sorry">sorry', 'tk-cm"> b -/'):
            self.assertIn(expected, result.stdout)


class GraphViewerUpgradeTests(unittest.TestCase):
    """Probe rows for the graph and the static-asset rules (CSP, no rebuilt dropdowns)."""
    ASSETS = server.ASSETS

    def probe(self, ident, parent, passed, message, goals=0):
        diagnostics = [{"severity": "warning" if passed else "error", "message": message}]
        compat = {"v1": {"passed": passed, "heartbeats": 5, "diagnostics": diagnostics,
                         "diagnostic_counts": {"errors": 0 if passed else 1}, "goals": [{"goals": "x : Nat"}] * goals}}
        return {"proof_id": ident, "idea_id": "i1", "parent": parent, "ts": 1.0,
                "result": {"tokens": 12, "compat": compat}}

    def test_slim_probes_classify_route_and_drop_diagnostics(self):
        payload = {"nodes": [{"id": "c1"}], "probes": [
            self.probe("p1", "c1", True, "declaration uses `sorry`", goals=2),
            self.probe("p2", "c1", False, "type mismatch"),
            self.probe("p3", "c1", True, "unused variable"),
            self.probe("c1", None, True, "x")]}
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
            self.assertNotRegex((self.ASSETS / name).read_text(), r'\sstyle\s*=', name)
        for name in ("app.js", "dashboard.js", "hub.js"):
            self.assertNotRegex((self.ASSETS / name).read_text(), r'style\s*=\s*\\?"', name)
        graph = (self.ASSETS / "index.html").read_text()
        self.assertNotIn("<select", graph)  # route/idea/kind/status filters are chips and a legend, not dropdowns
        hub = (self.ASSETS / "hub.js").read_text()
        self.assertIn("dataset.sig", hub)
        self.assertIn("document.activeElement !== select", hub)
        self.assertIn("document.activeElement", (self.ASSETS / "dashboard.js").read_text())

    def test_viewer_scripts_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        for name in ("app.js", "dashboard.js", "hub.js", "charts.js"):
            result = subprocess.run([node, "--check", str(self.ASSETS / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
