import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena import graph as graph_module
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


class ArchiveTests(unittest.TestCase):
    def project(self, specs):
        history = []
        proofs = {}
        for proof_id, route, score, status, parent in specs:
            proof = (
                "theorem t : True := by\n  sorry\n"
                if status == "sketch"
                else "theorem t : True := by\n  exact True.intro\n"
            )
            proofs[proof_id] = proof
            history.append({"kind": "candidate", "candidate_id": proof_id, "origin": "model"})
            passed = status in ("closed", "sketch")
            history.append(
                {
                    "kind": "evaluation",
                    "candidate_id": proof_id,
                    "mode": "fast",
                    "result": {
                        "compat": {"v": {"passed": passed}},
                        "contains_sorry": status == "sketch",
                        "metrics": {"estimated_proxy": score},
                    },
                }
            )
            history.append({"kind": "edge", "proof_id": proof_id, "from": [parent] if parent else []})
            history.append({"kind": "route", "proof_id": proof_id, "route": route})
        return graph_module.Graph.from_history(history, proofs.get), history

    def test_depth_buckets_follow_the_four_boundaries(self):
        self.assertEqual(
            [graph_module.depth_bucket(depth) for depth in (0, 2, 3, 7, 8, 15, 16)],
            ["0-2", "0-2", "3-7", "3-7", "8-15", "8-15", "16+"],
        )

    def test_archive_keeps_best_counts_visits_splits_status_and_stabilizes_letters(self):
        graph, _ = self.project(
            [
                ("a", "r1", 50, "closed", None),
                ("b", "r1", 60, "closed", "a"),
                ("c", "r1", None, "sketch", "b"),
                ("d", "r2", None, "broken", "c"),
            ]
        )
        cells = graph_module.archive(graph)
        self.assertEqual(
            [(cell.letter, cell.route, cell.status) for cell in cells], [("A", "r1", "closed"), ("B", "r1", "sketch")]
        )
        self.assertEqual((cells[0].node.proof_id, cells[0].visits), ("b", 2))
        graph, _ = self.project([("a", "r1", 50, "closed", None), ("b", "r2", 40, "closed", "a")])
        self.assertEqual([cell.letter for cell in graph_module.archive(graph)], ["A", "B"])

    def test_keeps_are_only_strict_new_highs(self):
        graph, _ = self.project(
            [("a", "r1", 50, "closed", None), ("b", "r1", 50, "closed", "a"), ("c", "r1", 51, "closed", "b")]
        )
        self.assertEqual([node.proof_id for node in graph_module.keeps(graph)], ["a", "c"])

    def test_stall_counts_only_descendants_and_resets_on_keeps_and_fires(self):
        specs = [("root", "r1", 60, "closed", None)]
        specs += [(f"n{i}", "r1", 60 - i, "closed", specs[-1][0]) for i in range(1, 13)]
        graph, history = self.project(specs)
        self.assertEqual(graph_module.stall_fire(graph, 12), {"root": "root", "count": 12, "after": "n12"})
        self.assertIsNone(graph_module.stall_fire(graph_module.Graph.from_history([], lambda _: None), 12))
        after_fire = [
            *history,
            {"kind": "candidate", "candidate_id": "n13", "origin": "model"},
            {
                "kind": "evaluation",
                "candidate_id": "n13",
                "mode": "fast",
                "result": {"compat": {"v": {"passed": True}}, "metrics": {"estimated_proxy": 80}},
            },
            {"kind": "edge", "proof_id": "n13", "from": ["n12"]},
            {"kind": "route", "proof_id": "n13", "route": "r1"},
        ]
        self.assertEqual(
            graph_module.stall_fire(Graph.from_history(after_fire, lambda _: "proof"), 12),
            {"root": "root", "count": 12, "after": "n12"},
        )
        after_fire.append(
            {"kind": "stall", "root": "root", "count": 12, "mode": "best_other_cell", "target": "elsewhere"}
        )
        replay = Graph.from_history(after_fire, lambda _: "proof")
        self.assertEqual(graph_module.stall_fire(replay, 12), {"root": "root", "count": 12, "after": "n12"})
        self.assertEqual(
            replay.stall_events,
            [{"root": "root", "count": 12, "mode": "best_other_cell", "target": "elsewhere"}],
        )

        branches = [("root", "r1", 60, "closed", None), ("sibling", "r1", 59, "closed", None)]
        branches += [(f"n{i}", "r1", 59 - i, "closed", branches[-1][0]) for i in range(1, 12)]
        graph, _ = self.project(branches)
        self.assertIsNone(graph_module.stall_fire(graph, 12))
        short_chain = [("root", "r1", 60, "closed", None)]
        short_chain += [(f"n{i}", "r1", 60 - i, "closed", short_chain[-1][0]) for i in range(1, 12)]
        graph, _ = self.project(short_chain)
        self.assertEqual(graph_module.stall_fire(graph, 11), {"root": "root", "count": 11, "after": "n11"})

    def test_stall_target_modes_choose_archive_cells_and_validate_inputs(self):
        graph, _ = self.project(
            [
                ("root", "r1", 100, "closed", None),
                ("x", "r2", 30, "closed", None),
                ("y", "r2", 25, "closed", None),
                ("z", "r3", 25, "closed", None),
            ]
        )
        fired = {"root": "root", "count": 12}
        best = graph_module.stall_target(graph, fired, "best_other_cell")
        least = graph_module.stall_target(graph, fired, "least_visited")
        assert best is not None and least is not None
        self.assertEqual(best.node.proof_id, "x")
        self.assertEqual(least.node.proof_id, "z")
        self.assertIsNone(graph_module.stall_target(graph, fired, "map_only"))
        with self.assertRaises(ValueError):
            graph_module.stall_target(graph, fired, "unknown")

        tied, _ = self.project(
            [
                ("root", "r1", 100, "closed", None),
                ("x", "r2", 30, "closed", None),
                ("y", "r3", 30, "closed", None),
            ]
        )
        tied_best = graph_module.stall_target(tied, fired, "best_other_cell")
        tied_least = graph_module.stall_target(tied, fired, "least_visited")
        assert tied_best is not None and tied_least is not None
        self.assertEqual(tied_best.letter, "B")
        self.assertEqual(tied_least.letter, "B")

        only_lineage, _ = self.project([("root", "r1", 100, "closed", None), ("child", "r1", 90, "closed", "root")])
        self.assertIsNone(graph_module.stall_target(only_lineage, fired, "best_other_cell"))

    def test_stall_target_prefers_another_route_over_a_better_same_route_cell(self):
        graph, _ = self.project(
            [
                ("root", "r1", 100, "closed", None),
                ("same", "r1", 90, "sketch", None),
                ("other", "r2", 10, "closed", None),
            ]
        )
        fired = {"root": "root", "count": 12}
        for mode in ("best_other_cell", "least_visited"):
            target = graph_module.stall_target(graph, fired, mode)
            assert target is not None
            self.assertEqual(target.node.proof_id, "other")
        same_only, _ = self.project([("root", "r1", 100, "closed", None), ("same", "r1", 90, "sketch", None)])
        target = graph_module.stall_target(same_only, fired, "best_other_cell")
        assert target is not None
        self.assertEqual(target.node.proof_id, "same")

    def test_stall_fires_depend_only_on_nodes_and_reset_on_each_crossing(self):
        specs = [("root", "r1", 100, "closed", None)]
        specs += [(f"n{i}", "r1", 100 - i, "closed", specs[-1][0]) for i in range(1, 13)]
        graph, history = self.project(specs)
        self.assertEqual(graph_module.stall_fire(graph, 12), {"root": "root", "count": 12, "after": "n12"})
        history.append({"kind": "focus", "proof_id": "elsewhere", "reason": "stall", "root": "root"})
        self.assertEqual(
            graph_module.stall_fire(Graph.from_history(history, lambda _: "proof"), 12),
            {"root": "root", "count": 12, "after": "n12"},
        )
        history += [
            event
            for proof_id in (f"m{i}" for i in range(1, 13))
            for event in (
                {"kind": "candidate", "candidate_id": proof_id, "origin": "model"},
                {
                    "kind": "evaluation",
                    "candidate_id": proof_id,
                    "mode": "fast",
                    "result": {"compat": {"v": {"passed": True}}, "metrics": {"estimated_proxy": 80}},
                },
                {"kind": "edge", "proof_id": proof_id, "from": ["root"]},
                {"kind": "route", "proof_id": proof_id, "route": "r1"},
            )
        ]
        self.assertEqual(
            graph_module.stall_fire(Graph.from_history(history, lambda _: "proof"), 12),
            {"root": "root", "count": 12, "after": "m12"},
        )

    def test_batch_replay_preserves_every_threshold_crossing(self):
        specs = [("root", "r1", 100, "closed", None)]
        specs += [(f"n{i}", "r1", 100 - i, "closed", specs[-1][0]) for i in range(1, 25)]
        graph, history = self.project(specs)
        fires = graph_module.stall_fires(graph, 12)
        self.assertEqual(
            fires,
            [
                {"root": "root", "count": 12, "after": "n12"},
                {"root": "root", "count": 12, "after": "n24"},
            ],
        )
        history.extend(
            {
                "kind": "stall",
                "root": fire["root"],
                "count": fire["count"],
                "mode": "map_only",
                "target": None,
            }
            for fire in fires
        )
        replay = Graph.from_history(history, lambda _: "proof")
        self.assertEqual(graph_module.stall_fires(replay, 12), fires)
        self.assertEqual(
            replay.stall_events,
            [
                {"root": "root", "count": 12, "mode": "map_only", "target": None},
                {"root": "root", "count": 12, "mode": "map_only", "target": None},
            ],
        )

    def test_map_has_exact_shape_and_marks_recent_nodes(self):
        graph, _ = self.project(
            [("a", "r1", 50, "closed", None), ("b", "r1", 40, "closed", "a"), ("c", "r1", None, "broken", "b")]
        )
        view = graph_module.map_view(graph)
        self.assertEqual(set(view), {"best", "reference", "archive", "recent", "effort", "open"})
        self.assertEqual(view["best"]["node"], "n1")
        self.assertEqual([row["status"] for row in view["recent"]], ["closed", "closed", "broken"])
        self.assertEqual((view["effort"], view["open"]), ([], []))

    def test_map_names_parents_by_node_id_and_lists_the_original_as_reference(self):
        graph, history = self.project(
            [("a" * 64, "r1", 50, "closed", None), ("b" * 64, "r1", None, "sketch", "a" * 64)]
        )
        history[0]["origin"] = "reference"
        graph = Graph.from_history(history, lambda _: "theorem t : True := by\n  sorry\n")
        view = graph_module.map_view(graph, reference=(407, 1383))
        self.assertEqual(view["reference"], {"node": "n1", "tokens": 407, "heartbeats": 1383})
        self.assertEqual(
            [(row["node"], row["from"], row["status"]) for row in view["recent"]], [("n2", ["n1"], "sketch")]
        )

    def test_map_has_no_best_before_a_scored_node(self):
        graph, _ = self.project([("a", "r1", None, "closed", None)])
        self.assertIsNone(graph_module.map_view(graph)["best"])


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
        reference = campaign._candidate_ids(campaign.events(self.directory))[0]
        campaign._append(self.directory, {"kind": "focus", "proof_id": reference, "reason": "start"})

    def test_routes_are_filed_synchronously_and_one_line_edit_keeps_parent_route(self):
        initial = campaign.events(self.directory)
        first_routes = [item for item in initial if item.get("kind") == "route"]
        first_route_line = next(
            line
            for line in (self.directory / "ledger.jsonl").read_bytes().splitlines()
            if json.loads(line).get("kind") == "route"
        )
        reference = campaign._candidate_ids(campaign.events(self.directory))[0]
        self.evaluate("theorem t := by\n  ref2")
        history = campaign.events(self.directory)
        routes = [event for event in history if event.get("kind") == "route"]
        route_lines = [
            line
            for line in (self.directory / "ledger.jsonl").read_bytes().splitlines()
            if json.loads(line).get("kind") == "route"
        ]
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0], first_routes[0])
        self.assertEqual(route_lines[0], first_route_line)
        self.assertEqual(routes[1]["parent"], reference)
        self.assertEqual(routes[1]["route"], routes[0]["route"])
        self.assertEqual(routes[1]["assigned_by"], "signature")
        self.assertFalse((self.directory / "route-queue.jsonl").exists())

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


