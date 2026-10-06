import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena.graph import common_base, merge_text, ranked_frontier
from arena import campaign
from tools.build_candidate_graph import build_snapshot
from tools.serve_candidate_graph import graph_payload
from tools.run_pi_budgeted import attempt_has_model_error


class MergeTests(unittest.TestCase):
    def test_disjoint_changes_combine_exactly(self):
        base = "theorem t := by\n  intro x\n  have h := x\n  exact h\n"
        left = "theorem t := by\n  intro x\n  have h : _ := x\n  exact h\n"
        right = "theorem t := by\n  intro x\n  have h := x\n  simpa using h\n"
        result = merge_text(base, left, right)
        self.assertEqual(result["text"], "theorem t := by\n  intro x\n  have h : _ := x\n  simpa using h\n")
        self.assertEqual(len(result["left_edits"]), 1)
        self.assertEqual(len(result["right_edits"]), 1)

    def test_overlapping_and_same_point_insertions_are_not_guessed(self):
        base = "a\nb\nc\n"
        self.assertEqual(merge_text(base, "a\nB\nc\n", "a\nC\nc\n")["reason"], "overlapping_edits")
        self.assertEqual(merge_text(base, "a\nx\nb\nc\n", "a\ny\nb\nc\n")["reason"], "overlapping_edits")

    def test_unique_common_base_required(self):
        parents = {"o": [], "a": ["o"], "b": ["o"], "c": ["a", "b"], "d": ["a", "b"]}
        self.assertEqual(common_base("c", "d", parents), {"base": None, "reason": "ambiguous_common_base"})
        self.assertEqual(common_base("a", "c", parents)["base"], "a")


class FrontierTests(unittest.TestCase):
    def test_frontier_rotates_from_saturated_lineage(self):
        nodes = [
            {"id": "a", "parents": [], "status": "full", "local_proxy": 70, "tokens": 150, "attempts_since_gain": 6, "children": ["a1"]},
            {"id": "b", "parents": [], "status": "full", "local_proxy": 68, "tokens": 152, "attempts_since_gain": 0, "children": []},
        ]
        ranked = ranked_frontier(nodes)
        self.assertEqual(ranked[0]["candidate_id"], "b")
        self.assertIn("saturation", ranked[0]["priority"])


class WorkerTests(unittest.TestCase):
    def test_primary_compile_failure_is_materialized_for_lean_repair(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "validate_proof"), \
             patch.object(campaign, "versions", return_value=[("v1", "a")]), \
             patch.object(campaign, "evaluate", return_value={"ok": True, "tokens": 4,
                 "compat": {"v1": {"passed": False, "diagnostics": "exact goal"}}}), \
             patch.object(campaign, "materialize", return_value={"candidate_path": "scratch.lean"}) as live:
            campaign._append(campaign.run_dir("repair"), {"kind": "init", "theorem": "T"})
            result = campaign.record_evaluation("T", "repair", "theorem t := by\n  bad", "fast")
            self.assertEqual(result["candidate_path"], "scratch.lean")
            live.assert_called_once()

    def test_new_good_nodes_merge_without_touching_live_candidate(self):
        base = "theorem t := by\n  intro x\n  have h := x\n  exact h\n"
        left = base.replace("have h := x", "have h : _ := x")
        right = base.replace("exact h", "simpa using h")
        def fake_eval(_name, proof, mode, known=None):
            compat = {"v1": {"passed": True}}
            if mode == "full":
                compat.update({"v2": {"passed": True}, "v3": {"passed": True}})
            return {"ok": True, "tokens": len(proof), "heartbeat": 3,
                    "local_proxy": 50 if mode == "full" else None, "compat": compat}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "validate_proof"), \
             patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b"), ("v3", "c")]), \
             patch.object(campaign, "evaluate", side_effect=fake_eval), \
             patch.object(campaign, "materialize") as live:
            directory = campaign.run_dir("test")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "test", base, "full", materialize_live=False)["candidate_id"]
            a = campaign.record_evaluation("T", "test", left, "full", [root], materialize_live=False)["candidate_id"]
            b = campaign.record_evaluation("T", "test", right, "full", [root], materialize_live=False)["candidate_id"]
            first = campaign.merge_once("test")
            self.assertEqual(first["reason"], "no_independent_edits")
            outcome = campaign.merge_once("test")
            self.assertEqual(outcome["parents"], sorted([a, b]))
            self.assertTrue(outcome["full_passed"])
            child = next(n for n in campaign.graph_state("test")["nodes"] if n["id"] == outcome["candidate_id"])
            self.assertEqual(child["origin"], "auto_merge")
            self.assertEqual(child["merge"]["base"], root)
            self.assertEqual(child["parents"], sorted([a, b]))
            live.assert_not_called()
            self.assertIsNotNone(campaign.merge_once("test"))

    def test_worker_checks_every_open_good_pair_and_deduplicates_combinations(self):
        base = "theorem t := by\n  a\n  b\n  c\n"
        def fake_eval(_name, proof, mode, known=None):
            compat = {"v1": {"passed": True}}
            if mode == "full":
                compat.update({"v2": {"passed": True}, "v3": {"passed": True}})
            return {"ok": True, "tokens": len(proof), "heartbeat": 1,
                    "local_proxy": 40 if mode == "full" else None, "compat": compat}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "validate_proof"), \
             patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b"), ("v3", "c")]), \
             patch.object(campaign, "evaluate", side_effect=fake_eval):
            directory = campaign.run_dir("all-pairs")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "all-pairs", base, "full", materialize_live=False)["candidate_id"]
            for old, new in (("  a", "  aa"), ("  b", "  bb"), ("  c", "  cc")):
                campaign.record_evaluation("T", "all-pairs", base.replace(old, new), "full", [root], materialize_live=False)
            for _ in range(200):
                if campaign.merge_batch("all-pairs", max_checks=4)["checks"] == 0:
                    break
            else:
                self.fail("pair checks did not converge")
            graph = campaign.graph_state("all-pairs")
            self.assertEqual(len(graph["nodes"]), 8)
            self.assertEqual(len({tuple(check["parents"]) for check in graph["merge_checks"]}),
                             len(graph["merge_checks"]))
            self.assertTrue(any("aa\n  bb\n  cc" in node["proof"] for node in graph["nodes"]))


