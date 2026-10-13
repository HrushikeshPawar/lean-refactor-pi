import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena.cli.graph import build_snapshot
from arena.cli.run import attempt_has_model_error
from arena.cli.serve import graph_payload
from arena.graph import (
    Graph,
    common_base,
    measured_parent,
    merge_steps,
    merge_text,
    ranked_frontier,
    similarity,
    splice_text,
)
from arena.steps import split_steps, step_range
from tests.graph_support import FakeRunCase


class StepTests(unittest.TestCase):
    def test_steps_keep_nested_bullets_together_and_report_source_lines(self):
        proof = "theorem t : P := by\n  have h := by\n    · exact h\n  exact h\n"
        steps = split_steps(proof)
        self.assertEqual([(step.id, step.first_line, step.last_line) for step in steps], [("s1", 2, 3), ("s2", 4, 4)])
        self.assertEqual(steps[0].text, "  have h := by\n    · exact h")

    def test_term_mode_is_one_step_and_invalid_range_lists_valid_ids(self):
        steps = split_steps("theorem t : P := exact h\n")
        self.assertEqual(len(steps), 1)
        with self.assertRaisesRegex(ValueError, "unknown step s3; steps are s1-s1"):
            step_range(steps, "s3")

    def test_comment_only_lines_do_not_start_steps_and_reversed_ranges_fail(self):
        steps = split_steps("theorem t : P := by\n  -- context\n  exact h\n  assumption\n")
        self.assertEqual([step.text for step in steps], ["  exact h", "  assumption"])
        indented = split_steps("theorem t : P := by\n-- context\n  exact h\n  assumption\n")
        self.assertEqual([step.text for step in indented], ["  exact h", "  assumption"])
        with self.assertRaisesRegex(ValueError, "reversed step range s2-s1; steps are s1-s2"):
            step_range(steps, "s2-s1")

    def test_projection_assigns_stable_ids_status_and_depth_from_ledger_events(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        passed = {"compat": {"v1": {"passed": True}}, "tokens": 8, "heartbeat": 3, "metrics": {"proxy": 80}}
        history = [
            {"kind": "init", "versions": [["v1", "a"], ["v2", "b"]]},
            {"kind": "candidate", "candidate_id": a, "origin": "reference"},
            {"kind": "evaluation", "candidate_id": a, "mode": "fast", "result": passed},
            {"kind": "edge", "proof_id": a, "type": "root", "from": [], "exact": True},
            {
                "kind": "probe",
                "proof_id": b,
                "result": {"compat": {"v1": {"passed": True, "contains_sorry": True}}, "tokens": 6},
            },
            {"kind": "edge", "proof_id": b, "type": "edited_from", "from": [a], "exact": True},
            {"kind": "probe", "proof_id": c, "result": {"compat": {"v1": {"passed": False}}, "tokens": 4}},
            {"kind": "edge", "proof_id": c, "type": "edited_from", "from": [b], "exact": True},
            {"kind": "focus", "proof_id": b, "reason": "start"},
        ]
        texts = {a: "theorem t := by\n  exact h", b: "theorem t := by\n  sorry", c: "theorem t := by\n  bad"}
        graph = Graph.from_history(history, texts.get)
        self.assertEqual(
            [(node.id, node.status, node.depth) for node in graph.nodes],
            [("n1", "closed", 0), ("n2", "sketch", 1), ("n3", "broken", 2)],
        )
        self.assertEqual(graph.focus, b)
        self.assertEqual(graph.order, ["n1", "n2", "n3"])

    def test_projection_joins_latest_successful_step_goals_by_step_id(self):
        proof_id = "a" * 64
        result = {"compat": {"v1": {"passed": True}}, "tokens": 1, "heartbeat": 1, "metrics": {"proxy": 1}}
        history = [
            {"kind": "candidate", "candidate_id": proof_id},
            {"kind": "evaluation", "candidate_id": proof_id, "mode": "fast", "result": result},
            {"kind": "step_goals", "proof_id": proof_id, "error": "temporary failure"},
            {"kind": "step_goals", "proof_id": proof_id, "goals": [{"id": "s1", "before": "P", "after": None}]},
            {"kind": "step_goals", "proof_id": proof_id, "error": "later failure"},
        ]

        node = Graph.from_history(history, lambda _ident: "theorem t := by\n  exact h\n").nodes[0]
        self.assertEqual([(step.before, step.after) for step in node.steps], [("P", None)])

    def test_projection_leaves_steps_without_successful_goal_events_empty(self):
        proof_id = "a" * 64
        result = {"compat": {"v1": {"passed": True}}, "tokens": 1, "heartbeat": 1, "metrics": {"proxy": 1}}
        history = [
            {"kind": "candidate", "candidate_id": proof_id},
            {"kind": "evaluation", "candidate_id": proof_id, "mode": "fast", "result": result},
            {"kind": "step_goals", "proof_id": proof_id, "error": "temporary failure"},
            {"kind": "step_goals", "proof_id": proof_id, "goals": [{"id": "missing", "before": "P", "after": "Q"}]},
        ]

        node = Graph.from_history(history, lambda _ident: "theorem t := by\n  exact h\n").nodes[0]
        self.assertEqual([(step.before, step.after) for step in node.steps], [(None, None)])

    def test_splice_reindents_replacement_and_preserves_other_lines(self):
        proof = "theorem t : P := by\n  intro h\n  exact h\n  done\n"
        self.assertEqual(
            splice_text(proof, "s2", "exact\n  h"),
            "theorem t : P := by\n  intro h\n  exact\n    h\n  done\n",
        )
        self.assertEqual(splice_text("theorem t : P := rfl\n", "s1", "exact h"), "theorem t : P := exact h\n")

    def test_merge_steps_uses_matching_ids_and_rejects_duplicate_take(self):
        base = "theorem t : P := by\n  intro h\n  exact h\n"
        donor = "theorem t : P := by\n  intro z\n  assumption\n"
        self.assertIn("  assumption\n", merge_steps(base, [{"text": donor, "step": "s2"}]))
        with self.assertRaisesRegex(ValueError, "duplicate step s2"):
            merge_steps(base, [{"text": donor, "step": "s2"}, {"text": donor, "step": "s2"}])

    def test_similarity_and_measured_parent_use_recent_lines(self):
        self.assertEqual(similarity("  tactic alpha", "tactic alpha"), 1.0)
        old = [(str(index), f"unique proof line {index}") for index in range(21)]
        self.assertEqual(measured_parent(old, "unique proof line 0")[0], "20")


class GraphCampaignTests(FakeRunCase):
    def setUp(self):
        super().setUp()
        route_patch = patch.object(campaign, "_record_route_later")
        route_patch.start()
        self.addCleanup(route_patch.stop)
        reference = campaign._candidate_ids(campaign.events(self.directory))[0]
        campaign._append(self.directory, {"kind": "focus", "proof_id": reference, "reason": "start"})

    def test_operation_creates_exact_edge_and_stable_node_projection(self):
        with patch.object(campaign, "normalize_draft", side_effect=lambda _name, proof: proof):
            result = campaign.compile_operation(
                "T",
                "logic",
                {"type": "draft", "base": "n1", "text": "theorem t := by\n  good"},
            )
        self.assertEqual(result["node"], "n2")
        self.assertEqual(
            result["edge"],
            {"type": "edited_from", "from": [campaign._candidate_ids(campaign.events(self.directory))[0]]},
        )
        projection = Graph.from_history(
            campaign.events(self.directory), lambda ident: (self.directory / "proofs" / f"{ident}.lean").read_text()
        )
        self.assertEqual([node.id for node in projection.nodes], ["n1", "n2"])
        self.assertEqual(projection.nodes[1].status, "closed")

    def test_operation_honors_full_mode_after_fast_probe_passes(self):
        with patch.object(campaign, "normalize_draft", side_effect=lambda _name, proof: proof):
            result = campaign.compile_operation(
                "T", "logic", {"type": "draft", "base": "n1", "text": "theorem t := by\n  good"}, mode="full"
            )
        self.assertEqual(result["mode"], "full")
        evaluations = [item for item in campaign.events(self.directory) if item.get("kind") == "evaluation"]
        self.assertEqual(evaluations[-1]["mode"], "full")

    def test_free_text_uses_focus_and_failed_compile_still_has_node(self):
        result = self.evaluate("theorem t := by\n  ref2")
        graph = campaign.graph_state("logic")
        edge = graph["nodes"][-1]["edge"]
        self.assertEqual(edge["type"], "filed_under_focus")
        self.assertEqual(edge["from"], [campaign._candidate_ids(campaign.events(self.directory))[0]])
        self.assertEqual(result["candidate"], "#2")

        failed = self.evaluate("theorem t := by\n  bad")
        graph = campaign.graph_state("logic")
        self.assertEqual(graph["nodes"][-1]["edge"]["type"], "filed_under_focus")
        self.assertEqual(failed["candidate"], "#3")

    def test_probe_batch_files_all_drafts_under_original_focus_then_settles_once(self):
        reference = campaign._candidate_ids(campaign.events(self.directory))[0]
        compiled = {"ok": True, "tokens": 1, "heartbeat": 1, "compat": {"v1": {"passed": True}}}
        with (
            patch.object(campaign, "normalize_draft", side_effect=lambda _name, proof: proof),
            patch.object(campaign, "_compile_probes", return_value={}),
            patch.object(campaign, "_compile_probe", return_value=compiled),
        ):
            campaign.probe_batch(
                "T",
                "logic",
                [
                    "theorem t := by\n  alpha",
                    "theorem t := by\n  beta",
                    "theorem t := by\n  gamma",
                    "theorem t := by\n  delta",
                ],
            )
        edges = [item for item in campaign.events(self.directory) if item.get("kind") == "edge"]
        self.assertEqual([edge["from"] for edge in edges[1:]], [[reference]] * 4)
        focuses = [item for item in campaign.events(self.directory) if item.get("kind") == "focus"]
        self.assertEqual(focuses[-1]["reason"], "batch_best")

    def test_named_parent_does_not_control_filing(self):
        first = self.evaluate("theorem t := by\n  ref2")
        result = campaign.record_evaluation(
            "T", "logic", "theorem t := by\n  ref3", "fast", parents=["#1"], materialize_live=False
        )
        reference_id = campaign._candidate_ids(campaign.events(self.directory))[0]
        first_id = campaign._candidate_ids(campaign.events(self.directory))[1]
        event = next(
            item
            for item in campaign.events(self.directory)
            if item.get("kind") == "edge" and item.get("proof_id") == result["candidate_id"]
        )
        self.assertEqual(event["named_parent"], reference_id)
        self.assertEqual(event["from"], [first_id])
        self.assertEqual(first["candidate"], "#2")

    def test_dissimilar_free_text_is_a_root_and_restore_moves_focus(self):
        proof = "theorem t := by\n  entirely different approach\n  another distinct line\n  third separate tactic\n  fourth unrelated statement"
        proof_id = "f" * 64
        campaign._snapshot(self.directory, proof_id, proof)
        edge = campaign._file_node(self.directory, campaign.events(self.directory), proof_id, proof)
        self.assertEqual((edge["type"], edge["from"], edge["exact"]), ("root", [], False))

        campaign.candidate("T", "logic", "#1")
        last_focus = next(item for item in reversed(campaign.events(self.directory)) if item.get("kind") == "focus")
        self.assertEqual(
            (last_focus["proof_id"], last_focus["reason"]),
            (campaign._candidate_ids(campaign.events(self.directory))[0], "restore"),
        )

    def test_splice_and_merge_operations_record_exact_lineage(self):
        with patch.object(campaign, "normalize_draft", side_effect=lambda _name, proof: proof):
            base = self.evaluate("theorem t := by\n  intro h\n  exact h")
            splice = campaign.compile_operation(
                "T", "logic", {"type": "splice", "base": base["candidate"], "steps": "s2", "text": "trivial"}
            )
            donor = self.evaluate("theorem t := by\n  intro z\n  assumption")
            merged = campaign.compile_operation(
                "T",
                "logic",
                {"type": "merge", "base": base["candidate"], "take": [{"from": donor["candidate"], "step": "s2"}]},
            )
        self.assertEqual(splice["edge"]["type"], "edited_from")
        current_graph = Graph.from_history(
            campaign.events(self.directory), lambda ident: (self.directory / "proofs" / f"{ident}.lean").read_text()
        )
        splice_event = next(
            item
            for item in campaign.events(self.directory)
            if item.get("kind") == "edge" and item.get("proof_id") == current_graph.nodes[2].proof_id
        )
        self.assertTrue(splice_event["exact"])
        self.assertEqual(merged["edge"]["type"], "merged_from")
        merge_node = next(item.proof_id for item in current_graph.nodes if item.id == merged["node"])
        merge_event = next(
            item
            for item in campaign.events(self.directory)
            if item.get("kind") == "edge" and item.get("proof_id") == merge_node
        )
        donor_id = campaign._candidate_ids(campaign.events(self.directory))[3]
        self.assertEqual(merge_event["operation"]["take"], [{"from": donor_id, "step": "s2"}])

    def test_bad_node_and_step_references_name_the_input(self):
        with self.assertRaisesRegex(ValueError, "unknown node nope; use nK, #N, pN or a hash prefix"):
            campaign.resolve_node_ref(campaign.events(self.directory), "nope")
        with (
            patch.object(campaign, "normalize_draft", side_effect=lambda _name, proof: proof),
            self.assertRaisesRegex(ValueError, "unknown step s8; steps are s1-s1"),
        ):
            campaign.compile_operation("T", "logic", {"type": "splice", "base": "n1", "steps": "s8", "text": "exact h"})

    def test_repeated_text_does_not_create_another_node_or_edge(self):
        proof = "theorem t := by\n  good"
        first = self.evaluate(proof)
        edges_before = len([item for item in campaign.events(self.directory) if item.get("kind") == "edge"])
        self.evaluate(proof, mode="full")
        graph = Graph.from_history(
            campaign.events(self.directory), lambda ident: (self.directory / "proofs" / f"{ident}.lean").read_text()
        )
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(
            len([item for item in campaign.events(self.directory) if item.get("kind") == "edge"]), edges_before
        )
        self.assertEqual(first["candidate"], "#2")


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
            {
                "id": "a",
                "parents": [],
                "status": "full",
                "local_proxy": 70,
                "tokens": 150,
                "attempts_since_gain": 6,
                "children": ["a1"],
            },
            {
                "id": "b",
                "parents": [],
                "status": "full",
                "local_proxy": 68,
                "tokens": 152,
                "attempts_since_gain": 0,
                "children": [],
            },
        ]
        ranked = ranked_frontier(nodes)
        self.assertEqual(ranked[0]["candidate_id"], "b")
        self.assertIn("saturation", ranked[0]["priority"])


