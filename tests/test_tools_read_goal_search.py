from unittest.mock import patch

from arena import campaign, tools
from tests.graph_support import FakeRunCase

ROW = {
    "name": "T",
    "statement": "theorem t : True",
    "src": "theorem t : True := by\n  trivial",
    "version_info": [{"v1": "a"}],
}


class ToolCase(FakeRunCase):
    def setUp(self):
        super().setUp()
        for target, value in (
            ("problem", ROW),
            ("_probe_workers", 1),
            ("autocheck", {"checked": []}),
        ):
            item = patch.object(campaign, target, return_value=value)
            item.start()
            self.addCleanup(item.stop)


class CascadeToolCase(ToolCase):
    cascade_errors = True

    def sketch(self):
        return tools.compile_tool("T", "logic", {"drafts": ["by\n  sorry"]})["items"][0]["node"]


class ReadGoalSearchTests(CascadeToolCase):
    def test_goal_try_keeps_a_bad_snippet_separate_from_a_good_one(self):
        node = self.sketch()
        with (
            patch(
                "arena.tools.engine.candidate_file",
                return_value={
                    "path": "T.lean",
                    "text": "theorem t : True := by\n  sorry",
                    "head": 0,
                    "start_line": 1,
                },
            ),
            patch("arena.tools.engine.lean_goals", return_value={"goals": ["⊢ True"], "rendered": "⊢ True"}),
            patch(
                "arena.tools.engine.lean_try",
                return_value={
                    "results": [{"returncode": 0, "goals_after": None}, {"returncode": 1, "output": "error"}]
                },
            ),
        ):
            result = tools.goal_tool("T", "logic", {"hole": f"{node}.h1", "try": ["trivial", "bad"]})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["items"]), 3)
        self.assertTrue(result["items"][1]["ok"])
        self.assertFalse(result["items"][2]["ok"])
        self.assertEqual(result["items"][2]["error"]["code"], "snippet_failed")
        self.assertEqual(result["items"][1].get("status", "closed"), "closed")

    def test_goal_at_error_line_is_blocked_until_error_is_replaced(self):
        node = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  bad"]})["items"][0]["node"]
        with patch(
            "arena.tools._node_result",
            return_value={
                "compat": {"v1": {"diagnostics": [{"severity": "error", "proof_line": 2, "message": "bad"}]}}
            },
        ):
            result = tools.goal_tool("T", "logic", {"node": node, "line": 2})
        self.assertEqual(result["items"][0]["error"]["code"], "goal_blocked")

    def test_goal_try_at_line_targets_the_enclosing_step(self):
        node = self.sketch()
        with (
            patch(
                "arena.tools.engine.candidate_file",
                return_value={
                    "path": "T.lean",
                    "text": "theorem t : True := by\n  sorry",
                    "head": 0,
                    "start_line": 1,
                },
            ),
            patch("arena.tools.engine.lean_goals", return_value={"goals": ["⊢ True"], "rendered": "⊢ True"}),
            patch(
                "arena.tools.engine.lean_try",
                return_value={"results": [{"returncode": 0, "goals_after": None}]},
            ) as lean_try,
        ):
            result = tools.goal_tool("T", "logic", {"node": node, "line": 2, "try": ["trivial"]})
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(lean_try.call_args.args[4], {"line": 1, "end_line": 1, "column": 0, "end_column": 7})

    def test_search_is_per_query_and_does_not_price_hits(self):
        with patch(
            "arena.tools.search.search",
            return_value={
                "kind": "name",
                "queries": [
                    {"query": "", "hits": [], "error": {"code": "empty_query", "input": ""}},
                    {
                        "query": "Nat.add",
                        "hits": [
                            {
                                "handle": "decl:Nat.add_comm",
                                "signature": "Nat.add_comm : _",
                                "module": "Init",
                                "line": 1,
                                "why": "exact",
                            }
                        ],
                    },
                ],
            },
        ):
            result = tools.search_tool("T", "logic", {"queries": ["", "Nat.add"]})
        self.assertTrue(result["ok"])
        self.assertFalse(result["items"][0]["ok"])
        self.assertTrue(result["items"][1]["ok"])
        self.assertNotIn("tokens", result["items"][1])

    def test_search_miss_renders_suggestions(self):
        with patch(
            "arena.tools.search.search",
            return_value={"queries": [{"query": "Nat.ad", "hits": [], "suggestions": ["Nat.add", "Nat.sub"]}]},
        ):
            result = tools.search_tool("T", "logic", {"queries": ["Nat.ad"]})
        self.assertIn("Nat.add, Nat.sub", result["items"][0]["lines"][0])

    def test_decl_read_appends_event_and_invalid_hole_view_lists_source(self):
        with (
            patch("arena.tools.search.resolve_handle", return_value={"line": 1}),
            patch.object(
                campaign,
                "source_range",
                return_value={"source": "p", "first": 1, "last": 2, "text": "1: x\n2: y", "next_first": None},
            ),
        ):
            result = tools.read_tool("T", "logic", {"handle": "decl:Nat.add_comm"})
        self.assertTrue(result["ok"])
        self.assertTrue(any(event.get("kind") == "read" for event in campaign.events(self.directory)))
        sketch = self.sketch()
        invalid = tools.read_tool("T", "logic", {"hole": f"{sketch}.h1", "view": "prices"})
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"]["valid"], ["source"])

    def test_read_map_needs_no_target(self):
        node = self.sketch()
        with patch.object(campaign, "map_view", return_value={"recent": [{"node": node, "status": "open"}]}):
            result = tools.read_tool("T", "logic", {"view": "map"})
            again = tools.read_tool("T", "logic", {"view": "map"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], [])
        self.assertTrue(any(node in line for line in result["map"]))
        self.assertEqual(again["map"], result["map"])
        missing = tools.read_tool("T", "logic", {"view": "source"})
        self.assertEqual(missing["error"]["code"], "bad_target")

    def test_finish_returns_archive_and_stops(self):
        with (
            patch.object(
                campaign,
                "state",
                return_value={
                    "baseline": {"tokens": 100, "heartbeats": 1000},
                    "best": {"tokens": 80, "heartbeats": 500, "versions": {"v1": True}},
                },
            ),
            patch.object(campaign, "map_view", return_value={"archive": [{"letter": "A", "node": "n1", "score": 90}]}),
        ):
            result = tools.finish_tool("T", "logic", {})
        self.assertTrue(result["stop"])
        self.assertTrue(any("Archive:" in fact for fact in result["facts"]))
        self.assertTrue(any("Points left:" in fact for fact in result["facts"]))
