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


RESULT = "## Result"


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


class ScratchResultTests(ToolCase):
    def scratch(self, code, output="", measured=None):
        built = {"path": "p", "text": "", "head": 0, "start_line": 1, "end_line": 1, "offset": 0}
        with (
            patch.object(tools.engine, "versions", return_value=[("v", "c")]),
            patch("arena.scoring.reference", return_value=(1000, 10000)),
            patch.object(tools.engine, "candidate_file", return_value=built),
            patch.object(tools.engine, "run_lean", return_value=None if output is None else (0, output)),
            patch.object(tools, "_history", return_value=[]),
            patch.object(campaign, "run_dir", return_value=self.directory),
        ):
            result = tools.scratch_tool("T", "logic", {"code": code})
        return (result.get("details") or result)["items"][0]["lines"]

    def test_scratch_retains_exact_original_code_for_success_failure_and_timeout(self):
        code = "-- original λ context\r\n#check Nat.add_comm\r\n  \r\n"
        shift = tools._SNIPPET_PREFIX.count("\n")
        for output in ("", f"f.lean:{shift + 1}:0: error: fixture failure\n", None):
            with self.subTest(output=output):
                self.scratch(code, output=output)
                saved = [row for row in campaign.events(self.directory) if row["kind"] == "scratch"][-1]
                self.assertEqual(saved["code"], code)
                self.assertEqual(saved["code_sha256"], hashlib.sha256(code.encode()).hexdigest())

    def test_scratch_retains_code_when_context_construction_fails(self):
        code = "#check Nat.add_comm\n"
        with (
            patch.object(tools.engine, "versions", return_value=[("v", "c")]),
            patch.object(tools.engine, "candidate_file", side_effect=RuntimeError("fixture context unavailable")),
            self.assertRaisesRegex(RuntimeError, "fixture context unavailable"),
        ):
            tools.scratch_tool("T", "logic", {"code": code})
        saved = [row for row in campaign.events(self.directory) if row["kind"] == "scratch"][-1]
        self.assertEqual(saved["code"], code)

    def test_v8_scratch_failure_is_retrievable(self):
        code = "-- original λ\r\n#check Nat.add_comm\r\n"
        lean = patch.object(tools.engine, "run_lean", side_effect=AssertionError("lean must not run"))
        with (
            patch.object(tools.engine, "versions", return_value=[("v", "c")]),
            patch.object(tools.engine, "candidate_file", side_effect=RuntimeError("fixture context unavailable")),
            lean,
            self.assertRaisesRegex(RuntimeError, "fixture context unavailable"),
        ):
            tools.scratch_tool("T", "logic", {"code": code})
        saved = [row for row in campaign.events(self.directory) if row.get("experiment_id")][0]
        with lean:
            found = tools.read_tool("T", "logic", {"experiment": saved["experiment_id"]})
        item = found["items"][0]
        self.assertEqual(item["code"], code)
        self.assertEqual(item["outcome"], "construction_error")
        self.assertIn("fixture context unavailable", "\n".join(item["lines"]))
        self.assertNotEqual(item.get("validity"), "passed")
        legacy = tools.read_tool("T", "logic", {"experiment": "a" * 64})
        campaign._append(self.directory, {"kind": "scratch", "code_sha256": "b" * 64})
        missing = tools.read_tool("T", "logic", {"experiment": "b" * 64})
        self.assertEqual(missing["items"][0]["code_status"], "missing")
        self.assertIsNone(missing["items"][0]["code"])
        self.assertIn("missing code", "\n".join(missing["items"][0]["lines"]))
        self.assertFalse(legacy["ok"])

    def test_result_line_counts_messages_and_body_tokens_only_when_the_snippet_declares(self):
        check = self.scratch("#check Nat.add_comm\n")
        proof = self.scratch("example : 1 = 1 := trivial\n")
        self.assertEqual(check[0], "OK: errors 0, warnings 0")
        self.assertRegex(proof[0], r"^OK: errors 0, warnings 0, body tokens 1 ")
        self.assertFalse([line for line in proof if line.startswith("line 1 tokens")])

    def test_info_outputs_are_a_table_with_their_source_lines_and_warnings_are_deduplicated(self):
        # Lean prints each info command's text after an ARENA_MARK line naming the snippet line.
        shift = tools._SNIPPET_PREFIX.count("\n") + tools._MEASURE_DEFINITION.count("\n")
        output = (
            "ARENA_MARK 2\nNat.add_comm (n m : ℕ) : n + m = m + n\n"
            f"f.lean:{shift + 1}:0: warning: `X` has been deprecated\u0335: use Y\nNote: a long note\n"
            f"f.lean:{shift + 3}:0: warning: `X` has been deprecated\u0335: use Y\n"
        )
        lines = self.scratch("example : True := trivial\n#check Nat.add_comm\nexample : True := trivial\n", output)
        self.assertIn("| 2 | `#check Nat.add_comm` | Nat.add_comm (n m : ℕ) : n + m = m + n |", lines)
        warnings = [line for line in lines if "warning:" in line]
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("Note", "\n".join(lines))
        self.assertNotIn("\u0335", "\n".join(lines))
        self.assertTrue(warnings[0].endswith("(also lines 3)"))
        self.assertFalse([line for line in lines if "line ?" in line])


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
        # The failure is in the snippet's own verdict line, not repeated as a second error line.
        self.assertIsNone(result["items"][2]["error"])
        self.assertRegex(result["items"][2]["lines"][0], r"^t2 error")
        self.assertEqual(result["items"][1].get("status", "closed"), "closed")

    def test_goal_at_error_line_is_blocked_until_error_is_replaced(self):
        node = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  bad"]})["items"][0]["node"]
        with patch(
            "arena.tools._node_result",
            return_value={
                "compat": {"v1": {"diagnostics": [{"severity": "error", "proof_line": 2, "message": "bad"}]}}
            },
        ):
            result = tools.goal_tool("T", "logic", {"node": node, "line": 3})
        self.assertEqual(result["items"][0]["error"]["code"], "goal_blocked")

    def test_goal_try_at_the_failing_line_runs_in_place_of_that_line(self):
        node = tools.compile_tool("T", "logic", {"drafts": ["by\n  bad\n  bad"]})["items"][0]["node"]
        failing = {"compat": {"v1": {"diagnostics": [{"severity": "error", "proof_line": 2, "message": "bad"}]}}}
        with (
            patch("arena.tools._node_result", return_value=failing),
            patch(
                "arena.tools.engine.candidate_file",
                return_value={
                    "path": "T.lean",
                    "text": "theorem t : True := by\n  bad\n  bad",
                    "head": 0,
                    "start_line": 1,
                },
            ),
            patch("arena.tools.engine.lean_goals", return_value={"goals": ["⊢ True"], "rendered": "⊢ True"}),
            patch(
                "arena.tools.engine.lean_try", return_value={"results": [{"returncode": 0, "goals_after": None}]}
            ) as lean_try,
        ):
            result = tools.goal_tool("T", "logic", {"node": node, "line": 2, "try": ["trivial"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"][1]["ref"], "t1")
        self.assertEqual(lean_try.call_args.args[4]["line"], 1)
        with patch("arena.tools._node_result", return_value=failing):
            blocked = tools.goal_tool("T", "logic", {"node": node, "line": 3})
        error = blocked["items"][0]["error"]
        self.assertEqual(error["code"], "goal_blocked")
        self.assertIn("error at line 2", error["input"])
        self.assertEqual(error["valid"], ["a line up to 2"])

    def test_search_hit_without_a_line_omits_the_line_part(self):
        hits = [
            {"handle": "decl:A.f", "signature": "A.f : Nat", "module": "(this file)", "line": None, "why": "name"},
            {"handle": "decl:A.g", "signature": "A.g : Nat", "module": "Init", "line": 7, "why": "name"},
        ]
        with patch(
            "arena.tools.search.search", return_value={"kind": "name", "queries": [{"query": "A", "hits": hits}]}
        ):
            result = tools.search_tool("T", "logic", {"queries": ["A"]})
        shown = "\n".join(line for item in result["items"] for line in item["lines"])
        self.assertIn("| A.f | Nat | (this file) | name |", shown)
        self.assertIn("| A.g | Nat | Init:7 | name |", shown)
        self.assertNotIn("None", shown)

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

    def test_search_event_keeps_only_name_handle_module_and_signature_per_hit(self):
        hit = {
            "name": "Nat.add_comm",
            "handle": "decl:Nat.add_comm",
            "signature": "Nat.add_comm : ∀ (n m : ℕ), n + m = m + n",
            "module": "Init.Data.Nat.Basic",
            "line": 7,
            "why": "exact",
            "score": 0.9,
            "tokens": 3,
        }
        miss = {"query": "Nat.zz", "hits": [], "suggestions": ["Nat.zero"]}
        with patch(
            "arena.tools.search.search",
            return_value={"queries": [{"query": "Nat.add", "hits": [hit, {**hit, "name": "Nat.mul_comm"}]}, miss]},
        ):
            tools.search_tool("T", "logic", {"queries": ["Nat.add", "Nat.zz"]})
        events = [event for event in campaign.events(self.directory) if event.get("kind") == "search"]
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["hits"],
            [
                {key: hit[key] for key in ("name", "handle", "module", "signature")},
                {**{key: hit[key] for key in ("handle", "module", "signature")}, "name": "Nat.mul_comm"},
            ],
        )

    def test_search_miss_renders_suggestions(self):
        with patch(
            "arena.tools.search.search",
            return_value={"queries": [{"query": "Nat.ad", "hits": [], "suggestions": ["Nat.add", "Nat.sub"]}]},
        ):
            result = tools.search_tool("T", "logic", {"queries": ["Nat.ad"]})
        self.assertIn("Nat.add, Nat.sub", result["items"][0]["lines"][-1])

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

    def test_prices_of_an_unmeasured_node_say_n_a_not_none(self):
        node = self.sketch()
        total = {"tokens": 290, "heartbeats": None, "versions": "0/3"}
        with patch.object(campaign, "price_table", return_value={"total": total}):
            result = tools.read_tool("T", "logic", {"node": node, "view": "prices"})
        line = result["items"][0]["lines"][1]  # [0] is the result section header
        self.assertIn("heartbeats n/a", line)
        self.assertNotIn("None", line)

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


class ToolReplyTextTests(CascadeToolCase):
    def goal_with_tries(self, results: list[dict], request: dict) -> dict:
        with (
            patch(
                "arena.tools.engine.candidate_file",
                return_value={"path": "T.lean", "text": "theorem t : True := by\n  sorry", "head": 0, "start_line": 1},
            ),
            patch("arena.tools.engine.lean_goals", return_value={"goals": ["⊢ True"], "rendered": "⊢ True"}),
            patch("arena.tools.engine.lean_try", return_value={"results": results}),
        ):
            return tools.goal_tool("T", "logic", request)

    def test_goal_try_reports_each_snippet_verdict_and_tokens_only(self):
        node = self.sketch()
        result = self.goal_with_tries(
            [
                {"returncode": 0, "goals_after": None},
                {"returncode": 0, "goals_after": "case a\n⊢ True\n\ncase b\nh : True\n⊢ True"},
                {"returncode": 1, "output": "T.lean:2:2: error: unknown tactic\n  near x\nT.lean:3:2: error: later"},
                {"timeout": True},
            ],
            {"hole": f"{node}.h1", "try": ["trivial", "constructor", "bogus x", "skip"]},
        )
        lines = [line for item in result["items"][1:] for line in item["lines"]]
        verdicts = [line for line in lines if line.startswith("t")]
        self.assertEqual(
            [line.split(", tokens")[0] for line in verdicts],
            ["t1 compiles", "t2 open goals 2", "t3 error: unknown tactic near x", "t4 timed out"],
        )
        self.assertTrue(all(", tokens " in line for line in verdicts))
        # An open snippet shows the goals it leaves, with each case's hypothesis names.
        self.assertIn("case b: h", "\n".join(lines))
        self.assertNotRegex("\n".join(lines), r"delta|n/a|heartbeats|None")

    def test_goal_try_without_line_or_hole_names_both(self):
        node = self.sketch()
        result = tools.goal_tool("T", "logic", {"node": node, "try": ["trivial"]})
        self.assertEqual(result["error"]["code"], "missing_position")
        self.assertIn("line or hole", result["error"]["input"])
        self.assertNotEqual(result["error"]["input"], "None")

    def test_compile_token_check_shows_each_draft_count(self):
        with patch("arena.tools.engine._proof_length", side_effect=lambda proof, _statement=None: len(proof.split())):
            result = tools.compile_tool("T", "logic", {"check": "tokens", "drafts": ["by\n  exact x", "by\n  trivial"]})
        lines = [line for item in result["items"] for line in item["lines"]]
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^d1 tokens \d+; n1 has \d+\.$")

    def test_read_of_the_own_theorem_shows_the_reference_node(self):
        with patch("arena.tools.search.resolve_handle", return_value=None) as resolve:
            result = tools.read_tool("T", "logic", {"handle": "decl:T:3-9"})
        resolve.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"][0]["ref"], "n1")
        self.assertIn("node n1", result["facts"][0])

    def test_read_of_an_indexed_handle_without_source_is_unknown_with_hints(self):
        missing = ValueError("X.y is not a declaration of the pinned project.")
        with (
            patch("arena.tools.search.resolve_handle", return_value={"line": 1}),
            patch.object(campaign, "source_range", side_effect=missing),
        ):
            result = tools.read_tool("T", "logic", {"handle": "decl:X.y"})
        self.assertEqual(result["error"]["code"], "unknown_handle")
        self.assertEqual(result["error"]["input"], "X.y is not a declaration of the pinned project")
        self.assertTrue(result["error"]["valid"])

    def test_outline_is_a_step_table_and_a_requested_step_shows_its_goals(self):
        node = tools.compile_tool("T", "logic", {"drafts": ["by\n  skip\n  trivial"]})["items"][0]["node"]
        bare = tools.read_tool("T", "logic", {"node": node, "view": "outline"})["items"][0]["lines"]
        self.assertEqual(bare[0], RESULT)
        self.assertTrue(bare[1].startswith("| step |"))
        self.assertRegex(bare[2], r"^\| s1 \| 2-2 \| \S+ \| - \| - \| `skip` \|$")  # unmeasured: no heartbeats, no pts
        proof_id = campaign.resolve_node_ref(campaign.events(self.directory), node)
        hypotheses = "a : ℕ\nb : ℕ\n"
        goals = [
            {"id": "s1", "before": hypotheses + "⊢ True", "after": hypotheses + "c : ℕ\n⊢ True"},
            {"id": "s2", "before": "⊢ True", "after": None},
        ]
        campaign._append(self.directory, {"kind": "step_goals", "proof_id": proof_id, "goals": goals})
        again = tools.read_tool("T", "logic", {"node": node, "view": "outline"})["items"][0]["lines"]
        self.assertNotIn("⊢ True", "\n".join(again))  # goals only for a requested step
        shown = tools.read_tool("T", "logic", {"node": node, "view": "outline", "step": "s1"})["items"][0]["lines"]
        self.assertEqual(
            shown,
            [
                RESULT,
                "s1 lines 2-2",
                "before: a : ℕ\nb : ℕ\n⊢ True",
                "after: (2 unchanged hypotheses omitted)\nc : ℕ\n⊢ True",
            ],
        )
        missing = tools.read_tool("T", "logic", {"node": node, "view": "outline", "step": "s9"})
        self.assertEqual(missing["error"]["code"], "unknown_step")


class ReadHandleForgivingTests(CascadeToolCase):
    def test_decl_handle_with_a_literal_first_last_suffix_reads_the_whole_declaration(self):
        with (
            patch("arena.tools.search.resolve_handle", return_value={"line": 1, "end_line": 2}),
            patch.object(
                campaign,
                "source_range",
                return_value={"source": "p", "first": 1, "last": 2, "text": "1: x", "next_first": None},
            ),
        ):
            result = tools.read_tool(
                "T", "logic", {"handle": "decl:Binius.BinaryBasefold.fold_advances_evaluation_poly:first-last"}
            )
        self.assertNotEqual((result.get("error") or {}).get("code"), "bad_handle")
        self.assertTrue(result["ok"])

    def test_file_handle_with_a_source_prefix_reads_the_range_like_the_plain_path(self):
        source = {"source": "p", "first": 1000, "last": 1080, "text": "1000: x", "next_first": None}
        with patch.object(campaign, "source_range", return_value=source) as read:
            result = tools.read_tool(
                "T", "logic", {"handle": "arklib:ArkLib/ProofSystem/Binius/BinaryBasefold/Prelude.lean:1000-1080"}
            )
        self.assertNotEqual((result.get("error") or {}).get("code"), "bad_handle")
        self.assertTrue(result["ok"])
        read.assert_called_once_with("T", "ArkLib/ProofSystem/Binius/BinaryBasefold/Prelude.lean", 1000, 1080)

    def test_node_handle_reads_exactly_like_the_node_parameter(self):
        node = self.sketch()
        self.assertRegex(node, r"^n[1-9][0-9]*$")
        by_handle = tools.read_tool("T", "logic", {"handle": f"node:{node}"})
        by_node = tools.read_tool("T", "logic", {"node": node})
        self.assertNotEqual((by_handle.get("error") or {}).get("code"), "bad_handle")
        self.assertEqual(by_handle, by_node)

    def test_hole_handle_reads_exactly_like_the_hole_parameter(self):
        node = self.sketch()
        by_handle = tools.read_tool("T", "logic", {"handle": f"hole:{node}.h1"})
        by_hole = tools.read_tool("T", "logic", {"hole": f"{node}.h1"})
        self.assertNotEqual((by_handle.get("error") or {}).get("code"), "bad_handle")
        self.assertEqual(by_handle, by_hole)