class WorkerTests(unittest.TestCase):
    def test_primary_compile_failure_is_materialized_for_lean_repair(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(campaign, "ROOT", Path(temporary)),
            patch.object(campaign, "problem", return_value={"name": "T"}),
            patch.object(campaign, "validate_proof"),
            patch.object(campaign, "versions", return_value=[("v1", "a")]),
            patch.object(
                campaign,
                "evaluate",
                return_value={
                    "ok": True,
                    "tokens": 4,
                    "compat": {"v1": {"passed": False, "diagnostics": "exact goal"}},
                },
            ),
            patch.object(campaign, "materialize", return_value={"candidate_path": "scratch.lean"}) as live,
        ):
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
            return {
                "ok": True,
                "tokens": len(proof),
                "heartbeat": 3,
                "local_proxy": 50 if mode == "full" else None,
                "compat": compat,
            }

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(campaign, "ROOT", Path(temporary)),
            patch.object(campaign, "problem", return_value={"name": "T"}),
            patch.object(campaign, "validate_proof"),
            patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b"), ("v3", "c")]),
            patch.object(campaign, "evaluate", side_effect=fake_eval),
            patch.object(campaign, "materialize") as live,
        ):
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
            return {
                "ok": True,
                "tokens": len(proof),
                "heartbeat": 1,
                "local_proxy": 40 if mode == "full" else None,
                "compat": compat,
            }

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(campaign, "ROOT", Path(temporary)),
            patch.object(campaign, "problem", return_value={"name": "T"}),
            patch.object(campaign, "validate_proof"),
            patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b"), ("v3", "c")]),
            patch.object(campaign, "evaluate", side_effect=fake_eval),
        ):
            directory = campaign.run_dir("all-pairs")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            root = campaign.record_evaluation("T", "all-pairs", base, "full", materialize_live=False)["candidate_id"]
            for old, new in (("  a", "  aa"), ("  b", "  bb"), ("  c", "  cc")):
                campaign.record_evaluation(
                    "T", "all-pairs", base.replace(old, new), "full", [root], materialize_live=False
                )
            for _ in range(200):
                if campaign.merge_batch("all-pairs", max_checks=4)["checks"] == 0:
                    break
            else:
                self.fail("pair checks did not converge")
            graph = campaign.graph_state("all-pairs")
            self.assertEqual(len(graph["nodes"]), 8)
            self.assertEqual(
                len({tuple(check["parents"]) for check in graph["merge_checks"]}), len(graph["merge_checks"])
            )
            self.assertTrue(any("aa\n  bb\n  cc" in node["proof"] for node in graph["nodes"]))


