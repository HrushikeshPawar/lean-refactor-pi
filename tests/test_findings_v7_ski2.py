import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, reply, text, tools
from arena import graph as graph_module
from arena.graph import Graph
from tests.test_tools_compile import CascadeCase


def _history(scores: dict[str, tuple[float, bool]]) -> tuple[list[dict], dict[str, str]]:
    """Nodes a, b, ...: (score, passes every version); all checked on two versions."""
    history: list[dict] = [{"kind": "init", "theorem": "T", "versions": [["v1", "a"], ["v2", "b"]]}]
    proofs = {}
    for name, (score, ok) in scores.items():
        proofs[name] = f"theorem t : True := by\n  exact {name}\n"
        compat = {"v1": {"passed": True}, "v2": {"passed": ok}}
        history += [
            {"kind": "candidate", "candidate_id": name, "origin": "model"},
            {
                "kind": "evaluation",
                "candidate_id": name,
                "mode": "full",
                "result": {"compat": compat, "tokens": 5, "heartbeat": 1, "metrics": {"proxy": score}},
            },
            {"kind": "edge", "proof_id": name, "from": []},
            {"kind": "route", "proof_id": name, "route": "r" + name},
        ]
    return history, proofs


class VersionFailureTests(unittest.TestCase):
    def test_a_version_failing_node_is_never_best_nor_compiles_in_the_map(self):
        history, proofs = _history({"a": (60.0, True), "b": (70.0, False)})
        built = Graph.from_history(history, proofs.get)
        failing = next(node for node in built.nodes if node.proof_id == "b")
        self.assertIsNone(failing.score)
        self.assertEqual(graph_module.shown_status(failing), "ineligible")
        view = graph_module.map_view(built)
        self.assertEqual(view["best"]["node"], "n1")
        statuses = {row["node"]: row["status"] for row in view["archive"] + view["recent"]}
        self.assertEqual(statuses["n2"], "ineligible")
        shown = reply.outcome(statuses["n2"])
        self.assertNotIn("compiles", shown)
        self.assertIn("not eligible", shown)

    def test_a_passing_node_keeps_its_score(self):
        history, proofs = _history({"a": (60.0, True)})
        node = Graph.from_history(history, proofs.get).nodes[0]
        self.assertEqual((node.score, graph_module.shown_status(node)), (60.0, "closed"))


class MarkIneligibleTests(unittest.TestCase):
    def test_compile_item_line_never_says_compiles_for_a_failing_version(self):
        history, proofs = _history({"a": (70.0, False)})
        built = Graph.from_history(history, proofs.get)
        item = {"node": "n1", "lines": [f"n1 {reply.outcome('closed')} · filed"]}
        tools._mark_ineligible(item, built)
        self.assertNotIn("compiles", item["lines"][0])
        self.assertEqual(item["status"], "ineligible")


class MapDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patcher = patch.object(campaign, "ROOT", Path(self.temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        campaign.run_dir("m").mkdir(parents=True)

    def view(self, best: str, recent: str = "x") -> dict:
        row = {"node": "n1", "status": "closed", "score": 1, "tokens": 1, "heartbeats": 1, "visits": 1, "letter": "A"}
        return {
            "best": {"node": best, "score": 1},
            "archive": [row],
            "recent": [{"node": recent, "edge": "root", "from": [], "status": "closed", "score": 1}],
            "effort": [],
            "open": [],
        }

    def attach(self, view: dict) -> dict:
        with (
            patch.object(campaign, "state", return_value={"updates": []}),
            patch.object(campaign, "map_view", return_value=view),
        ):
            return reply.attach_context("m", reply.reply(), include_map=True)

    def test_full_map_only_when_it_matters(self):
        first = self.attach(self.view("n1", "n1"))
        self.assertEqual(first["map"][0], text.render("replies/tools.section_map"))
        quiet = self.attach(self.view("n1", "n2"))
        self.assertEqual(quiet["map"], [text.render("replies/tools.map_unchanged")])
        unchanged = self.attach(self.view("n1", "n2"))
        self.assertIsNone(unchanged["map"])
        best = self.attach(self.view("n3", "n3"))
        self.assertEqual(best["map"][0], text.render("replies/tools.section_map"))
        reply.reset_delivered("m")
        again = self.attach(self.view("n3", "n3"))
        self.assertEqual(again["map"][0], text.render("replies/tools.section_map"))


class ErrorGroupTests(unittest.TestCase):
    def test_same_messages_group_and_distinct_ones_stay(self):
        errors = [
            {"id": "e1", "line": 3, "message": "grind failed\nline 3 h✝¹"},
            {"id": "e2", "line": 5, "message": "grind failed\nline 5 h✝²"},
            {"id": "e3", "line": 9, "message": "Case tag 'a' not found"},
            {"id": "e4", "line": 10, "message": "unsolved goals\n⊢ P"},
            {"id": "e5", "line": 11, "message": "unsolved goals\n⊢ Q"},
        ]
        merged = tools._same_message_groups(tools._branch_groups(errors))
        self.assertEqual([(item["id"], same) for item, _, same in merged], [("e1", ["e2"]), ("e3", []), ("e4", []), ("e5", [])])

    def test_hint_diff_keeps_the_new_text(self):
        # Lean draws a suggested edit as a diff: U+0335 strikes removed characters, U+0332 underlines added ones.
        self.assertEqual(tools.error_message("Case tag: par.red_̲K̲S̵"), "Case tag: par.red_K")
        # Strikethrough alone (no added text) is styling, not a diff: keep the characters.
        self.assertEqual(tools.error_message("unknown c̵onstant"), "unknown constant")


class CompileCase(CascadeCase):
    def test_compile_reply_groups_repeated_errors(self):
        result = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  bad"]})
        self.assertTrue(result["ok"])

    def test_top_level_base_is_the_splice_base(self):
        a = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})["items"][0]["node"]
        b = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial\n  trivial"]})["items"][0]["node"]
        result = tools.compile_tool("T", "logic", {"base": b, "splice": {"steps": "s1", "text": "bad"}})
        node = tools._node("logic", result["items"][0]["node"])
        edge = next(
            e for e in reversed(campaign.events(self.directory)) if e.get("kind") == "edge" and e["proof_id"] == node.proof_id
        )
        self.assertEqual(edge["from"], [tools._node("logic", b).proof_id])
        self.assertNotEqual(edge["from"], [tools._node("logic", a).proof_id])
        flat = tools.compile_tool("T", "logic", {"base": b, "steps": "s1", "text": "bad bad"})
        self.assertTrue(flat["ok"])

    def test_conflicting_bases_are_rejected(self):
        a = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})["items"][0]["node"]
        b = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial\n  trivial"]})["items"][0]["node"]
        result = tools.compile_tool("T", "logic", {"base": a, "splice": {"base": b, "steps": "s1", "text": "bad"}})
        self.assertEqual(result["error"]["code"], "base_conflict")
        same = tools.compile_tool("T", "logic", {"base": a, "splice": {"base": a, "steps": "s1", "text": "bad"}})
        self.assertTrue(same["ok"])

    def test_node_is_an_alias_of_base(self):
        a = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial"]})["items"][0]["node"]
        b = tools.compile_tool("T", "logic", {"drafts": ["by\n  trivial\n  trivial"]})["items"][0]["node"]
        self.assertTrue(tools.compile_tool("T", "logic", {"node": a, "steps": "s1", "text": "bad"})["ok"])
        self.assertTrue(tools.compile_tool("T", "logic", {"node": a, "base": a, "steps": "s1", "text": "bad"})["ok"])
        result = tools.compile_tool("T", "logic", {"node": a, "base": b, "steps": "s1", "text": "bad"})
        self.assertEqual(result["error"]["code"], "base_conflict")


if __name__ == "__main__":
    unittest.main()
