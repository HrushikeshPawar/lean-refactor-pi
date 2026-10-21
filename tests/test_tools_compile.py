import contextlib
import hashlib
import io
import json
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import campaign, tools
from arena.cli.protocol import ProtocolOptions, execute
from tests.graph_support import FakeRunCase

ROW = {
    "name": "T",
    "statement": "theorem t : True",
    "src": "theorem t : True := by\n  trivial",
    "version_info": [{"v1": "a"}],
}


class CascadeCase(FakeRunCase):
    cascade_errors = True

    def setUp(self):
        super().setUp()
        row_patch = patch.object(campaign, "problem", return_value=ROW)
        row_patch.start()
        self.addCleanup(row_patch.stop)
        worker_patch = patch.object(campaign, "_probe_workers", return_value=1)
        worker_patch.start()
        self.addCleanup(worker_patch.stop)
        autocheck_patch = patch.object(campaign, "autocheck", return_value={"checked": []})
        autocheck_patch.start()
        self.addCleanup(autocheck_patch.stop)


class NoGoalCase(CascadeCase):
    no_goal_marker = "sorry"


class CompileToolTests(CascadeCase):
    def test_invalid_operation_and_unknown_graph_references_report_input_and_forms(self):
        empty = tools.compile_tool("T", "logic", {})
        self.assertEqual(empty["error"]["code"], "empty_arguments")
        no_operation = tools.compile_tool("T", "logic", {"note": "audit"})
        self.assertEqual(no_operation["error"]["code"], "bad_operation")
        two_operations = tools.compile_tool(
            "T", "logic", {"drafts": ["by trivial"], "fill": {"hole": "n999.h1", "text": "trivial"}}
        )
        self.assertEqual(two_operations["error"]["code"], "bad_operation")
        for request in (
            {"drafts": ["by trivial"], "base": "n999"},
            {"fill": {"hole": "n999.h1", "text": "trivial"}},
        ):
            result = tools.compile_tool("T", "logic", request)
            error = result["error"] if not result["ok"] else result["items"][0]["error"]
            self.assertTrue(error["input"])
            self.assertTrue(error["valid"])
            self.assertTrue(error["forms"])

    def test_two_drafts_return_closed_and_all_cascading_errors(self):
        result = tools.compile_tool(
            "T",
            "logic",
            {"drafts": ["by\n  bad\n  bad\n  bad", "by\n  trivial"]},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["items"]), 2)
        broken, closed = result["items"]
        self.assertEqual([item["id"] for item in broken["errors"]], ["n2.e1", "n2.e2", "n2.e3"])
        self.assertTrue(all(item["goal"] for item in broken["errors"]))
        self.assertEqual(broken["status"], "broken")
        self.assertEqual(closed["status"], "closed")
        self.assertIsNotNone(closed["price"])
        self.assertTrue(any("new root" in line or "focus" in line for line in closed["lines"]))
        self.assertNotIn("sorry", str(result))
        proof_ids = [event["proof_id"] for event in campaign.events(self.directory) if event.get("kind") == "probe"]
        self.assertEqual(len(set(proof_ids)), 1)
        self.assertEqual(sum(event.get("kind") == "edge" for event in campaign.events(self.directory)), 3)

    def test_repeated_identical_fill_says_so_and_marks_the_item(self):
        sketch = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
        request = {"fill": {"hole": f"{sketch}.h1", "text": "bad\n  bad"}}
        first, second, third = (tools.compile_tool("T", "logic", request) for _ in range(3))
        self.assertFalse(first["items"][0]["repeat"])
        self.assertNotIn("identical", str(first["facts"]))
        node = first["items"][0]["node"]
        self.assertTrue(second["items"][0]["repeat"])
        self.assertTrue(third["items"][0]["repeat"])
        self.assertEqual(third["items"][0]["node"], node)
        # A repeat fact names this call's own node, so it is part of the result section.
        self.assertIn(
            f"{node} is identical to an earlier attempt (seen 3 times)", "\n".join(third["items"][0]["lines"])
        )
        self.assertIn("seen 2 times", "\n".join(second["items"][0]["lines"]))

    def test_tokens_do_not_file_or_compile(self):
        before = len(campaign.events(self.directory))
        with patch("arena.engine._proof_length", side_effect=lambda proof, *_: len(proof)):
            result = tools.compile_tool("T", "logic", {"check": "tokens", "drafts": ["by trivial"]})
        normalized = campaign.normalize_draft("T", "by trivial")
        self.assertEqual(result["items"][0]["tokens"], len(normalized))
        self.assertEqual(len(campaign.events(self.directory)), before)

    def test_duplicate_text_is_filed_once(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial", "by\n  trivial"]})
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(any("same text" in line.lower() for line in result["items"][1]["lines"]))
        self.assertEqual([item["ref"] for item in result["items"]], ["d1", "d2"])
        self.assertEqual(result["items"][1]["same_as"], "d1")
        self.assertEqual(result["items"][1]["status"], result["items"][0]["status"])
        self.assertIn("errors", result["items"][1])
        nodes = tools._nodes("logic")[1].nodes
        expected = hashlib.sha256(("T\0" + ROW["statement"] + " := by\n  trivial").encode()).hexdigest()
        self.assertEqual(sum(node.proof_id == expected for node in nodes), 1)
        first, repeated = result["items"]
        self.assertNotEqual(first["attempt_id"], repeated["attempt_id"])
        self.assertNotEqual(first["construction_operation_id"], repeated["construction_operation_id"])
        self.assertEqual(first["evaluation_id"], repeated["evaluation_id"])
        self.assertEqual(first["verification"], {"primary": "passed", "full": "pending", "cold": "not_checked"})
        self.assertEqual(first["inputs"], [])
        self.assertIsNone(first["best"])  # The existing reference is shorter.
        self.assertIn("primary passed; full pending; cold not_checked", "\n".join(first["lines"]))
        for item in (first, repeated):
            self.assertNotIn(item["attempt_id"], "\n".join(item["lines"]))
        base = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
        replacement = tools.compile_tool("T", "logic", {"base": base, "drafts": ["by\n  trivial"], "from": "n1"})["items"][0]
        self.assertEqual(replacement["node"], first["node"])
        self.assertEqual([(source["role"], source["node"]) for source in replacement["inputs"]],
                         [("base", base), ("named_parent", "n1")])
        self.assertIn(f"made from {base} as a new draft", "\n".join(replacement["lines"]))
        self.assertIn("tokens", replacement["comparisons"][0]["deltas"])
        self.assertNotEqual(first["attempt_id"], replacement["attempt_id"])
        failed = tools.compile_tool("T", "logic", {"splice": {"base": base, "steps": "s1", "text": "bad"}})["items"][0]
        self.assertEqual(failed["verification"]["primary"], "proof_error")
        self.assertEqual(failed["inputs"][0]["node"], base)
        self.assertTrue(failed["attempt_id"])
        self.assertIsNone(failed["best"])
        self.assertNotIn("heartbeats", failed["comparisons"][0]["deltas"])
        independent = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"], "from": base})["items"][0]
        self.assertEqual(independent["inputs"], [{"role": "named_parent", "proof_id": tools._node("logic", base).proof_id,
                                                 "node": base}])
        self.assertNotEqual(independent["attempt_id"], replacement["attempt_id"])
        self.assertNotEqual(independent["derivation_id"], replacement["derivation_id"])
        self.assertEqual(tools._node("logic", first["node"]).edge["type"], "root")
        campaign.record_evaluation("T", "logic", tools._node("logic", first["node"]).proof_text, "full")
        certified = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})["items"][0]
        self.assertEqual(certified["verification"]["full"], "passed")
        self.assertEqual(certified["best"], "all-pin verified best")
        worse = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial\n  trivial"]})["items"][0]
        self.assertIsNone(worse["best"])

    def test_more_errors_than_pass_limit_are_reported_as_incomplete(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n" + "\n".join(["  bad"] * 5)]})
        self.assertEqual(len(result["items"][0]["errors"]), 4)
        node = result["items"][0]["node"]
        # A note about a node this call filed sits in that node's result, not under Updates.
        lines = result["items"][0]["lines"]
        self.assertTrue(
            any(line.startswith(f"{node}: Lean may report more errors after line") for line in lines), lines
        )
        self.assertEqual(result["facts"], [])

    def test_splice_fill_and_merge_record_exact_graph_edges(self):
        base = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})["items"][0]["node"]
        splice = tools.compile_tool("T", "logic", {"splice": {"base": base, "steps": "s1", "text": "bad"}})
        splice_id = tools._node("logic", splice["items"][0]["node"]).proof_id
        splice_edge = next(
            event
            for event in reversed(campaign.events(self.directory))
            if event.get("kind") == "edge" and event.get("proof_id") == splice_id
        )
        self.assertEqual((splice_edge["type"], splice_edge["operation"]["steps"]), ("edited_from", "s1"))
        sketch = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
        filled = tools.compile_tool("T", "logic", {"fill": {"hole": f"{sketch}.h1", "text": "bad\n  bad"}})
        fill_id = tools._node("logic", filled["items"][0]["node"]).proof_id
        fill_edge = next(
            event
            for event in reversed(campaign.events(self.directory))
            if event.get("kind") == "edge" and event.get("proof_id") == fill_id
        )
        self.assertEqual(fill_edge["type"], "filled_from")
        nodes = tools._nodes("logic")[1].nodes
        donor = next(node for node in nodes if node.id == base)
        merge_base = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  bad"]})["items"][0]["node"]
        merged = tools.compile_tool(
            "T", "logic", {"merge": {"base": merge_base, "take": [{"from": base, "step": "s1"}]}}
        )
        merge_id = tools._node("logic", merged["items"][0]["node"]).proof_id
        merge_edge = next(
            event
            for event in reversed(campaign.events(self.directory))
            if event.get("kind") == "edge" and event.get("proof_id") == merge_id
        )
        self.assertEqual(merge_edge["type"], "merged_from")
        self.assertEqual(merge_edge["operation"]["take"][0]["step"], "s1")
        self.assertEqual(donor.id, base)
        self.assertEqual([(source["role"], source["node"]) for source in merged["items"][0]["inputs"]],
                         [("base", merge_base), ("donor", base)])
        self.assertEqual(merged["items"][0]["inputs"][1]["step"], "s1")
        self.assertTrue(merged["items"][0]["attempt_id"])

    def test_v8_duplicate_attempt_roundtrip(self):
        from arena import run_control
        from arena.cli.serve import graph_payload
        from arena.graph import Graph
        from arena.replay import load_run
        from arena.viewer_data import node_calls

        directory = self.directory
        calls = []

        def once(ctx):
            calls.append("mutate")
            return [ctx.append_ledger({"kind": "attempt", "proof_id": "receipt-only", "data": {"marker": "once"}})]

        operation = {
            "operation_id": "op-same",
            "kind": "compile",
            "arguments": {"n": 1},
            "run_id": "logic",
            "actor_id": "sol",
            "session_id": "session-1",
        }
        first = run_control.apply_operation(directory, operation, once)
        replayed = run_control.apply_operation(directory, operation, once)
        self.assertEqual(calls, ["mutate"])
        self.assertEqual(replayed["operation_id"], first["operation_id"])
        self.assertEqual(replayed["event_seq"], first["event_seq"])
        self.assertEqual(replayed["evidence_refs"], first["evidence_refs"])
        conflict = run_control.apply_operation(directory, {**operation, "arguments": {"n": 2}}, once)
        self.assertEqual(conflict["status"], "operation_conflict")
        self.assertEqual(calls, ["mutate"])

        filed = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"], "from": "n1"})
        node_id = filed["items"][0]["node"]
        proof_id = tools._node("logic", node_id).proof_id
        ledger_path = directory / "ledger.jsonl"
        proof_path = directory / "proofs" / f"{proof_id}.lean"
        original_ledger = ledger_path.read_bytes()
        edge_line = next(
            line
            for line in original_ledger.splitlines(keepends=True)
            if b'"kind":"edge"' in line and proof_id.encode() in line
        )
        original_proof = proof_path.read_bytes()
        edge = next(
            event
            for event in campaign.events(directory)
            if event.get("kind") == "edge" and event.get("proof_id") == proof_id
        )
        self.assertNotEqual(edge["type"], "edited_from")
        self.assertTrue(edge["named_parent"])

        base = tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]
        second = tools.compile_tool("T", "logic", {"base": base, "drafts": ["by\n  trivial"]})
        self.assertEqual(second["items"][0]["node"], node_id)
        self.assertGreaterEqual(len(second["items"][0]["derivations"]), 2)
        self.assertGreaterEqual(len(second["items"][0]["attempts"]), 2)

        reloaded = ledger_path.read_bytes()
        self.assertIn(edge_line, reloaded)
        self.assertEqual(proof_path.read_bytes(), original_proof)
        history = campaign.events(directory)
        projection = Graph.from_history(
            history,
            campaign._proof_reader(directory),
            committed_operations=run_control.committed_operation_ids(directory),
        )
        canonical = [node for node in projection.nodes if node.proof_id == proof_id]
        self.assertEqual(len(canonical), 1)
        self.assertGreaterEqual(len(canonical[0].derivations), 2)
        self.assertGreaterEqual(len(canonical[0].attempts), 2)
        relations = {item["relation"] for item in canonical[0].derivations}
        self.assertIn("exact", relations)
        self.assertTrue(relations - {"exact"})

        def interrupted(ctx):
            for kind in ("attempt", "derivation"):
                ctx.append_ledger({"kind": kind, "proof_id": proof_id, "data": {"marker": "aborted"}})
            raise RuntimeError("interrupted before commit")

        with self.assertRaisesRegex(RuntimeError, "interrupted before commit"):
            run_control.apply_operation(directory, {**operation, "operation_id": "op-aborted"}, interrupted)
        campaign._append(
            directory,
            {
                "kind": "attempt",
                "proof_id": proof_id,
                "operation_id": "op-no-receipt",
                "data": {},
            },
        )
        raw_history = campaign.events(directory)
        without_receipts = Graph.from_history(raw_history, campaign._proof_reader(directory))
        # Candidate rows are committed under an operation; without receipts the proof is not a canonical node.
        self.assertEqual([node for node in without_receipts.nodes if node.proof_id == proof_id], [])
        checked = Graph.from_history(
            raw_history,
            campaign._proof_reader(directory),
            committed_operations=run_control.committed_operation_ids(directory),
        )
        checked_node = next(node for node in checked.nodes if node.proof_id == proof_id)
        self.assertEqual(checked_node.attempts, canonical[0].attempts)
        self.assertEqual(checked_node.derivations, canonical[0].derivations)
        self.assertEqual(ledger_path.read_bytes()[: len(reloaded)], reloaded)

        served = next(node for node in graph_payload("logic")["nodes"] if node["id"] == proof_id)
        self.assertGreaterEqual(len(served["derivations"]), 2)
        detail = node_calls(directory, node_id)
        self.assertGreaterEqual(len(detail["attempts"]), 2)
        self.assertGreaterEqual(len(detail["derivations"]), 2)

        (directory / "trace-journal.jsonl").write_text(
            '{"kind":"request","id":"r1","turn":1,"ts":1}\n', encoding="utf-8"
        )
        loaded = load_run("logic", directory.parent)
        replayed_graph = Graph.from_history(
            loaded.ledger,
            campaign._proof_reader(directory),
            committed_operations=run_control.committed_operation_ids(directory),
        )
        replayed_node = next(node for node in replayed_graph.nodes if node.proof_id == proof_id)
        self.assertEqual(
            [item["relation"] for item in replayed_node.derivations],
            [item["relation"] for item in canonical[0].derivations],
        )
        self.assertEqual(len(replayed_node.attempts), len(canonical[0].attempts))
        copied = directory.parent / "reloaded"
        copied.mkdir()
        (copied / "ledger.jsonl").write_bytes(ledger_path.read_bytes())
        (copied / "control.jsonl").write_bytes((directory / "control.jsonl").read_bytes())
        proofs = copied / "proofs"
        proofs.mkdir()
        (proofs / proof_path.name).write_bytes(original_proof)
        reloaded_graph = Graph.from_history(
            campaign.events(copied),
            lambda ident: (proofs / f"{ident}.lean").read_text() if ident == proof_id else None,
            committed_operations=run_control.committed_operation_ids(copied),
        )
        self.assertEqual(len([node for node in reloaded_graph.nodes if node.proof_id == proof_id]), 1)
        self.assertGreaterEqual(
            len(next(node for node in reloaded_graph.nodes if node.proof_id == proof_id).derivations), 2
        )

    def test_v8_actor_focus_delivery_eligibility(self):
        import os

        from arena import reply

        run_id = "logic"
        parent = tools.compile_tool("T", run_id, {"drafts": ["by\n  trivial"]})
        parent_id = parent["items"][0]["node"]
        parent_proof = tools._node(run_id, parent_id).proof_id
        self.assertEqual(reply.actor_focus_proof(run_id), parent_proof)
        other = tools.compile_tool("T", run_id, {"drafts": ["by\n  sorry"]})
        other_id = other["items"][0]["node"]
        other_proof = tools._node(run_id, other_id).proof_id
        self.assertEqual(parent["items"][0]["eligibility"], "eligible")
        self.assertIn("verification", parent["items"][0])

        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "worker"}):
            reply.set_actor_focus(run_id, parent_proof)
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol"}):
            reply.set_actor_focus(run_id, other_proof)
        stale = reply._load(run_id)
        reply.set_actor_focus(run_id, other_proof, actor="another-worker")
        reply._write_actor(run_id, "worker", reply._bucket(stale, "worker"), stale)
        self.assertEqual(reply.actor_focus_proof(run_id, "another-worker"), other_proof)
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "worker"}):
            moved = tools.compile_tool("T", run_id, {"splice": {"steps": "s1", "text": "exact"}})
        self.assertTrue(moved["ok"])
        moved_proof = tools._node(run_id, moved["items"][0]["node"]).proof_id
        edge = next(
            event
            for event in campaign.events(self.directory)
            if event.get("kind") == "edge" and event.get("proof_id") == moved_proof
        )
        self.assertIn(parent_proof, edge.get("from") or [])
        self.assertNotIn(other_proof, edge.get("from") or [])

        plain = tools.compile_tool("T", run_id, {"drafts": ["by\n  native_decide"]})
        self.assertTrue(plain["ok"])
        shared = tools.compile_tool("T", run_id, {"drafts": ["by\n  decide"], "note": "hyp:shared"})
        again_note = tools.compile_tool("T", run_id, {"drafts": ["by\n  omega"], "note": "hyp:shared"})
        self.assertTrue(shared["ok"] and again_note["ok"])
        refs = [
            event.get("hypothesis_ref")
            for event in campaign.events(self.directory)
            if event.get("kind") == "candidate" and event.get("hypothesis_ref")
        ]
        self.assertGreaterEqual(refs.count("hyp:shared"), 2)
        self.assertTrue(campaign.write_strategy(run_id, "first")["ok"])
        self.assertTrue(campaign.write_strategy(run_id, "second")["ok"])
        self.assertEqual(campaign.current_strategy(campaign.events(self.directory)), "second")
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "worker"}):
            denied = campaign.write_strategy(run_id, "nope")
            campaign.write_observation(run_id, "seen", hypothesis_ref="hyp:shared")
            campaign.write_observation(run_id, "again", hypothesis_ref="hyp:shared")
        self.assertEqual(denied["category"], "invalid_input")
        observations = [event for event in campaign.events(self.directory) if event.get("kind") == "observation"]
        self.assertEqual([event["actor_id"] for event in observations], ["worker", "worker"])
        self.assertEqual(campaign.current_strategy(campaign.events(self.directory)), "second")

        proof_id = parent_proof
        campaign._append(
            self.directory,
            {
                "kind": "evaluation",
                "candidate_id": proof_id,
                "key": "background-notification",
                "mode": "fast",
                "trigger": "auto",
                "result": {
                    "compat": {"v1": {"passed": True}, "v2": {"passed": True}},
                    "metrics": {"proxy": 1},
                },
            },
        )
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol"}):
            sol_reply = reply.attach_context(run_id, reply.reply())
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "worker"}):
            worker_reply = reply.attach_context(run_id, reply.reply())
        self.assertTrue(sol_reply["facts"])
        self.assertEqual(sol_reply["facts"], worker_reply["facts"])
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol"}):
            again = reply.attach_context(run_id, reply.reply())
            repeated = reply.redeliver(run_id)
        self.assertFalse(again["facts"])
        self.assertTrue(repeated["event_ids"])
        replies = [event for event in campaign.events(self.directory) if event.get("kind") == "delivered_reply"]
        self.assertEqual(sum(1 for event in replies if event.get("actor_id") == "sol"), 1)

        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "recovering-worker"}):
            with (
                patch.object(reply, "_save", side_effect=RuntimeError("cache write interrupted")),
                self.assertRaisesRegex(RuntimeError, "cache write interrupted"),
            ):
                reply.attach_context(run_id, reply.reply())
            recovered = reply.redeliver(run_id)
            self.assertTrue(recovered["event_ids"])
            self.assertEqual(recovered["receipt"]["status"], "committed")
            self.assertFalse(reply.attach_context(run_id, reply.reply())["facts"])

        child_id = "harness-child"
        (self.directory / "proofs" / f"{child_id}.lean").write_text("by\n  exact\n")
        campaign._append(
            self.directory,
            {
                "kind": "candidate",
                "candidate_id": child_id,
                "parents": [parent_proof],
                "origin": "assembly",
                "hypothesis": "",
            },
        )
        campaign.select_proof(run_id, parent_proof)
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), child_id), "ineligible")
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), parent_proof), "eligible")
        campaign.select_proof(run_id, child_id)
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), child_id), "eligible")
        detail = next(node for node in campaign.graph_state(run_id)["nodes"] if node["id"] == child_id)
        self.assertEqual(detail["eligibility"], "eligible")
        self.assertIn("verification", detail)
        self.assertIn("cold", detail)

        harness_proof = campaign.normalize_draft("T", "by\n  exact True.intro")
        evaluated = campaign.record_evaluation("T", run_id, harness_proof, "fast", origin="assembly")
        harness_id = evaluated["candidate_id"]
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), harness_id), "ineligible")
        with patch.dict(os.environ, {"ARENA_ACTOR_ID": "worker"}):
            adopted = tools.compile_tool("T", run_id, {"drafts": [harness_proof]})
        self.assertEqual(adopted["items"][0]["eligibility"], "eligible")
        self.assertEqual(campaign.proof_eligibility(campaign.events(self.directory), harness_id), "eligible")


