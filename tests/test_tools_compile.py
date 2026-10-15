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
