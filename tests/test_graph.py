import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena.graph import common_base, merge_text, ranked_frontier
from arena import campaign
from tools.build_candidate_graph import build_snapshot
from tools.serve_candidate_graph import graph_payload


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
        def fake_eval(_name, proof, mode):
            compat = {"v1": {"passed": True}}
            if mode == "full":
                compat.update({"v2": {"passed": True}, "v3": {"passed": True}})
            return {"ok": True, "tokens": len(proof), "heartbeat": 3,
                    "local_proxy": 50 if mode == "full" else None, "compat": compat}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
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
        def fake_eval(_name, proof, mode):
            compat = {"v1": {"passed": True}}
            if mode == "full":
                compat.update({"v2": {"passed": True}, "v3": {"passed": True}})
            return {"ok": True, "tokens": len(proof), "heartbeat": 1,
                    "local_proxy": 40 if mode == "full" else None, "compat": compat}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b"), ("v3", "c")]), \
             patch.object(campaign, "evaluate", side_effect=fake_eval):
            directory = campaign.run_dir("all-pairs")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "all-pairs", base, "full", materialize_live=False)["candidate_id"]
            for old, new in (("  a", "  aa"), ("  b", "  bb"), ("  c", "  cc")):
                campaign.record_evaluation("T", "all-pairs", base.replace(old, new), "full", [root], materialize_live=False)
            for _ in range(200):
                if campaign.merge_once("all-pairs") is None:
                    break
            else:
                self.fail("pair checks did not converge")
            graph = campaign.graph_state("all-pairs")
            self.assertEqual(len(graph["nodes"]), 8)
            self.assertEqual(len({tuple(check["parents"]) for check in graph["merge_checks"]}),
                             len(graph["merge_checks"]))
            self.assertTrue(any("aa\n  bb\n  cc" in node["proof"] for node in graph["nodes"]))


class PacketTests(unittest.TestCase):
    def test_packet_includes_original_and_mechanical_opportunities(self):
        text = campaign.packet("Core.InitsUpdatesComm")
        self.assertIn("theorem InitsUpdatesComm", text)
        self.assertIn("update_some: 32 lines", text)
        self.assertIn("UpdateStateNotDefMonotone'", text)
        self.assertNotIn("arena-candidate-126", text)

    def test_primed_lean_declaration_is_source_verified(self):
        for symbol in ("UpdateStateNotDefMonotone'", "UpdateStates", "isDefined"):
            with self.subTest(symbol=symbol):
                found = campaign.declaration("Core.InitsUpdatesComm", symbol)
                self.assertIn("signature", found)
                self.assertIn(symbol, found["signature"])


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

    def test_spend_chart_uses_settled_cost_not_temporary_reservations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"reserve","id":"one","usd":0.4}\n'
                '{"kind":"settle","id":"one","usd":0.1}\n'
                '{"kind":"reserve","id":"two","usd":0.5}\n'
                '{"kind":"settle","id":"two","usd":0.2}\n')
            with patch("tools.serve_candidate_graph.graph_state", return_value={}), \
                 patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                timeline = graph_payload("viewer")["cost_timeline"]
            self.assertEqual([round(row["spent_usd"], 3) for row in timeline], [0, 0.1, 0.1, 0.3])
            self.assertEqual([row["outstanding_usd"] for row in timeline], [0.4, 0, 0.5, 0])


if __name__ == "__main__":
    unittest.main()