class PacketTests(unittest.TestCase):
    def test_packet_has_statement_and_protocol_but_no_strategy(self):
        text = campaign.packet("Core.InitsUpdatesComm")
        self.assertIn("theorem InitsUpdatesComm", text)
        self.assertIn("Survey the supplied references", text)
        self.assertNotIn("at least three", text)
        self.assertNotIn("witness before versus after induction", text)
        self.assertNotIn("arena-candidate-126", text)

    def test_primed_lean_declaration_is_source_verified(self):
        for symbol in ("UpdateStateNotDefMonotone'", "UpdateStates", "isDefined"):
            with self.subTest(symbol=symbol):
                found = campaign.declarations("Core.InitsUpdatesComm", [symbol])["items"][0]
                self.assertEqual(found["kind"], "declaration")
                self.assertIn(symbol, found["source_text"])

    def test_declaration_keeps_named_argument_inside_type(self):
        declaration = campaign.declarations("Core.InitsUpdatesComm", ["UpdateStatesLength"])["items"][0]
        self.assertIn("UpdateStates (P:=P)", declaration["source_text"])
        self.assertIn("List.length ks = List.length vs", declaration["source_text"])


class ViewerTests(unittest.TestCase):
    def test_static_snapshot_and_live_payload(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(campaign, "ROOT", Path(temporary)):
            directory = campaign.run_dir("viewer")
            campaign._append(directory, {"kind": "init", "theorem": "T"})
            with (
                patch(
                    "arena.cli.serve.graph_state",
                    return_value={
                        "run_id": "viewer",
                        "theorem": "T",
                        "nodes": [],
                        "evaluations": 0,
                        "ledger_events": 1,
                        "merge_checks": [],
                        "milestones": [],
                        "frontier": [],
                        "timeline": [],
                    },
                ),
                patch("arena.cli.serve.run_dir", return_value=directory),
            ):
                output = build_snapshot("viewer", Path(temporary) / "snapshot.html")
                self.assertIn("window.GRAPH_SNAPSHOT", output.read_text())
                self.assertEqual(graph_payload("viewer")["run_id"], "viewer")

    def test_spend_chart_has_one_point_per_settled_request_split_by_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"settle","id":"one","usd":0.1,"pi_embedded_cost_usd":0.1,"ts":1791274568395,'
                '"tokens":{"input":1,"output":10,"cache_read":0,"cache_write":50},'
                '"ledger_components_usd":{"input":0.01,"output":0.04,"cacheRead":0,"cacheWrite":0.05}}\n'
                '{"kind":"settle","id":"two","usd":0.2,"pi_embedded_cost_usd":0.2,'
                '"tokens":{"input":1,"output":20,"cache_read":150,"cache_write":50},'
                '"ledger_components_usd":{"input":0.01,"output":0.09,"cacheRead":0.08,"cacheWrite":0.02}}\n'
            )
            (directory / "run-config.json").write_text('{"limit_usd": 0.1}')
            with (
                patch("arena.cli.serve.graph_state", return_value={}),
                patch("arena.cli.serve.run_dir", return_value=directory),
            ):
                payload = graph_payload("viewer")
            timeline = payload["cost_timeline"]
            self.assertEqual([row["number"] for row in timeline], [1, 2])
            self.assertEqual([round(row["spent_usd"], 3) for row in timeline], [0.1, 0.3])
            self.assertEqual(
                {k: round(v, 3) for k, v in timeline[-1]["parts"].items()},
                {"input": 0.02, "output": 0.13, "cache_read": 0.08, "cache_write": 0.07},
            )
            self.assertAlmostEqual(timeline[1]["reuse_pct"], 100 * 150 / 201)  # read / (input + read + write)
            self.assertAlmostEqual(timeline[0]["ts"], 1791274568.395)
            self.assertAlmostEqual(payload["cost"]["pi_embedded_usd"], 0.3)
            self.assertEqual(payload["limit_usd"], 0.1)

    def test_score_charts_start_from_the_original_proof(self):
        from arena.cli.serve import baseline_point

        payload = {
            "theorem": "Core.InitsUpdatesComm",
            "nodes": [{"id": "ref", "origin": "reference"}, {"id": "a", "origin": "model"}],
        }
        point = baseline_point(payload)
        self.assertEqual(
            (point["number"], point["candidate_id"], point["tokens"], point["local_proxy"]), (0, "ref", 224, 33.33)
        )
        self.assertGreater(point["heartbeat"], 0)
        self.assertIsNone(baseline_point({"theorem": "Core.InitsUpdatesComm", "nodes": []}))

    def test_original_proof_node_shows_its_published_numbers(self):
        from arena.cli.serve import baseline_point, give_reference_its_numbers

        payload = {
            "theorem": "Core.InitsUpdatesComm",
            "nodes": [
                {
                    "id": "ref",
                    "origin": "reference",
                    "status": "unevaluated",
                    "tokens": None,
                    "heartbeat": None,
                    "local_proxy": None,
                },
                {"id": "a", "origin": "model", "tokens": None},
            ],
        }
        payload["baseline"] = baseline_point(payload)
        give_reference_its_numbers(payload)
        ref, other = payload["nodes"]
        self.assertEqual((ref["status"], ref["tokens"], ref["local_proxy"]), ("full", 224, 33.33))
        self.assertGreater(ref["heartbeat"], 0)
        self.assertIsNone(other["tokens"])

    def test_hub_lists_matching_runs_and_serves_each_viewer_under_its_own_path(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        from arena.cli.serve import Runs, handler_for

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, model in (
                ("rep-r3-model-a", "deepseek-v4.1-flash"),
                ("rep-r3-model-b", "deepseek-v4.1-flash"),
                ("rep-r3-matrix", None),
                ("other-run", "deepseek-v4.1-flash"),
            ):
                (root / name).mkdir()
                if model:
                    (root / name / "ledger.jsonl").write_text('{"kind":"init","theorem":"T"}\n')
                    (root / name / "run-config.json").write_text(
                        json.dumps({"model": model, "limit_usd": 0.1, "theorem": "Core.InitsUpdatesComm"})
                    )
            (root / "rep-r3-model-b" / "summary.json").write_text('{"stop_reason": "actual_usage_cap"}')
            (root / "rep-r3-model-b" / "state.json").write_text('{"best": {"candidate": "#5", "proxy": 81.76}}')
            (root / "rep-r3-model-b" / "cost-ledger.jsonl").write_text(
                '{"kind":"settle","usd":0.03}\n{"kind":"settle","usd":0.02}\n'
            )
            with (
                patch("arena.cli.serve.run_dir", side_effect=lambda run_id: root / run_id),
                patch("arena.cli.serve.graph_state", side_effect=lambda run_id: {"run_id": run_id}),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(Runs([], "rep-r3-*")))
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.addCleanup(server.shutdown)
                base = f"http://127.0.0.1:{server.server_port}"

                def get(path):
                    with urllib.request.urlopen(base + path) as response:
                        return response.read().decode(), response.headers

                hub, headers = get("/")
                self.assertIn('src="hub.js"', hub)
                self.assertIn("frame-src 'self'", headers["Content-Security-Policy"])
                cards = json.loads(get("/runs.json")[0])
                # The matrix log directory has no ledger and runs outside the glob are not shown.
                self.assertEqual([c["run_id"] for c in cards], ["rep-r3-model-a", "rep-r3-model-b"])
                done = cards[1]
                self.assertEqual(
                    (done["finished"], done["best"]["proxy"], done["spent_usd"], done["requests"]),
                    (True, 81.76, 0.05, 2),
                )
                self.assertFalse(cards[0]["finished"])
                # The hub shows every change against the theorem's original proof.
                self.assertEqual(cards[0]["reference"], {"tokens": 224, "heartbeats": 4251, "proxy": 33.33})
                viewer, _ = get("/run/rep-r3-model-a/")
                self.assertIn('src="app.js"', viewer)
                self.assertEqual(json.loads(get("/run/rep-r3-model-a/graph.json")[0])["run_id"], "rep-r3-model-a")
                for bad in ("/run/other-run/", "/run/../secrets/", "/run/rep-r3-model-a/../../x"):
                    with self.assertRaises(urllib.error.HTTPError, msg=bad):
                        get(bad)
                # A run started after the server is found on the next request.
                (root / "rep-r3-model-c").mkdir()
                (root / "rep-r3-model-c" / "ledger.jsonl").write_text("")
                self.assertEqual(len(json.loads(get("/runs.json")[0])), 3)

    def test_a_single_run_still_gets_the_plain_viewer_at_the_root(self):
        from arena.cli.serve import Runs

        self.assertFalse(Runs(["one"]).hub)
        self.assertTrue(Runs(["one", "two"]).hub)
        self.assertTrue(Runs([], "x-*").hub)

    def test_settles_without_known_usage_do_not_raise_spend(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "cost-ledger.jsonl").write_text(
                '{"kind":"settle","id":"failed","usd":0,"usage_known":false}\n'
                '{"kind":"settle","id":"legacy","usd":0.3,"usage_known":false}\n'
                '{"kind":"settle","id":"paid","usd":0.12,"usage_known":true}\n'
            )
            with (
                patch("arena.cli.serve.graph_state", return_value={}),
                patch("arena.cli.serve.run_dir", return_value=directory),
            ):
                payload = graph_payload("viewer")
            self.assertEqual(payload["cost"]["spent_usd"], 0.12)

    def test_legacy_session_exposes_embedded_cost_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session = directory / "session"
            session.mkdir()
            (session / "old.jsonl").write_text(
                '{"type":"message","message":{"usage":{"totalTokens":10,"cost":{"total":0.02}}}}\n'
            )
            with (
                patch("arena.cli.serve.graph_state", return_value={}),
                patch("arena.cli.serve.run_dir", return_value=directory),
            ):
                estimate = graph_payload("viewer")["cost_report"]["pi_embedded_estimate"]
            self.assertEqual(estimate, {"usd": 0.02, "priced_entries": 1, "missing_entries": 0})


class RunnerTests(unittest.TestCase):
    def test_resume_ignores_old_model_errors_but_catches_new_ones(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text('{"type":"message_end","message":{"role":"assistant","stopReason":"error"}}\n')
            offset = path.stat().st_size
            path.write_text(
                path.read_text() + '{"type":"message_end","message":{"role":"assistant","stopReason":"stop"}}\n'
            )
            self.assertFalse(attempt_has_model_error(path, offset))
            offset = path.stat().st_size
            path.write_text(
                path.read_text() + '{"type":"message_end","message":{"role":"assistant","stopReason":"aborted"}}\n'
            )
            self.assertTrue(attempt_has_model_error(path, offset))

    def test_the_limit_stop_abort_and_recovered_transport_error_are_not_fatal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(
                '{"type":"message_end","message":{"role":"assistant","stopReason":"error","errorMessage":"Connection error."}}\n'
                '{"type":"auto_retry_end","success":true}\n'
                '{"type":"message_end","message":{"role":"assistant","stopReason":"stop"}}\n'
                '{"type":"message_end","message":{"role":"assistant","stopReason":"aborted"}}\n'
            )
            self.assertFalse(attempt_has_model_error(path, 0, intentional_stop=True))
            self.assertTrue(attempt_has_model_error(path, 0))


if __name__ == "__main__":
    unittest.main()
