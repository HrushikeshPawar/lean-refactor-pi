import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena.graph import common_base, merge_text, ranked_frontier
from arena.ideas import idea_shape_issue, scheduled_ideas, source_ideas
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
    def test_induct_first_requires_a_different_proof_outline(self):
        self.assertIsNotNone(idea_shape_issue("induct-first", "theorem t := by\n  exists w\n  induction h"))
        self.assertIsNone(idea_shape_issue("induct-first", "theorem t := by\n  induction h\n  exists w"))
        self.assertIsNone(idea_shape_issue("local-golf", "theorem t := by\n  exists w\n  induction h"))

    def test_frontier_rotates_from_saturated_lineage(self):
        nodes = [
            {"id": "a", "parents": [], "status": "full", "local_proxy": 70, "tokens": 150, "attempts_since_gain": 6, "children": ["a1"]},
            {"id": "b", "parents": [], "status": "full", "local_proxy": 68, "tokens": 152, "attempts_since_gain": 0, "children": []},
        ]
        ranked = ranked_frontier(nodes)
        self.assertEqual(ranked[0]["candidate_id"], "b")
        self.assertIn("saturation", ranked[0]["priority"])

    def test_source_ideas_rotate_after_two_development_attempts(self):
        ideas = source_ideas("∃ witness, P witness", "by\n  exists w\n  induction h")
        root = {"id": "root", "index": 1, "origin": "reference"}
        def model(number, idea_id, status="fail"):
            return {"id": str(number), "index": number, "origin": "model", "idea_id": idea_id,
                    "status": status, "tokens": 100, "local_proxy": 50 if status == "full" else None,
                    "decision": "pursue"}
        nodes = [root]
        self.assertEqual(scheduled_ideas(ideas, nodes)[0]["id"], "induct-first")
        nodes.append(model(2, "induct-first"))
        self.assertEqual(scheduled_ideas(ideas, nodes)[0]["id"], "induct-first")
        self.assertIn("Repair", scheduled_ideas(ideas, nodes)[0]["next_action"])
        nodes.append(model(3, "induct-first"))
        self.assertEqual(scheduled_ideas(ideas, nodes)[0]["id"], "factor-premises")
        nodes.extend([model(4, "factor-premises"), model(5, "factor-premises")])
        self.assertEqual(scheduled_ideas(ideas, nodes)[0]["id"], "focused-goals")
        nodes.extend([model(6, "focused-goals"), model(7, "focused-goals")])
        self.assertEqual(scheduled_ideas(ideas, nodes)[0]["id"], "local-golf")

    def test_stalled_four_node_lane_rotates_even_after_portfolio(self):
        ideas = source_ideas("∃ witness, P witness", "by\n  induction h")
        root = {"id": "root", "index": 1, "origin": "reference"}
        nodes = [root] + [{"id": str(i), "index": i, "origin": "model", "idea_id": idea["id"],
                           "status": "full", "tokens": 100, "local_proxy": 50,
                           "decision": "pursue"}
                          for i, idea in enumerate([ideas[0], ideas[0], ideas[1], ideas[1],
                                                     ideas[2], ideas[2], ideas[3], ideas[3],
                                                     ideas[3], ideas[3]], 2)]
        self.assertNotEqual(scheduled_ideas(ideas, nodes)[0]["id"], "local-golf")
        nodes.append({"id": "other", "index": 12, "origin": "model", "idea_id": "focused-goals",
                      "status": "fail", "tokens": 100, "decision": "pursue"})
        self.assertNotEqual(scheduled_ideas(ideas, nodes)[0]["id"], "local-golf")

    def test_scratch_probes_rotate_without_a_graph_candidate(self):
        ideas = source_ideas("∃ witness, P witness", "by\n  induction h")
        nodes = [{"id": "root", "index": 1, "origin": "reference"}]
        probes = [{"idea_id": "induct-first"} for _ in range(4)]
        self.assertEqual(scheduled_ideas(ideas, nodes, probes)[0]["id"], "factor-premises")
        probes.extend({"idea_id": "factor-premises"} for _ in range(4))
        probes.extend({"idea_id": "focused-goals"} for _ in range(4))
        probes.extend({"idea_id": "local-golf"} for _ in range(4))
        self.assertEqual(scheduled_ideas(ideas, nodes, probes)[0]["id"], "induct-first")
        probes.append({"idea_id": "induct-first"})
        self.assertEqual(scheduled_ideas(ideas, nodes, probes)[0]["id"], "factor-premises")

    def test_local_golf_starts_from_global_best_including_merge(self):
        ideas = source_ideas("∃ witness, P witness", "by\n  induction h")
        nodes = [{"id": "root", "index": 1, "origin": "reference"},
                 {"id": "merge", "index": 5, "origin": "auto_merge", "idea_id": None,
                  "status": "full", "local_proxy": 70, "tokens": 150, "decision": "pursue"}]
        golf = next(row for row in scheduled_ideas(ideas, nodes) if row["id"] == "local-golf")
        self.assertEqual(golf["seed_candidate_id"], "merge")