class StallCampaignTests(FakeRunCase):
    def test_stall_threshold_rejects_an_invalid_environment_value(self):
        graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        with (
            patch.dict("os.environ", {"ARENA_STALL_M": "zero"}),
            self.assertRaisesRegex(ValueError, "stall threshold must be a positive integer"),
        ):
            campaign._check_stall(self.directory, graph, set())

    def test_stall_moves_focus_to_another_cell_and_adds_one_state_update(self):
        history = campaign.events(self.directory)
        root = campaign._candidate_ids(history)[0]

        def add(proof_id, route, score, parent):
            proof = "theorem t : True := by\n  exact True.intro\n"
            proof_path = self.directory / "proofs" / f"{proof_id}.lean"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text(proof)
            campaign._append(self.directory, {"kind": "candidate", "candidate_id": proof_id, "origin": "model"})
            campaign._append(
                self.directory,
                {
                    "kind": "evaluation",
                    "candidate_id": proof_id,
                    "mode": "fast",
                    "result": {
                        "compat": {"v1": {"passed": True}},
                        "metrics": {"estimated_proxy": score},
                    },
                },
            )
            campaign._append(self.directory, {"kind": "edge", "proof_id": proof_id, "from": [parent] if parent else []})
            campaign._append(self.directory, {"kind": "route", "proof_id": proof_id, "route": route})

        target = "a" * 64
        add(target, "r2", 5, None)
        add("b" * 64, "r1", 4, root)
        add("c" * 64, "r1", 3, root)
        graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        with patch.dict("os.environ", {"ARENA_STALL_M": "2", "ARENA_STALL_TARGET": "map_only"}):
            campaign._check_stall(self.directory, graph, {"c" * 64})
        history = campaign.events(self.directory)
        self.assertEqual(
            [
                {key: item[key] for key in ("root", "count", "mode", "target")}
                for item in history
                if item.get("kind") == "stall"
            ],
            [{"root": root, "count": 2, "mode": "map_only", "target": None}],
        )
        self.assertFalse(any(item.get("kind") == "focus" and item.get("reason") == "stall" for item in history))
        self.assertFalse(campaign.state("logic")["updates"])
        campaign._check_stall(self.directory, graph, set())
        self.assertEqual(len([item for item in campaign.events(self.directory) if item.get("kind") == "stall"]), 1)

        add("d" * 64, "r1", 2, "c" * 64)
        add("e" * 64, "r1", 1, "d" * 64)
        graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        with patch.dict("os.environ", {"ARENA_STALL_M": "2", "ARENA_STALL_TARGET": "best_other_cell"}):
            campaign._check_stall(self.directory, graph, {"d" * 64, "e" * 64})
        history = campaign.events(self.directory)
        focus = [item for item in history if item.get("kind") == "focus" and item.get("reason") == "stall"][-1]
        self.assertEqual(
            (focus["proof_id"], focus["reason"], focus["root"], focus["cell"]), (target, "stall", root, "B")
        )
        replayed = Graph.from_history(history, campaign._proof_reader(self.directory))
        self.assertEqual(graph_module.stall_fires(replayed, 2), graph_module.stall_fires(graph, 2))
        self.assertEqual(
            replayed.stall_events,
            [
                {"root": root, "count": 2, "mode": "map_only", "target": None},
                {"root": root, "count": 2, "mode": "best_other_cell", "target": target},
            ],
        )
        self.assertEqual(
            campaign.state("logic")["updates"][-1],
            {
                "seq": next(index for index, event in enumerate(history) if event == focus),
                "text": "Focus set to n2: archive cell B, score 5, 1 nodes in the cell.",
            },
        )

    def test_stall_without_an_other_cell_is_audited_once_without_focus_or_update(self):
        root = campaign._candidate_ids(campaign.events(self.directory))[0]
        proof = "theorem t : True := by\n  exact True.intro\n"
        parent = root
        filed = set()
        for index in range(1, 3):
            proof_id = f"{index:064x}"
            proof_path = self.directory / "proofs" / f"{proof_id}.lean"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text(proof)
            campaign._append(self.directory, {"kind": "candidate", "candidate_id": proof_id, "origin": "model"})
            campaign._append(
                self.directory,
                {
                    "kind": "evaluation",
                    "candidate_id": proof_id,
                    "mode": "fast",
                    "result": {"compat": {"v1": {"passed": True}}, "metrics": {"estimated_proxy": 1}},
                },
            )
            campaign._append(self.directory, {"kind": "edge", "proof_id": proof_id, "from": [parent]})
            campaign._append(self.directory, {"kind": "route", "proof_id": proof_id, "route": "r1"})
            filed.add(proof_id)
            parent = proof_id

        graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        expected_fires = graph_module.stall_fires(graph, 2)
        with patch.dict("os.environ", {"ARENA_STALL_M": "2", "ARENA_STALL_TARGET": "best_other_cell"}):
            campaign._check_stall(self.directory, graph, filed)
        history = campaign.events(self.directory)
        self.assertFalse(any(item.get("kind") == "focus" and item.get("reason") == "stall" for item in history))
        self.assertEqual(
            [
                {key: item[key] for key in ("root", "count", "mode", "target")}
                for item in history
                if item.get("kind") == "stall"
            ],
            [{"root": root, "count": 2, "mode": "best_other_cell", "target": None}],
        )
        self.assertFalse(campaign.state("logic")["updates"])
        replayed = Graph.from_history(history, campaign._proof_reader(self.directory))
        self.assertEqual(graph_module.stall_fires(replayed, 2), expected_fires)
        self.assertEqual(
            replayed.stall_events,
            [{"root": root, "count": 2, "mode": "best_other_cell", "target": None}],
        )

        target = "a" * 64
        target_path = self.directory / "proofs" / f"{target}.lean"
        target_path.write_text(proof)
        campaign._append(self.directory, {"kind": "candidate", "candidate_id": target, "origin": "model"})
        campaign._append(
            self.directory,
            {
                "kind": "evaluation",
                "candidate_id": target,
                "mode": "fast",
                "result": {"compat": {"v1": {"passed": True}}, "metrics": {"estimated_proxy": 0}},
            },
        )
        campaign._append(self.directory, {"kind": "edge", "proof_id": target, "from": []})
        campaign._append(self.directory, {"kind": "route", "proof_id": target, "route": "r2"})
        later_graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        with patch.dict("os.environ", {"ARENA_STALL_M": "2", "ARENA_STALL_TARGET": "best_other_cell"}):
            campaign._check_stall(self.directory, later_graph, {target})
        later_history = campaign.events(self.directory)
        self.assertEqual(len([item for item in later_history if item.get("kind") == "stall"]), 1)
        self.assertFalse(any(item.get("kind") == "focus" and item.get("reason") == "stall" for item in later_history))

    def test_stall_records_each_crossing_from_a_multi_threshold_batch(self):
        root = campaign._candidate_ids(campaign.events(self.directory))[0]

        def add(proof_id, route, score, parent):
            proof = "theorem t : True := by\n  exact True.intro\n"
            proof_path = self.directory / "proofs" / f"{proof_id}.lean"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text(proof)
            campaign._append(self.directory, {"kind": "candidate", "candidate_id": proof_id, "origin": "model"})
            campaign._append(
                self.directory,
                {
                    "kind": "evaluation",
                    "candidate_id": proof_id,
                    "mode": "fast",
                    "result": {"compat": {"v1": {"passed": True}}, "metrics": {"estimated_proxy": score}},
                },
            )
            campaign._append(self.directory, {"kind": "edge", "proof_id": proof_id, "from": [parent] if parent else []})
            campaign._append(self.directory, {"kind": "route", "proof_id": proof_id, "route": route})

        add("a" * 64, "r2", 0, None)
        parent = root
        for index in range(1, 25):
            proof_id = f"{index:064x}"
            add(proof_id, "r1", 0, parent)
            parent = proof_id

        graph = Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        with patch.dict("os.environ", {"ARENA_STALL_M": "12", "ARENA_STALL_TARGET": "best_other_cell"}):
            campaign._check_stall(self.directory, graph, {f"{index:064x}" for index in range(1, 25)})

        history = campaign.events(self.directory)
        stall_events = [event for event in history if event.get("kind") == "stall"]
        self.assertEqual([(event["root"], event["count"]) for event in stall_events], [(root, 12), (root, 12)])
        self.assertEqual([event["target"] for event in stall_events], ["a" * 64, "a" * 64])
        self.assertEqual(
            len([event for event in history if event.get("kind") == "focus" and event.get("reason") == "stall"]),
            1,
        )
        replayed = Graph.from_history(history, campaign._proof_reader(self.directory))
        self.assertEqual(graph_module.stall_fires(replayed, 12), graph_module.stall_fires(graph, 12))
        self.assertEqual(
            replayed.stall_events,
            [
                {"root": root, "count": 12, "mode": "best_other_cell", "target": "a" * 64},
                {"root": root, "count": 12, "mode": "best_other_cell", "target": "a" * 64},
            ],
        )
        self.assertEqual(graph_module.stall_fires(replayed, 12), graph_module.stall_fires(graph, 12))

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
        winner = focuses[-1]["proof_id"]
        campaign._append(self.directory, {"kind": "focus", "proof_id": reference, "reason": "restore"})
        settled = campaign._settle_focus(self.directory, [winner])
        self.assertEqual(settled.focus, winner)

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

    def test_dissimilar_free_text_is_filed_once_as_a_root(self):
        proof = "theorem t := by\n  entirely different approach\n  another distinct line\n  third separate tactic\n  fourth unrelated statement"
        proof_id = "f" * 64
        campaign._snapshot(self.directory, proof_id, proof)
        edge, created = campaign._file_node(self.directory, campaign.events(self.directory), proof_id, proof)
        self.assertTrue(created)
        self.assertEqual((edge["type"], edge["from"], edge["exact"]), ("root", [], False))
        duplicate, created = campaign._file_node(self.directory, campaign.events(self.directory), proof_id, proof)
        self.assertFalse(created)
        self.assertEqual(duplicate["proof_id"], edge["proof_id"])

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
        with self.assertRaisesRegex(ValueError, "nope is not a node id"):
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
            assert first is not None
            self.assertEqual(first["reason"], "no_independent_edits")
            outcome = campaign.merge_once("test")
            assert outcome is not None
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
        self.assertIn("Original proof: node n1", text)
        self.assertIn("| step | lines | tokens |", text)
        self.assertNotIn("at least three", text)
        self.assertNotIn("witness before versus after induction", text)
        self.assertNotIn("arena-candidate-126", text)


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
        assert point is not None
        self.assertEqual(
            (point["number"], point["candidate_id"], point["tokens"], point["local_proxy"]), (0, "ref", 224, 33.33)
        )
        assert isinstance(point["heartbeat"], (int, float))
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
        assert isinstance(ref["heartbeat"], (int, float))
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