class SessionPathProtocolTests(CascadeCase):
    """Real Lean results carry `compat[v]["lean"]`; the model view turns it into a string."""

    lean_info: ClassVar[dict | None] = {"path": "session", "seconds": 0.1, "engine": "lsp"}

    def call(self, request: dict) -> dict:
        request_file = Path(self.temporary.name) / "request.json"
        request_file.write_text(json.dumps(request))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            execute(ProtocolOptions(action="compile", theorem="T", run_id="logic", request_file=request_file))
        return json.loads(output.getvalue().strip().splitlines()[-1])

    def test_every_form_after_a_model_node_files_a_node(self):
        base = self.call({"drafts": ["by\n  trivial"]})["items"][0]["node"]
        sketch = self.call({"drafts": ["by\n  sorry"]})["items"][0]["node"]
        requests = {
            "drafts on base": {"base": base, "drafts": ["by\n  bad"]},
            "drafts": {"drafts": ["by\n  bad\n  trivial"]},
            "splice": {"splice": {"base": base, "steps": "s1", "text": "bad"}},
            "fill": {"fill": {"hole": f"{sketch}.h1", "text": "bad\n  bad"}},
            "merge": {"merge": {"base": sketch, "take": [{"from": base, "step": "s1"}]}},
        }
        for form, request in requests.items():
            with self.subTest(form=form):
                result = self.call(request)
                self.assertTrue(result["ok"], result)
                item = result["items"][0]
                self.assertIsNone(item["error"], item)
                self.assertTrue(item["node"].startswith("n"))
        self.assertFalse((campaign.run_dir("logic") / "tool-errors.log").exists())

    def test_internal_error_traceback_goes_to_the_run_directory_only(self):
        with patch.object(tools, "compile_tool", side_effect=AttributeError("boom")):
            result = self.call({"drafts": ["by\n  trivial"]})
        self.assertEqual(result["error"]["code"], "internal_error")
        self.assertNotIn("Traceback", json.dumps(result))
        log = (campaign.run_dir("logic") / "tool-errors.log").read_text()
        self.assertIn("Traceback", log)
        self.assertIn("AttributeError: boom", log)


