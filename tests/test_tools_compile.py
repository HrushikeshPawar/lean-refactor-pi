import hashlib
from unittest.mock import patch

from arena import campaign, tools
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
        self.assertTrue(any("filed" in line or "focus" in line for line in closed["lines"]))
        self.assertNotIn("sorry", str(result))
        proof_ids = [event["proof_id"] for event in campaign.events(self.directory) if event.get("kind") == "probe"]
        self.assertEqual(len(set(proof_ids)), 1)
        self.assertEqual(sum(event.get("kind") == "edge" for event in campaign.events(self.directory)), 3)

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

    def test_more_errors_than_pass_limit_are_reported_as_incomplete(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n" + "\n".join(["  bad"] * 5)]})
        self.assertEqual(len(result["items"][0]["errors"]), 4)
        self.assertTrue(any("incomplete" in fact.lower() for fact in result["facts"]))

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


class MissingGoalTests(NoGoalCase):
    def test_error_without_goal_is_still_a_valid_item(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad"]})
        self.assertTrue(result["items"][0]["ok"])
        self.assertIsNone(result["items"][0]["errors"][0]["goal"])