class PacketTests(unittest.TestCase):
    def test_packet_has_statement_and_protocol_but_no_strategy(self):
        text = campaign.packet("Core.InitsUpdatesComm")
        self.assertIn("theorem InitsUpdatesComm", text)
        self.assertIn("at least three structurally different ideas", text)
        self.assertNotIn("witness before versus after induction", text)
        self.assertNotIn("arena-candidate-126", text)

    def test_primed_lean_declaration_is_source_verified(self):
        for symbol in ("UpdateStateNotDefMonotone'", "UpdateStates", "isDefined"):
            with self.subTest(symbol=symbol):
                found = campaign.declaration("Core.InitsUpdatesComm", symbol)
                self.assertIn("signature", found)
                self.assertIn(symbol, found["signature"])

    def test_declaration_keeps_named_argument_inside_type(self):
        signature = campaign.declaration("Core.InitsUpdatesComm", "UpdateStatesLength")["signature"]
        self.assertIn("UpdateStates (P:=P)", signature)
        self.assertIn("List.length ks = List.length vs", signature)


class ViewerTests(unittest.TestCase):
    def test_static_snapshot_and_live_payload(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(campaign, "ROOT", Path(temporary)):
            directory = campaign.run_dir("viewer")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            with patch("tools.serve_candidate_graph.graph_state", return_value={
                "run_id": "viewer", "theorem": "T", "nodes": [], "evaluations": 0,
                "ledger_events": 1, "merge_checks": [], "milestones": [], "frontier": [], "timeline": []}), \
                patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                output = build_snapshot("viewer", Path(temporary) / "snapshot.html")
                self.assertIn("window.GRAPH_SNAPSHOT", output.read_text())
                self.assertEqual(graph_payload("viewer")["run_id"], "viewer")

    def test_spend_chart_has_one_point_per_settled_request_split_by_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"reserve","id":"one","usd":0.4}\n'
                '{"kind":"settle","id":"one","usd":0.1,"pi_embedded_cost_usd":0.1,"ts":1791274568395,'
                '"tokens":{"input":1,"output":10,"cache_read":0,"cache_write":50},'
                '"ledger_components_usd":{"input":0.01,"output":0.04,"cacheRead":0,"cacheWrite":0.05}}\n'
                '{"kind":"reserve","id":"two","usd":0.5}\n'
                '{"kind":"settle","id":"two","usd":0.2,"pi_embedded_cost_usd":0.2,'
                '"tokens":{"input":1,"output":20,"cache_read":150,"cache_write":50},'
                '"ledger_components_usd":{"input":0.01,"output":0.09,"cacheRead":0.08,"cacheWrite":0.02}}\n')
            (directory / "run-config.json").write_text('{"hard_cap_usd": 0.1}')
            with patch("tools.serve_candidate_graph.graph_state", return_value={}), \
                 patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                payload = graph_payload("viewer")
            timeline = payload["cost_timeline"]
            self.assertEqual([row["number"] for row in timeline], [1, 2])
            self.assertEqual([round(row["spent_usd"], 3) for row in timeline], [0.1, 0.3])
            self.assertEqual({k: round(v, 3) for k, v in timeline[-1]["parts"].items()},
                             {"input": 0.02, "output": 0.13, "cache_read": 0.08, "cache_write": 0.07})
            self.assertEqual(timeline[1]["reuse_pct"], 75.0)
            self.assertAlmostEqual(timeline[0]["ts"], 1791274568.395)
            self.assertAlmostEqual(payload["cost"]["pi_embedded_usd"], 0.3)
            self.assertEqual(payload["hard_cap_usd"], 0.1)

    def test_score_charts_start_from_the_original_proof(self):
        from tools.serve_candidate_graph import baseline_point
        payload = {"theorem": "Core.InitsUpdatesComm",
                   "nodes": [{"id": "ref", "origin": "reference"}, {"id": "a", "origin": "model"}]}
        point = baseline_point(payload)
        self.assertEqual((point["number"], point["candidate_id"], point["tokens"], point["local_proxy"]),
                         (0, "ref", 224, 33.33))
        self.assertGreater(point["heartbeat"], 0)
        self.assertIsNone(baseline_point({"theorem": "Core.InitsUpdatesComm", "nodes": []}))

    def test_failed_and_legacy_unknown_usage_releases_do_not_raise_spend(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"reserve","id":"failed","usd":0.4}\n'
                '{"kind":"release","id":"failed","usage_known":false}\n'
                '{"kind":"reserve","id":"legacy","usd":0.3}\n'
                '{"kind":"settle","id":"legacy","usd":0.3,"usage_known":false}\n'
                '{"kind":"reserve","id":"paid","usd":0.5}\n'
                '{"kind":"settle","id":"paid","usd":0.12,"usage_known":true}\n')
            with patch("tools.serve_candidate_graph.graph_state", return_value={}), \
                 patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                payload = graph_payload("viewer")
            self.assertEqual(payload["cost"]["spent_usd"], 0.12)
            self.assertEqual(payload["cost"]["unresolved_usd"], 0)

    def test_legacy_session_exposes_embedded_cost_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session = directory / "session"
            session.mkdir()
            (session / "old.jsonl").write_text(
                '{"type":"message","message":{"usage":{"totalTokens":10,"cost":{"total":0.02}}}}\n')
            with patch("tools.serve_candidate_graph.graph_state", return_value={}), \
                 patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                estimate = graph_payload("viewer")["cost_report"]["pi_embedded_estimate"]
            self.assertEqual(estimate, {"usd": 0.02, "priced_entries": 1, "missing_entries": 0})


class RunnerTests(unittest.TestCase):
    def test_resume_ignores_old_model_errors_but_catches_new_ones(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text('{"type":"message_end","message":{"role":"assistant","stopReason":"error"}}\n')
            offset = path.stat().st_size
            path.write_text(path.read_text() + '{"type":"message_end","message":{"role":"assistant","stopReason":"stop"}}\n')
            self.assertFalse(attempt_has_model_error(path, offset))
            offset = path.stat().st_size
            path.write_text(path.read_text() + '{"type":"message_end","message":{"role":"assistant","stopReason":"aborted"}}\n')
            self.assertTrue(attempt_has_model_error(path, offset))

    def test_budget_stop_and_recovered_transport_error_are_not_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(
                '{"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"Connection error."}}\n'
                '{"type":"auto_retry_end","success":true}\n'
                '{"type":"message_end","message":{"role":"assistant","stopReason":"stop"}}\n'
                '{"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"Arena budget stop: observed usage reached cap"}}\n')
            self.assertFalse(attempt_has_model_error(path, 0))


if __name__ == "__main__":
    unittest.main()