class MissingGoalTests(NoGoalCase):
    def test_error_without_goal_is_still_a_valid_item(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad"]})
        self.assertTrue(result["items"][0]["ok"])
        self.assertIsNone(result["items"][0]["errors"][0]["goal"])


RECORDED_LINE = "  induction h₁ generalizing a₂ <;> cases h₂ <;> grind"
RECORDED_MESSAGE = (
    "`grind` failed\ncase grind\na a₁ a_1 : SKI\nh : ¬Join ParallelReduction a_1 a_1\n⊢ False\n"
    "[grind] Goal diagnostics\n  [facts] Asserted facts\n    [prop] ¬Join ParallelReduction a_1 a_1"
)


class BranchErrorTests(CascadeCase):
    """A diagnostic recorded from v7solo-ski2: `grind` failing in several branches after `<;>`."""

    def recorded_errors(self, count):
        return [
            {
                "id": f"n2.e{index}",
                "line": 3,
                "column": 48,
                "message": RECORDED_MESSAGE.replace("a_1 a_1", f"a_{index} a_{index}"),
                "source_line_text": RECORDED_LINE,
                "goal": "⊢ Join ParallelReduction a₁ a₂",
            }
            for index in range(1, count + 1)
        ]

    def test_goal_is_the_one_lean_reports_at_the_failing_branch(self):
        self.assertEqual(
            tools.message_goal(RECORDED_MESSAGE),
            "case grind\na a₁ a_1 : SKI\nh : ¬Join ParallelReduction a_1 a_1\n⊢ False",
        )
        self.assertIsNone(tools.message_goal("unknown identifier 'x'"))

    def test_compile_item_shows_branch_count_and_first_branch_goal(self):
        tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})
        node = tools._nodes("logic")[1].nodes[-1]
        errors = self.recorded_errors(3)
        for item in errors:
            item["goal"] = tools.message_goal(item["message"])
        with patch.object(tools, "all_errors", return_value=(errors, False)):
            shown = tools._compile_item("T", "logic", node.id, {"compat": {}}, "filed")["item"]["lines"]
        text = "\n".join(shown)
        self.assertIn("3 branches failed", text)
        self.assertIn("case grind", text)
        self.assertNotIn("⊢ Join ParallelReduction a₁ a₂", text)
        self.assertEqual(text.count("`grind` failed"), 1)


class CompileWaitTests(FakeRunCase):
    cascade_errors = True

    def test_in_call_wait_full_checks_closed_node_without_salvaging(self):
        with (
            patch.object(campaign, "problem", return_value=ROW),
            patch.object(campaign, "_probe_workers", return_value=1),
            patch.object(campaign.lean_health, "tripped", return_value=False),
        ):
            with patch.object(campaign, "autocheck", return_value={"checked": []}):
                tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  exact True.intro"]})
            history = campaign.events(self.directory)
            self.assertTrue(campaign._salvage_jobs(history, self.directory, tools._nodes("logic")[1]))
            before = len(history)
            result = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})
        self.assertEqual(result["items"][0]["status"], "closed")
        after = campaign.events(self.directory)[before:]
        self.assertFalse(any(item.get("kind") == "salvage" for item in after))
        self.assertTrue(any(item.get("kind") == "evaluation" and item.get("trigger") == "auto" for item in after))