class WorkerTests(unittest.TestCase):
    def test_idea_schedule_rejects_wrong_lane_and_accepts_node_alias(self):
        base = "theorem t := by\n  exact True.intro\n"
        def fake_eval(_name, proof, _mode):
            return {"ok": True, "tokens": len(proof), "heartbeat": 3,
                    "compat": {"v1": {"passed": True}}, "local_proxy": None}
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "versions", return_value=[("v1", "a")]), \
             patch.object(campaign, "evaluate", side_effect=fake_eval), \
             patch.object(campaign, "materialize", return_value={"candidate_path": "shadow.lean"}):
            directory = campaign.run_dir("ideas")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "ideas", base, "fast", materialize_live=False)["candidate_id"]
            for idea in source_ideas("∃ x, P x", "by\n  induction h"):
                campaign._append(directory, {"kind": "idea", **idea})
            proof = base.replace("exact True.intro", "induction h\n  trivial")
            with self.assertRaisesRegex(ValueError, "scheduled idea induct-first"):
                campaign.record_evaluation("T", "ideas", proof, "fast", ["#1"], idea_id="local-golf")
            with self.assertRaisesRegex(ValueError, "induction or cases step"):
                campaign.record_evaluation("T", "ideas", base.replace("exact True.intro", "trivial"),
                                           "fast", ["#1"], idea_id="induct-first")
            first = campaign.record_evaluation("T", "ideas", proof, "fast", ["#1"],
                                               idea_id="induct-first", materialize_live=False)
            self.assertEqual(first["node_number"], 2)
            self.assertEqual(campaign.candidate("T", "ideas", "#2")["candidate_id"], first["candidate_id"])
            self.assertEqual(campaign.graph_state("ideas")["nodes"][1]["parents"], [root])

    def test_probe_keeps_draft_out_of_candidate_graph_and_deduplicates(self):
        base = "theorem t := by\n  exact True.intro\n"
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(campaign, "ROOT", Path(temporary)), \
             patch.object(campaign, "problem", return_value={"name": "T"}), \
             patch.object(campaign, "versions", return_value=[("v1", "a")]), \
             patch.object(campaign, "evaluate", return_value={"ok": True, "tokens": 4,
                 "compat": {"v1": {"passed": False, "diagnostics": "unsolved goal"}}}) as compiler, \
             patch.object(campaign, "materialize", return_value={"candidate_path": "shadow.lean"}):
            directory = campaign.run_dir("scratch-idea")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "scratch-idea", base, "fast", materialize_live=False)["candidate_id"]
            campaign._append(directory, {"kind": "idea", **source_ideas("∃ x, P x", "by\n  induction h")[0]})
            compiler.reset_mock()
            draft = base.replace("True.intro", "broken")
            first = campaign.probe("T", "scratch-idea", draft, "induct-first", "#1")
            second = campaign.probe("T", "scratch-idea", draft, "induct-first", root[:8])
            self.assertEqual(first["compat"]["v1"]["diagnostics"], "unsolved goal")
            self.assertIn("induction or cases", first["idea_shape_issue"])
            self.assertTrue(second["cached"])
            compiler.assert_called_once()
            self.assertEqual(len(campaign.graph_state("scratch-idea")["nodes"]), 1)
            self.assertEqual(len(campaign.graph_state("scratch-idea")["probes"]), 1)

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
    def test_packet_includes_original_and_mechanical_opportunities(self):
        text = campaign.packet("Core.InitsUpdatesComm")
        self.assertIn("theorem InitsUpdatesComm", text)
        self.assertIn("update_some: 32 lines", text)
        self.assertIn("UpdateStateNotDefMonotone'", text)
        self.assertIn("witness before versus after induction", text)
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

    def test_spend_chart_uses_settled_cost_not_temporary_reservations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"reserve","id":"one","usd":0.4}\n'
                '{"kind":"settle","id":"one","usd":0.1,"pi_embedded_cost_usd":0.06}\n'
                '{"kind":"reserve","id":"two","usd":0.5}\n'
                '{"kind":"settle","id":"two","usd":0.2,"pi_embedded_cost_usd":0.12}\n')
            with patch("tools.serve_candidate_graph.graph_state", return_value={}), \
                 patch("tools.serve_candidate_graph.run_dir", return_value=directory):
                timeline = graph_payload("viewer")["cost_timeline"]
            self.assertEqual([round(row["spent_usd"], 3) for row in timeline], [0, 0.1, 0.1, 0.3])
            self.assertEqual([round(row["pi_embedded_usd"], 3) for row in timeline], [0, 0.06, 0.06, 0.18])
            self.assertEqual([row["outstanding_usd"] for row in timeline], [0.4, 0, 0.5, 0])

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
