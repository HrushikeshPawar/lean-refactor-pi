"""Salvage, hole filling, and assembly contracts without a live Lean process."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from arena import campaign, graph, salvage
from tests.graph_support import FakeRunCase


def scripted(results):
    seen = []

    def compile(proof):
        seen.append(proof)
        outcome = results[min(len(seen) - 1, len(results) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(proof)
        return outcome

    return compile, seen


def diagnostics(*lines):
    return {
        "clean": False,
        "error_lines": list(lines),
        "unlocated": not lines,
        "result": {"ok": True, "compat": {"v1": {"passed": False}}},
    }


class SalvagePlanningTests(unittest.TestCase):
    def test_deferred_salvage_resumes_at_the_next_compile(self):
        proof = "theorem t : True := by\n  bad\n  exact True.intro"
        compile, seen = scripted([diagnostics(2), {"clean": True, "error_lines": [], "unlocated": False, "result": {}}])
        first = salvage.salvage("T", proof, compile, should_yield=lambda: "full_check_arrived" if seen else None)
        self.assertEqual((first["status"], first["compiles"], len(seen)), ("deferred", 1, 1))
        resumed = salvage.salvage("T", proof, compile, resume=first["continuation"])
        self.assertEqual((resumed["status"], resumed["compiles"], len(seen)), ("salvaged", 2, 2))

    def test_nested_body_error_becomes_one_hole_with_s2(self):
        proof = "theorem t : True := by\n  have h : True := by\n    bad\n  exact h"
        compile, seen = scripted(
            [
                diagnostics(3),
                {"clean": True, "error_lines": [], "unlocated": False, "result": {"compat": {"v1": {"passed": True}}}},
            ]
        )
        result = salvage.salvage("T", proof, compile)
        self.assertEqual(
            (result["status"], result["compiles"], result["rounds"][0]["strategies"]), ("salvaged", 2, ["S2"])
        )
        self.assertIn("    sorry", result["text"])
        self.assertEqual(len(seen), 2)

    def test_header_type_error_is_checked_then_parent_is_dropped(self):
        proof = "theorem t : True := by\n  have h : False := by\n    exact True.intro\n  exact h"
        compile, seen = scripted(
            [diagnostics(2), diagnostics(2), {"clean": True, "error_lines": [], "unlocated": False, "result": {}}]
        )
        result = salvage.salvage("T", proof, compile)
        self.assertEqual(result["status"], "salvaged")
        self.assertIn("have h : False := sorry", seen[1])
        self.assertEqual(result["rounds"][0]["strategies"], ["S3"])
        self.assertIn("sorry", result["text"])

    def test_s4_escalates_when_s2_and_s3_make_no_change(self):
        proof = "theorem t : True := by\n  cases h with\n    | inl x => exact x\n  exact True.intro"
        compile, _ = scripted([diagnostics(2), {"clean": True, "error_lines": [], "unlocated": False, "result": {}}])
        result = salvage.salvage("T", proof, compile)
        self.assertEqual(result["status"], "salvaged")
        self.assertEqual(result["rounds"][0]["strategies"], ["S4"])
        self.assertIn("sorry", result["text"])

    def test_s1_drops_a_trailing_tactic_that_finds_no_goals(self):
        proof = "theorem t : True := by\n  trivial\n  rfl"
        finished = {
            "ok": True,
            "compat": {
                "v1": {
                    "passed": False,
                    "diagnostics": [{"severity": "error", "proof_line": 3, "message": "No goals to be solved"}],
                }
            },
        }
        compile, seen = scripted(
            [
                {**diagnostics(3), "result": finished},
                {"clean": True, "error_lines": [], "unlocated": False, "result": {}},
            ]
        )
        result = salvage.salvage("T", proof, compile)
        self.assertEqual((result["status"], result["rounds"][0]["strategies"]), ("salvaged", ["S1"]))
        self.assertEqual(seen[-1], "theorem t : True := by\n  trivial")

    def test_top_level_errors_do_not_replace_the_whole_proof(self):
        proof = "theorem t : True := by\n  bad\n  bad"
        compile, _ = scripted([diagnostics(2, 3)])
        result = salvage.salvage("T", proof, compile)
        self.assertEqual(result["status"], "broken-whole-proof-sorried")

    def test_unlocated_unparseable_unavailable_and_pass_limit_statuses(self):
        malformed = salvage.salvage("T", "theorem t := exact h", lambda _: diagnostics(1))
        self.assertEqual(malformed["status"], "unparseable")
        proof = "theorem t : True := by\n" + "\n".join(f"  bad{i}" for i in range(7))
        outside, _ = scripted([diagnostics(1)])
        self.assertEqual(salvage.salvage("T", proof, outside)["status"], "broken-outside-steps")
        raised, _ = scripted([ValueError("offline")])
        self.assertEqual(salvage.salvage("T", proof, raised)["status"], "unavailable")
        seen = []

        def never_compiles(current):
            seen.append(current)
            return diagnostics(2 + len(seen) - 1)

        result = salvage.salvage("T", proof, never_compiles)
        self.assertEqual((result["status"], result["compiles"], len(seen)), ("broken-pass-limit", 6, 6))

    def test_salvage_has_no_input_size_threshold(self):
        for proof in (
            "theorem t : True := by\n  bad\n  exact True.intro",
            "theorem t : True := by\n" + "\n".join(["  exact True.intro"] * 98 + ["  bad"]),
        ):
            compile, seen = scripted([diagnostics(len(proof.splitlines()))])
            salvage.salvage("T", proof, compile)
            self.assertGreaterEqual(len(seen), 1)


class HoleTests(unittest.TestCase):
    def test_holes_ignore_comments_and_attach_goals_and_stated_types(self):
        proof = "theorem t : True := by\n  have h : True := sorry\n  exact sorry -- sorry\n  /- sorry\n     /- nested sorry -/ -/\n  trivial"
        rows = salvage.holes(proof, [{"proof_line": 3, "goals": ["P"]}, {"proof_line": 3, "goals": ["Q"]}])
        self.assertEqual([(row["index"], row["line"], row["column"]) for row in rows], [(1, 2, 20), (2, 3, 9)])
        self.assertEqual([(row["goal"], row["goal_source"]) for row in rows], [("True", "stated"), ("P", "lean")])

    def test_multiple_holes_on_one_line_take_goals_in_source_order(self):
        proof = "theorem t := by\n  exact (show True from sorry) ∧ (show True from sorry)"
        rows = salvage.holes(
            proof,
            [{"proof_line": 2, "goals": ["first"]}, {"proof_line": 2, "goals": ["second"]}],
        )
        self.assertEqual([row["goal"] for row in rows], ["first", "second"])
        self.assertEqual([row["column"] for row in rows], sorted(row["column"] for row in rows))

    def test_fill_text_preserves_source_and_indents_continuations(self):
        proof = "theorem t : True := by\n  exact sorry -- keep\n  have h : True :=\n    sorry\n"
        first = {"line": 2, "column": 9}
        second = {"line": 4, "column": 5}
        result = salvage.fill_text(proof, second, "by\nexact True.intro")
        result = salvage.fill_text(result, first, "exact\nTrue.intro")
        self.assertIn("exact exact\n    True.intro -- keep", result)
        self.assertIn("    by\n    exact True.intro", result)
        with self.assertRaises(ValueError):
            salvage.fill_text(proof, {"line": 2, "column": 3}, "exact h")


class SalvageCampaignTests(FakeRunCase):
    def test_full_candidate_arriving_during_salvage_runs_before_next_salvage_compile(self):
        with (
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
        ):
            campaign.probe("T", "logic", "bad\nexact True.intro")
            salvage_calls = []

            def compile_salvage(_name, proof):
                salvage_calls.append(proof)
                if len(salvage_calls) == 1:
                    campaign.probe("T", "logic", "exact True.intro")
                    return diagnostics(2)
                return {"clean": True, "error_lines": [], "unlocated": False, "result": {"compat": {"v1": {"passed": True}}}}

            with patch.object(campaign, "_salvage_compile", side_effect=compile_salvage):
                outcome = campaign.autocheck("T", "logic")
            history = campaign.events(self.directory)
            deferred = next(item for item in history if item.get("kind") == "salvage" and item.get("status") == "deferred")
            full_seq = next(
                seq for seq, item in enumerate(history)
                if item.get("kind") == "evaluation" and item.get("mode") == "full" and item.get("trigger") == "auto"
            )
            deferred_seq = next(seq for seq, item in enumerate(history) if item is deferred)
            self.assertEqual(deferred["reason"], "full_check_arrived")
            self.assertEqual(deferred["compiles"], 1)
            self.assertLess(deferred_seq, full_seq)
            self.assertEqual(len(salvage_calls), 2)
            self.assertTrue(outcome["ok"])

    def test_salvage_soft_cap_finishes_active_compile_then_resumes_without_repeating_it(self):
        with (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
        ):
            campaign.probe("T", "logic", "bad\nexact True.intro")
            node = campaign._salvage_jobs(campaign.events(self.directory), self.directory)[0]
            with (
                patch.object(campaign, "_salvage_compile", return_value=diagnostics(2)) as compile_salvage,
                patch.object(campaign.time, "monotonic", side_effect=[10, 10, 71, 71]),
            ):
                deferred = campaign._run_salvage("T", "logic", node)
            self.assertEqual((deferred["status"], deferred["reason"], deferred["compiles"]), ("deferred", "salvage_soft_cap_exhausted", 1))
            self.assertEqual(compile_salvage.call_count, 1)
            self.assertNotEqual(deferred["continuation"]["current"], node.proof_text)
            self.assertEqual(len(campaign._salvage_jobs(campaign.events(self.directory), self.directory)), 1)

            with patch.object(
                campaign,
                "_salvage_compile",
                return_value={"clean": True, "error_lines": [], "unlocated": False, "result": {"compat": {"v1": {"passed": True}}}},
            ) as resumed_compile:
                resumed = campaign._run_salvage("T", "logic", node)
            self.assertEqual((resumed["status"], resumed["compiles"]), ("salvaged", 2))
            self.assertEqual(resumed_compile.call_count, 1)
            self.assertEqual(resumed_compile.call_args.args[1], deferred["continuation"]["current"])

    def test_source_drafts_are_listed_compactly_in_one_line(self):
        self.assertEqual(campaign._compact_ids(["n2", "n3", "n4", "n5", "n9", "n11", "n12"]), "n2–n5, n9, n11–n12")
        self.assertEqual(campaign._compact_ids(["n7"]), "n7")

    def test_failed_probe_is_salvaged_once_and_published_as_an_update(self):
        with (
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "_step_goal_jobs", return_value=[]),
        ):
            campaign.probe("T", "logic", "bad\nexact True.intro")
            proof_id = hashlib.sha256(
                ("T\0" + "theorem t : True := by\n  bad\n  exact True.intro").encode()
            ).hexdigest()
            first = campaign.autocheck("T", "logic")
            history = campaign.events(self.directory)
            salvage_event = next(item for item in history if item.get("kind") == "salvage")
            sketch_id = salvage_event["sketch_id"]
            self.assertEqual(salvage_event["status"], "salvaged")
            self.assertIsInstance(salvage_event["seconds"], float)
            edge = next(item for item in history if item.get("kind") == "edge" and item.get("proof_id") == sketch_id)
            self.assertEqual((edge["type"], edge["from"], edge["exact"]), ("salvaged_from", [proof_id], True))
            self.assertTrue(any(item.get("kind") == "route" and item.get("proof_id") == sketch_id for item in history))
            notice = next(
                item["text"] for item in campaign.state("logic")["updates"] if "compiling part of" in item["text"]
            )
            self.assertRegex(
                notice, r"^n\d+: compiling part of n\d+; line \d+ is a hole to fill \(`fill` hole n\d+\.h1\)\.$"
            )
            self.assertEqual(campaign.autocheck("T", "logic")["checked"], [])
            self.assertTrue(first["ok"])

    def autocheck_kinds(self, closing, kinds=None):
        """Salvage, step-goal and auto full-check events in ledger order after one autocheck."""
        with (
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
        ):
            campaign.probe("T", "logic", "bad\nexact True.intro")
            self.evaluate("theorem t : True := by\n  a")
            outcome = campaign.autocheck("T", "logic", closing=closing, kinds=kinds)
        kinds = [
            "full" if item.get("kind") == "evaluation" else item["kind"]
            for item in campaign.events(self.directory)
            if item.get("kind") in ("salvage", "step_goals")
            or (item.get("kind") == "evaluation" and item.get("trigger") == "auto")
        ]
        return outcome, kinds

    def test_closing_drain_runs_full_checks_and_skips_salvage_and_step_goals(self):
        outcome, kinds = self.autocheck_kinds(closing=True)
        self.assertEqual(outcome["checked"], ["#2"])
        self.assertEqual(kinds, ["full"])

    def test_closing_drain_cap_leaves_candidates_unchecked_and_records_it(self):
        with (
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
        ):
            self.evaluate("theorem t : True := by\n  a")
            outcome = campaign.autocheck("T", "logic", 0, closing=True)
        self.assertEqual((outcome["checked"], outcome["remaining"], outcome["timed_out"]), ([], ["#2"], True))
        drain = [e for e in campaign.events(self.directory) if e.get("kind") == "closing_drain"][-1]
        self.assertEqual((drain["timed_out"], drain["unchecked_at_cap"]), (True, ["#2"]))

    def test_full_only_drain_skips_salvage_step_goals_and_profiles(self):
        outcome, kinds = self.autocheck_kinds(closing=False, kinds=("full",))
        self.assertEqual(outcome["checked"], ["#2"])
        self.assertEqual(kinds, ["full"])
        self.assertFalse(
            any(item.get("kind") in ("profile", "profile_error") for item in campaign.events(self.directory))
        )

    def test_background_drain_runs_full_checks_before_salvage(self):
        outcome, kinds = self.autocheck_kinds(closing=False)
        self.assertEqual(outcome["checked"], ["#2"])
        self.assertEqual(kinds[:2], ["full", "salvage"])

    def test_interrupted_job_is_requeued_and_unavailable_is_terminal_without_notice(self):
        with (
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t : True"}),
            patch.object(campaign, "_autocheck_jobs", return_value=[]),
            patch.object(campaign, "_step_goal_jobs", return_value=[]),
        ):
            campaign.probe("T", "logic", "bad\nexact True.intro")
            with (
                patch.object(campaign, "_salvage_compile", side_effect=RuntimeError("interrupted")),
                self.assertRaises(RuntimeError),
            ):
                campaign.autocheck("T", "logic")
            self.assertEqual(
                campaign._salvage_jobs(campaign.events(self.directory), self.directory)[0].status, "broken"
            )
            with patch.object(campaign, "_salvage_compile", side_effect=ValueError("service unavailable")):
                campaign.autocheck("T", "logic")
            events = [item for item in campaign.events(self.directory) if item.get("kind") == "salvage"]
            self.assertEqual((len(events), events[0]["status"], events[0]["compiles"]), (1, "unavailable", 1))
            self.assertFalse(any("compiling part of" in item["text"] for item in campaign.state("logic")["updates"]))
            campaign.autocheck("T", "logic")
            self.assertEqual(
                len([item for item in campaign.events(self.directory) if item.get("kind") == "salvage"]), 1
            )


class FillAndMapTests(FakeRunCase):
    def test_fill_operation_creates_first_class_hole_and_map_row(self):
        proof = "theorem t := by\n  have h : True := sorry\n  exact h"
        sketch_id = "a" * 64
        campaign._snapshot(self.directory, sketch_id, proof)
        campaign._append(
            self.directory,
            {"kind": "probe", "proof_id": sketch_id, "result": {"compat": {"v1": {"passed": True}}, "goals": []}},
        )
        campaign._file_node(
            self.directory,
            campaign.events(self.directory),
            sketch_id,
            proof,
            operation={"type": "salvaged_from", "from": ["root"]},
        )
        with patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t := by"}):
            projection = graph.Graph.from_history(
                campaign.events(self.directory), campaign._proof_reader(self.directory)
            )
        hole_id = f"{projection.nodes[-1].id}.h1"
        with self.assertRaisesRegex(ValueError, "n999.h1.*line"):
            campaign.compile_operation("T", "logic", {"type": "fill", "hole": "n999.h1", "text": "exact h"})
        with self.assertRaisesRegex(ValueError, "is not an open hole"):
            campaign.compile_operation(
                "T", "logic", {"type": "fill", "hole": f"{projection.nodes[0].id}.h1", "text": "exact h"}
            )
        with patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t := by"}):
            result = campaign.compile_operation(
                "T", "logic", {"type": "fill", "hole": hole_id, "text": "exact True.intro"}
            )
        fill_id = next(
            item["candidate_id"]
            for item in campaign.events(self.directory)
            if item.get("kind") == "candidate" and item.get("origin") != "reference"
        )
        edge = next(
            item
            for item in campaign.events(self.directory)
            if item.get("kind") == "edge" and item.get("proof_id") == fill_id
        )
        self.assertEqual(
            (edge["type"], edge["from"], edge["operation"]),
            ("filled_from", [sketch_id], {"hole": hole_id, "text": "exact True.intro"}),
        )
        self.assertIn("node", result)
        graph_after = graph.Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        sketch = next(node for node in graph_after.nodes if node.proof_id == sketch_id)
        self.assertEqual(
            (sketch.holes[0]["status"], sketch.holes[0]["filled_by"]), ("filled", graph_after.nodes[-1].id)
        )
        self.assertEqual(graph.map_view(graph_after)["open"], [])

    def test_fill_containing_sorry_does_not_close_a_hole(self):
        proof = "theorem t := by\n  have h : True := by\n    sorry\n  exact h"
        sketch_id = "c" * 64
        campaign._snapshot(self.directory, sketch_id, proof)
        campaign._append(
            self.directory,
            {"kind": "probe", "proof_id": sketch_id, "result": {"compat": {"v1": {"passed": True}}}},
        )
        campaign._file_node(
            self.directory,
            campaign.events(self.directory),
            sketch_id,
            proof,
            operation={"type": "salvaged_from", "from": ["failed"]},
        )
        before = graph.Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        sketch = next(node for node in before.nodes if node.proof_id == sketch_id)
        fill_id = "d" * 64
        fill_proof = proof.replace("    sorry", "    sorry\n    exact True.intro")
        campaign._snapshot(self.directory, fill_id, fill_proof)
        campaign._append(
            self.directory,
            {"kind": "candidate", "candidate_id": fill_id, "origin": "model", "parents": [sketch_id]},
        )
        campaign._append(
            self.directory,
            {
                "kind": "evaluation",
                "candidate_id": fill_id,
                "mode": "fast",
                "result": {"compat": {"v1": {"passed": True}}, "tokens": 1},
            },
        )
        campaign._append(
            self.directory,
            {
                "kind": "edge",
                "proof_id": fill_id,
                "type": "filled_from",
                "from": [sketch_id],
                "operation": {"hole": f"{sketch.id}.h1", "text": "by\n  sorry"},
            },
        )
        broken_id = "e" * 64
        broken_proof = proof.replace("    sorry", "    exact True.intro")
        campaign._snapshot(self.directory, broken_id, broken_proof)
        campaign._append(
            self.directory,
            {"kind": "candidate", "candidate_id": broken_id, "origin": "model", "parents": [sketch_id]},
        )
        campaign._append(
            self.directory,
            {
                "kind": "evaluation",
                "candidate_id": broken_id,
                "mode": "fast",
                "result": {"compat": {"v1": {"passed": False}}, "tokens": 1},
            },
        )
        campaign._append(
            self.directory,
            {
                "kind": "edge",
                "proof_id": broken_id,
                "type": "filled_from",
                "from": [sketch_id],
                "exact": True,
                "operation": {"hole": f"{sketch.id}.h1", "text": "exact True.intro"},
            },
        )
        after = graph.Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
        sketch_after = next(node for node in after.nodes if node.proof_id == sketch_id)
        self.assertEqual(sketch_after.holes[0]["status"], "open")

    def test_assembly_waits_for_every_hole_and_uses_cheapest_closing_fills(self):
        proof = "theorem t := by\n  have h : True := by\n    sorry\n  have k : True := by\n    sorry\n  exact h"
        sketch_id = "b" * 64
        campaign._snapshot(self.directory, sketch_id, proof)
        campaign._append(
            self.directory,
            {
                "kind": "probe",
                "proof_id": sketch_id,
                "result": {
                    "compat": {"v1": {"passed": True}},
                    "goals": [{"proof_line": 3, "goals": ["⊢ True"]}, {"proof_line": 5, "goals": ["⊢ True"]}],
                },
            },
        )
        campaign._file_node(
            self.directory,
            campaign.events(self.directory),
            sketch_id,
            proof,
            operation={"type": "salvaged_from", "from": ["failed"]},
        )
        with patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t := by"}):
            current = graph.Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
            sketch = next(node for node in current.nodes if node.proof_id == sketch_id)
            self.assertEqual(graph.map_view(current)["open"][0]["hole"], f"{sketch.id}.h1")
            campaign.compile_operation(
                "T", "logic", {"type": "fill", "hole": f"{sketch.id}.h1", "text": "exact True.intro"}
            )
            first_id = campaign._candidate_ids(campaign.events(self.directory))[-1]
            self.assertEqual(campaign._assembly_jobs(campaign.events(self.directory), self.directory), [])
            campaign.compile_operation(
                "T", "logic", {"type": "fill", "hole": f"{sketch.id}.h1", "text": "exact (show True from True.intro)"}
            )
            costly_id = campaign._candidate_ids(campaign.events(self.directory))[-1]
            campaign.compile_operation(
                "T", "logic", {"type": "fill", "hole": f"{sketch.id}.h2", "text": "exact True.intro"}
            )
            second_id = campaign._candidate_ids(campaign.events(self.directory))[-1]
            with (
                patch.object(campaign.lean_health, "tripped", return_value=False),
                patch.object(campaign, "_autocheck_jobs", return_value=[]),
                patch.object(campaign, "_step_goal_jobs", return_value=[]),
            ):
                campaign.autocheck("T", "logic")
                history = campaign.events(self.directory)
                event = next(item for item in history if item.get("kind") == "assembly")
                self.assertEqual(event["status"], "closed", event.get("error"))
                self.assertEqual(event["fills"][f"{sketch.id}.h1"], first_id)
                self.assertEqual(event["fills"][f"{sketch.id}.h2"], second_id)
                self.assertEqual(event["alternatives"][f"{sketch.id}.h1"], [costly_id])
                edge = next(
                    item for item in history if item.get("kind") == "edge" and item.get("proof_id") == event["node"]
                )
                self.assertEqual(edge["type"], "merged_from")
                self.assertEqual(edge["from"], [sketch_id, first_id, second_id])
                self.assertEqual(edge["operation"]["assembly"], True)
                notice = next(
                    item["text"] for item in campaign.state("logic")["updates"] if "assembled from" in item["text"]
                )
                self.assertIn("Other fills", notice)
                campaign.autocheck("T", "logic")
                self.assertEqual(
                    len([item for item in campaign.events(self.directory) if item.get("kind") == "assembly"]), 1
                )

    def test_broken_assembly_becomes_a_salvage_job(self):
        proof = "theorem t := by\n  have h : True := by\n    sorry\n  exact h"
        sketch_id = "f" * 64
        campaign._snapshot(self.directory, sketch_id, proof)
        campaign._append(
            self.directory,
            {"kind": "probe", "proof_id": sketch_id, "result": {"compat": {"v1": {"passed": True}}}},
        )
        campaign._file_node(
            self.directory,
            campaign.events(self.directory),
            sketch_id,
            proof,
            operation={"type": "salvaged_from", "from": ["failed"]},
        )
        with patch.object(campaign, "problem", return_value={"name": "T", "statement": "theorem t := by"}):
            current = graph.Graph.from_history(campaign.events(self.directory), campaign._proof_reader(self.directory))
            sketch = next(node for node in current.nodes if node.proof_id == sketch_id)
            fill_proof = proof.replace("    sorry", "    exact True.intro")
            fill_id = "1" * 64
            campaign._snapshot(self.directory, fill_id, fill_proof)
            campaign._append(
                self.directory,
                {"kind": "candidate", "candidate_id": fill_id, "origin": "model", "parents": [sketch_id]},
            )
            campaign._append(
                self.directory,
                {
                    "kind": "evaluation",
                    "candidate_id": fill_id,
                    "key": "fill-key",
                    "mode": "fast",
                    "result": {"compat": {"v1": {"passed": True}}, "tokens": 1},
                },
            )
            campaign._file_node(
                self.directory,
                campaign.events(self.directory),
                fill_id,
                fill_proof,
                operation={
                    "type": "filled_from",
                    "from": [sketch_id],
                    "hole": f"{sketch.id}.h1",
                    "text": "exact True.intro",
                },
            )
            after_fill = graph.Graph.from_history(
                campaign.events(self.directory), campaign._proof_reader(self.directory)
            )
            filled_sketch = next(node for node in after_fill.nodes if node.proof_id == sketch_id)
            self.assertTrue(filled_sketch.holes[0]["fills"])
            sketch = filled_sketch
            broken = {"ok": True, "mode": "fast", "tokens": 1, "compat": {"v1": {"passed": False, "diagnostics": []}}}
            with patch.object(campaign, "evaluate", return_value=broken):
                campaign._run_assembly("T", "logic", sketch)
            assembly = next(item for item in campaign.events(self.directory) if item.get("kind") == "assembly")
            self.assertEqual(assembly["status"], "broken", assembly.get("error"))
            broken_node = next(
                node
                for node in graph.Graph.from_history(
                    campaign.events(self.directory), campaign._proof_reader(self.directory)
                ).nodes
                if node.proof_id == assembly["node"]
            )
            self.assertEqual(broken_node.status, "broken")
            with (
                patch.object(campaign.lean_health, "tripped", return_value=False),
                patch.object(campaign, "_autocheck_jobs", return_value=[]),
                patch.object(campaign, "_step_goal_jobs", return_value=[]),
                patch.object(campaign, "_salvage_compile", side_effect=ValueError("unavailable")),
            ):
                campaign.autocheck("T", "logic")
            salvage_event = next(
                item
                for item in campaign.events(self.directory)
                if item.get("kind") == "salvage" and item.get("proof_id") == assembly["node"]
            )
            self.assertEqual(salvage_event["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()


class ClosingDrainSkipTests(unittest.TestCase):
    @staticmethod
    def row(n, status, score, verified=False, full=False):
        evaluations = [{"mode": "full" if full else "fast", "status": status, "result": {}, "score": score}]
        return {
            "id": f"p{n}", "n": n, "origin": "model", "status": status, "score": score,
            "verified": verified, "evaluations": evaluations,
        }  # fmt: skip

    def test_closing_drain_skips_candidates_that_cannot_beat_the_verified_best(self):
        rows = [
            self.row(1, "full", 90.0, verified=True, full=True),
            self.row(2, "primary", 80.0),
            self.row(3, "primary", 90.0),
            self.row(4, "primary", 95.0),
            self.row(5, "primary", None),
        ]
        jobs = campaign._autocheck_jobs(rows, closing=True)
        self.assertEqual([r["n"] for r in jobs], [4, 3, 5])

    def test_closing_drain_keeps_everything_without_a_verified_best(self):
        rows = [self.row(1, "primary", 10.0), self.row(2, "primary", 90.0)]
        self.assertEqual([r["n"] for r in campaign._autocheck_jobs(rows, closing=True)], [2, 1])
