import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena.engine import ROOT


class SourceHandleTests(unittest.TestCase):
    def setUp(self):
        self.row = {"name": "Target", "source": "strata", "file_path": "Strata/Target.lean",
                    "version_info": [{"4.29.1": "abc123"}]}
        self.problem = patch("arena.campaign.problem", return_value=self.row)
        self.versions = patch("arena.campaign.versions", return_value=[("4.29.1", "abc123")])
        self.workspace = patch("arena.campaign.workspace", return_value=Path("project"))
        self.contents = patch("arena.campaign._git_source", return_value="line one\nline two\n")
        self.module = patch("arena.campaign._indexed_module", return_value=None)
        for mock in (self.problem, self.versions, self.workspace, self.contents, self.module):
            mock.start()
            self.addCleanup(mock.stop)

    def test_source_accepts_decl_handle_and_reports_canonical_file_metadata(self):
        with patch("arena.campaign._resolve_declaration_source", return_value=("Strata/Target.lean", 2)), \
             patch("arena.campaign._source_target", return_value=(Path("project"), "abc123", "Strata/Target.lean")):
            result = campaign.source_range("Target", "decl:Target.helper", 1, 2)
        self.assertEqual(result["path"], "Strata/Target.lean")
        self.assertEqual(result["pin"], "abc123")
        self.assertEqual(result["file_lines"], 2)
        self.assertEqual(result["text"], "1: line one\n2: line two")

    def test_bad_source_range_reports_bounds(self):
        with patch("arena.campaign._source_target", return_value=(Path("project"), "abc123", "Strata/Target.lean")), \
             self.assertRaisesRegex(ValueError, "2 lines; first=3 is out of range"):
            campaign.source_range("Target", "Strata/Target.lean", 3)

    def test_dependency_path_alias_resolves_to_dependency_pin(self):
        self.assertEqual(campaign._canonical_source_path(self.row, "mathlib:Mathlib/Basic.lean"),
                         "Mathlib/Basic.lean")
        self.assertEqual(campaign._canonical_source_path(self.row, "strata/Strata/Target.lean"),
                         "Strata/Target.lean")
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            dependency = Path(directory) / "mathlib"
            project.mkdir()
            (dependency / "Mathlib").mkdir(parents=True)
            (dependency / "Mathlib" / "Basic.lean").write_text("theorem x : True := by trivial\n")
            with patch("arena.campaign._package_roots", return_value=[(dependency, "dep123", "mathlib")]):
                source_project, pin, path = campaign._source_target(project, "main123", "Mathlib/Basic.lean")
        self.assertEqual((source_project, pin, path), (dependency, "dep123", "Mathlib/Basic.lean"))

    def test_batched_declarations_accept_handles_and_preserve_local_scope(self):
        inventory = {"constant": [{"name": "Target.helper", "kind": "theorem",
                                   "origin": "elaborated-proof", "tag": "helper"}],
                     "local": [{"name": "x", "type": "Nat", "scope": "Target", "proof_line": 4}]}
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.context.constant_index", side_effect=lambda ctx, **kw:
                   [item for item in ctx["constant"] if all(item.get(k) == v for k, v in kw.items() if v is not None)]), \
             patch("arena.campaign.declaration", return_value={"found": True, "name": "Target.helper",
                                                                "handle": "decl:Target.helper", "source_text": "theorem helper : True := by trivial"}):
            result = campaign.declarations("Target", ["decl:Target.helper", "x", "missing"])
        self.assertEqual(result["items"][0]["handle"], "decl:Target.helper")
        self.assertEqual(result["items"][1], {"input": "x", "kind": "local", "name": "x",
                                                "type": "Nat", "scope": "Target"})
        self.assertEqual(result["items"][2]["error"], "not_found")

    def test_long_declaration_batch_returns_a_cursor_without_dropping_items(self):
        inventory = {"constant": [{"name": "Target.first", "kind": "theorem", "origin": "proof"},
                                   {"name": "Target.second", "kind": "theorem", "origin": "proof"}],
                     "local": []}
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.context.constant_index", side_effect=lambda ctx, **kw:
                   [item for item in ctx["constant"] if all(item.get(k) == v for k, v in kw.items() if v is not None)]), \
             patch("arena.campaign.declaration", side_effect=lambda theorem, name:
                   {"found": True, "name": name, "handle": "decl:" + name, "source_text": "x" * 17_000}):
            first = campaign.declarations("Target", ["Target.first", "Target.second"])
            second = campaign.declarations("Target", cursor=first["next_cursor"])
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual([item["name"] for item in first["items"]], ["Target.first"])
        self.assertEqual([item["name"] for item in second["items"]], ["Target.second"])

    def test_unavailable_declaration_reasons_are_typed(self):
        cases = [({"name": "_private.A.foo", "kind": "theorem"}, {}, "private"),
                 ({"name": "A._simp_1", "kind": "theorem", "tag": "generated"}, {}, "generated"),
                 ({"name": "A.opaque", "kind": "opaque"}, {}, "opaque"),
                 ({"name": "Mathlib.A.foo", "kind": "theorem"}, {"module": "Mathlib.A"}, "external"),
                 ({"name": "A.foo", "kind": "theorem"}, {}, "unavailable")]
        for entry, found, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(campaign._unavailable_reason(entry, found), expected)

    def test_unqualified_duplicate_name_is_reported_as_ambiguous(self):
        inventory = {"constant": [{"name": "Target.foo", "kind": "theorem"},
                                   {"name": "Other.foo", "kind": "theorem"}], "local": []}
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.context.constant_index", side_effect=lambda ctx, **kw:
                   [item for item in ctx["constant"] if all(item.get(k) == v for k, v in kw.items() if v is not None)]):
            result = campaign.declarations("Target", ["foo"])
        self.assertEqual(result["items"][0]["kind"], "ambiguous")
        self.assertEqual(result["items"][0]["suggestions"], ["Target.foo", "Other.foo"])

    def test_find_counts_distinct_qualified_names_and_emits_source_handles(self):
        source = "namespace A\ntheorem alpha : True := by trivial\ntheorem alpine : True := by trivial\nend A\n"
        with patch("arena.campaign._matching_pinned_paths", return_value=["A.lean"]), \
             patch("arena.campaign._git_source", return_value=source), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.context.lean_context", return_value={"constant": []}):
            result = campaign.find("Target", ["alp"], limit=1)
        matches = result["queries"][0]["matches"]
        self.assertEqual(result["queries"][0]["distinct_count"], 2)
        self.assertTrue(result["queries"][0]["truncated"])
        self.assertEqual(matches[0]["handle"], "decl:A.alpha")
        with patch("arena.campaign._matching_pinned_paths", return_value=["A.lean"]), \
             patch("arena.campaign._git_source", return_value=source), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.campaign._source_target", side_effect=lambda project, pin, path, module=None:
                   (Path("project"), pin, path)), \
             patch("arena.campaign._indexed_module", return_value=None):
            source_result = campaign.source_range("Target", matches[0]["handle"], 1, 1)
        self.assertEqual(source_result["path"], "A.lean")
        self.assertIn("namespace A", source_result["text"])


@unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir()
                     and (ROOT / "workspaces/physlib-v4.32.0").is_dir(),
                     "Strata and PhysLib pinned fixtures are required")
class PinnedFamilyRoundTripTests(unittest.TestCase):
    def test_handles_round_trip_on_strata_and_physlib(self):
        for theorem, symbol in (("Core.InitsUpdatesComm", "Core.InitsUpdatesComm"),
                                ("fundamental_theorem_of_variational_calculus'",
                                 "fundamental_theorem_of_variational_calculus'")):
            with self.subTest(theorem=theorem):
                result = campaign.declaration(theorem, symbol)
                self.assertTrue(result["source_text"].strip())
                source = campaign.source_range(theorem, result["handle"], result["line"], result["line"])
                self.assertEqual(source["path"], result["path"])
                self.assertEqual(source["pin"], result["pin"])
                self.assertEqual(source["first"], result["line"])


if __name__ == "__main__":
    unittest.main()
