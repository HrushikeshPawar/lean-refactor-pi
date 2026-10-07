import subprocess
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
        for mock in (self.problem, self.versions, self.workspace, self.contents):
            mock.start()
            self.addCleanup(mock.stop)

    def test_source_accepts_decl_handle_and_reports_canonical_file_metadata(self):
        located = {"root": Path("project"), "pin": "abc123", "path": "Strata/Target.lean", "line": 2,
                   "end": 2, "qualified": "Target.helper", "file_lines": 2}
        with patch("arena.campaign._resolve_declaration_source", return_value=located), \
             patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)):
            result = campaign.source_range("Target", "decl:Target.helper", 1, 2)
        self.assertEqual(result["path"], "Strata/Target.lean")
        self.assertEqual(result["pin"], "abc123")
        self.assertEqual(result["file_lines"], 2)
        self.assertEqual(result["text"], "1: line one\n2: line two")

    def test_lookups_and_lean_context_read_the_measurement_commit(self):
        from arena import context
        from arena.engine import measure_version

        self.assertIs(campaign.measure_version, measure_version)
        self.assertIs(context.measure_version, measure_version)
        with patch("arena.campaign.measure_version", return_value=("4.30.0", "measure1")), \
             patch("arena.campaign._git_source", return_value="line one\n"), \
             patch("arena.campaign._source_target", return_value=(Path("project"), "measure1", "Strata/Target.lean")):
            campaign.source_range("Target", "Strata/Target.lean", 1)
        campaign.workspace.assert_called_with(self.row, "4.30.0", "measure1")
        campaign.workspace.reset_mock()
        with patch("arena.campaign.measure_version", return_value=("4.30.0", "measure1")), \
             patch("arena.campaign._roots", return_value=[]), \
             patch("arena.campaign._context", return_value={"error": "x"}), \
             patch("arena.campaign._declaration_hits", return_value=[]):
            campaign._find("Target", ["Missing"], 5)
            with self.assertRaises(Exception):
                campaign._resolve_declaration_source("Target", "Missing")
        for call in campaign.workspace.call_args_list:
            self.assertEqual(call.args[1:], ("4.30.0", "measure1"))
        self.assertGreaterEqual(campaign.workspace.call_count, 2)

    def test_decl_handle_without_first_starts_at_the_declaration(self):
        located = {"root": Path("project"), "pin": "abc123", "path": "Strata/Target.lean", "line": 2,
                   "end": 2, "qualified": "Target.helper", "file_lines": 2}
        with patch("arena.campaign._resolve_declaration_source", return_value=located), \
             patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)):
            result = campaign.source_range("Target", "decl:Target.helper")
        self.assertEqual((result["first"], result["text"]), (2, "2: line two"))

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
             patch("arena.campaign.declaration", side_effect=lambda theorem, name:
                   {"found": False} if name == "missing" else
                   {"found": True, "name": "Target.helper", "handle": "decl:Target.helper",
                    "source_text": "theorem helper : True := by trivial"}):
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

    def test_batched_lookup_types_private_and_generated_index_entries(self):
        inventory = {"constant": [
            {"name": "_private.Target.0.secret", "kind": "theorem"},
            {"name": "Target._proof_1", "kind": "theorem", "tag": "generated"},
        ], "local": []}
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.context.constant_index", side_effect=lambda ctx, **kw:
                   [item for item in ctx["constant"] if all(item.get(k) == v for k, v in kw.items() if v is not None)]), \
             patch("arena.campaign.declaration", side_effect=lambda theorem, name:
                   {"found": True, "name": name, "kind": "theorem", "signature": "theorem ..."}):
            result = campaign.declarations("Target", [
                "_private.Target.0.secret", "Target._proof_1"])
        self.assertEqual([item["reason"] for item in result["items"]], ["private", "generated"])

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
        hits = [(0, "abc123", "A.lean", 2, "theorem alpha : True := by trivial"),
                (0, "abc123", "A.lean", 3, "theorem alpine : True := by trivial")]
        with patch("arena.campaign._declaration_hits", return_value=hits), \
             patch("arena.campaign._git_source", return_value=source), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.context.lean_context", return_value={"constant": []}):
            result = campaign.find("Target", ["alp"], limit=1)
        matches = result["queries"][0]["matches"]
        self.assertEqual(result["queries"][0]["distinct_count"], 2)
        self.assertTrue(result["queries"][0]["truncated"])
        self.assertEqual(matches[0]["handle"], "decl:A.alpha")
        self.assertEqual((matches[0]["path"], matches[0]["line"]), ("A.lean", 2))
        self.assertEqual(matches[0]["signature"], "theorem alpha : True := by trivial")
        self.assertNotIn("source_text", matches[0])
        located = {"root": Path("project"), "pin": "abc123", "path": "A.lean", "line": 1, "end": 1,
                   "qualified": "A.alpha", "file_lines": 4}
        with patch("arena.campaign._resolve_declaration_source", return_value=located), \
             patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)), \
             patch("arena.campaign._git_source", return_value=source):
            source_result = campaign.source_range("Target", matches[0]["handle"], 1, 1)
        self.assertEqual(source_result["path"], "A.lean")
        self.assertIn("namespace A", source_result["text"])

    def test_find_reads_indexed_names_without_searching_source_trees(self):
        inventory = {"constant": [{"name": "Lib.Foo.bar", "kind": "theorem", "origin": "elaborated-proof",
                                   "module": "Lib.Foo", "start_line": 2, "end_line": 3, "tag": "helper"}]}
        source = "namespace Lib.Foo\ntheorem bar (x : Nat) :\n    x = x := rfl\nend Lib.Foo\n"
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.campaign._package_roots", return_value=[(Path("lib"), "libpin", "lib")]), \
             patch("arena.campaign._declaration_hits", side_effect=AssertionError("no search expected")), \
             patch("arena.campaign._git_source", side_effect=lambda root, pin, path:
                   source if (str(root), path) == ("lib", "Lib/Foo.lean") else (_ for _ in ()).throw(
                       subprocess.CalledProcessError(128, "git"))):
            result = campaign.find("Target", ["Lib.Foo.bar"])
        match = result["queries"][0]["matches"][0]
        self.assertEqual((match["name"], match["path"], match["line"], match["end_line"], match["pin"]),
                         ("Lib.Foo.bar", "Lib/Foo.lean", 2, 3, "libpin"))
        self.assertEqual(match["signature"], "theorem bar (x : Nat) :\n    x = x := rfl")

    def test_find_reports_misses_with_suggestions_and_scan_truncation(self):
        inventory = {"constant": [{"name": "Lib.Foo.near", "kind": "theorem", "origin": "proof"}]}
        hits = [(0, "abc123", f"F{n}.lean", 1, "theorem zeta : True := trivial") for n in range(campaign.MAX_SCAN_FILES + 5)]
        with patch("arena.context.lean_context", return_value=inventory), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.campaign._declaration_hits", return_value=hits), \
             patch("arena.campaign._git_source", return_value="theorem zeta : True := trivial\n"):
            result = campaign.find("Target", ["Foo.nothing", "zeta"], limit=100)
        miss, found = result["queries"]
        self.assertEqual(miss["error"], "not_found")
        self.assertEqual(miss["suggestions"], ["Lib.Foo.near"])
        self.assertTrue(found["files_truncated"])
        self.assertEqual(found["files_scanned"], campaign.MAX_SCAN_FILES)

    def test_blob_reads_are_cached_within_one_call(self):
        reads = []
        session = campaign._Session()
        with patch.object(campaign._Session, "_fetch", side_effect=lambda root, spec: reads.append(spec) or "x\n"):
            self.assertEqual(session.read(Path("r"), "pin", "A.lean"), "x\n")
            self.assertEqual(session.read(Path("r"), "pin", "A.lean"), "x\n")
        self.assertEqual(reads, ["pin:A.lean"])

    def test_resolution_uses_the_indexed_module_without_searching(self):
        source = "namespace A\ntheorem foo : True := trivial\nend A\n"
        with patch("arena.campaign._declaration_hits", side_effect=AssertionError("no search expected")), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.campaign._git_source", return_value=source):
            located = campaign._resolve_declaration_source("Target", "A.foo", "Lib.A")
        self.assertEqual((located["path"], located["line"]), ("Lib/A.lean", 2))
        with patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.campaign._git_source", side_effect=subprocess.CalledProcessError(128, "git")), \
             self.assertRaisesRegex(ValueError, "Lib.Missing, which is not in the pinned"):
            campaign._resolve_declaration_source("Target", "A.foo", "Lib.Missing")

    def test_unqualified_source_name_matching_several_declarations_is_ambiguous(self):
        source = "namespace A\ntheorem foo : True := trivial\nend A\nnamespace B\ntheorem foo : True := trivial\nend B\n"
        hits = [(0, "abc123", "X.lean", 2, "theorem foo : True := trivial")]
        with patch("arena.campaign._declaration_hits", return_value=hits), \
             patch("arena.campaign._package_roots", return_value=[]), \
             patch("arena.campaign._git_source", return_value=source):
            with self.assertRaises(campaign.AmbiguousDeclaration) as raised:
                campaign._resolve_declaration_source("Target", "foo")
            self.assertEqual(raised.exception.candidates, ["A.foo", "B.foo"])
            # An exact qualified name wins over the other suffix matches.
            located = campaign._resolve_declaration_source("Target", "A.foo")
            self.assertEqual((located["qualified"], located["line"]), ("A.foo", 2))
            with patch("arena.context.lean_context", return_value={"constant": []}), \
                 patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)):
                self.assertEqual(campaign.source_range("Target", "decl:foo", 1)["candidates"], ["A.foo", "B.foo"])
                found = campaign.declaration("Target", "foo")
        self.assertEqual(found["ambiguous"], ["A.foo", "B.foo"])

    def test_declarations_require_exactly_one_of_items_or_cursor(self):
        for kwargs in ({}, {"items": ["a"], "cursor": "abc"}, {"items": []}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "exactly one of items"):
                campaign.declarations("Target", **kwargs)

    def test_source_declaration_scanner_tracks_nested_namespaces(self):
        source = "\n".join((
            "namespace Outer", "namespace Inner", "theorem alpha : True := by trivial",
            "end Inner", "theorem beta : True := by trivial", "end Outer",
            "theorem Outside.gamma : True := by trivial", ""))
        self.assertEqual(campaign._source_declarations(source.splitlines()), [
            (3, "Outer.Inner.alpha"),
            (5, "Outer.beta"),
            (7, "Outside.gamma"),
        ])

    def test_scanner_sections_do_not_close_namespaces(self):
        source = "\n".join((
            "namespace X", "section", "theorem a : True := trivial", "end",
            "section Named", "theorem b : True := trivial", "end Named",
            "noncomputable section", "def c := 1", "end",
            "theorem d : True := trivial", "end X", "theorem e : True := trivial"))
        self.assertEqual(campaign._source_declarations(source.splitlines()), [
            (3, "X.a"), (6, "X.b"), (9, "X.c"), (11, "X.d"), (13, "e")])

    def test_scanner_qualifies_dotted_names_and_honours_root_prefix(self):
        source = "\n".join((
            "namespace X", "theorem Foo.bar : True := trivial",
            "protected theorem baz : True := trivial", "theorem _root_.Top.level : True := trivial",
            "private noncomputable def hidden := 1", "end X", "namespace A.B", "theorem q : True := trivial",
            "end A.B", "theorem after : True := trivial"))
        self.assertEqual(campaign._source_declarations(source.splitlines()), [
            (2, "X.Foo.bar"), (3, "X.baz"), (4, "Top.level"), (5, "X.hidden"), (8, "A.B.q"), (10, "after")])

    def test_declaration_end_stops_before_the_next_declarations_docs_and_attributes(self):
        lines = ["theorem a : True := by", "  trivial", "", "/-- Docs for b. -/", "@[simp]",
                 "theorem b : True := trivial"]
        starts = campaign._source_declarations(lines)
        self.assertEqual(campaign._declaration_end(lines, starts, 0), 2)
        self.assertEqual(campaign._declaration_start(lines, 6), 4)


@unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir()
                     and (ROOT / "workspaces/physlib-v4.32.0").is_dir(),
                     "Strata and PhysLib pinned fixtures are required")
class PinnedFamilyRoundTripTests(unittest.TestCase):
    def test_handles_round_trip_on_strata_and_physlib(self):
        for theorem, symbol in (("Core.InitsUpdatesComm", "Core.InitsUpdatesComm"),
                                ("fundamental_theorem_of_variational_calculus'",
                                 "fundamental_theorem_of_variational_calculus'")):
            with self.subTest(theorem=theorem):
                result = campaign.declarations(theorem, [f"decl:{symbol}"])["items"][0]
                self.assertEqual(result["kind"], "declaration")
                self.assertTrue(result["source_text"].strip())
                source = campaign.source_range(theorem, result["handle"], result["line"], result["line"])
                self.assertEqual(source["path"], result["path"])
                self.assertEqual(source["pin"], result["pin"])
                self.assertEqual(source["first"], result["line"])


if __name__ == "__main__":
    unittest.main()
