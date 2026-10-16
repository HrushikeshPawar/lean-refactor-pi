import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign

FIXTURE = Path(__file__).parent / "fixtures" / "proof_tool_replay.json"


class LeanNameTests(unittest.TestCase):
    def test_accepts_lean_identifiers(self):
        for name in (
            "ι_timeOrderF_superCommuteF_eq_time",
            "Binius.BinaryBasefold.fold_advances_evaluation_poly",
            "foo₀",
            "h'",
            "α.β",
            "«weird name»",
            "A.«b c».d",
            "x!",
            "y?",
            "a_1ᵢ",
            "ℝ.foo",
        ):
            self.assertTrue(campaign._LEAN_NAME.fullmatch(name), name)

    def test_rejects_non_identifiers(self):
        for name in ("a b", "a;b", "", "a..b", ".a", "a.", "1a", "a$(x)", "a`b", "a|b", "a\nb", "«»", "a/b"):
            self.assertFalse(campaign._LEAN_NAME.fullmatch(name), repr(name))


class SourceHandleTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "name": "Target",
            "source": "strata",
            "file_path": "Strata/Target.lean",
            "version_info": [{"4.29.1": "abc123"}],
        }
        self.problem = patch("arena.campaign.problem", return_value=self.row)
        self.versions = patch("arena.campaign.versions", return_value=[("4.29.1", "abc123")])
        self.workspace = patch("arena.campaign.workspace", return_value=Path("project"))
        self.contents = patch("arena.campaign._git_source", return_value="line one\nline two\n")
        for mock in (self.problem, self.versions, self.workspace, self.contents):
            mock.start()
            self.addCleanup(mock.stop)

    def test_source_accepts_decl_handle_and_reports_canonical_file_metadata(self):
        located = {
            "root": Path("project"),
            "pin": "abc123",
            "path": "Strata/Target.lean",
            "line": 2,
            "end": 2,
            "qualified": "Target.helper",
            "file_lines": 2,
        }
        with (
            patch("arena.campaign._resolve_declaration_source", return_value=located),
            patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)),
        ):
            result = campaign.source_range("Target", "decl:Target.helper", 1, 2)
        self.assertEqual(result["path"], "Strata/Target.lean")
        self.assertEqual(result["pin"], "abc123")
        self.assertEqual(result["file_lines"], 2)
        self.assertEqual(result["text"], "1: line one\n2: line two")

    def test_source_accepts_line_suffixes_and_the_printed_handle_form(self):
        target = (Path("project"), "abc123", "Strata/Target.lean")
        with (
            patch("arena.campaign._git_source", return_value="".join(f"l{i}\n" for i in range(1, 11))),
            patch("arena.campaign._source_target", return_value=target) as resolved,
        ):
            for handle, bounds in [
                ("strata:Strata/Target.lean:3", (3, 10)),
                ("Strata/Target.lean:3-5", (3, 5)),
                ("strata@abc123:Strata/Target.lean:4-6", (4, 6)),
                ("strata@abc:Strata/Target.lean:2-3", (2, 3)),
            ]:
                result = campaign.source_range("Target", handle)
                self.assertEqual((result["first"], result["last"]), bounds, handle)
                self.assertEqual(resolved.call_args.args[2], "Strata/Target.lean")
            explicit = campaign.source_range("Target", "Strata/Target.lean:3-5", 1, 2)
            self.assertEqual((explicit["first"], explicit["last"]), (1, 2))
        with self.assertRaises(ValueError):
            campaign.source_range("Target", "strata@def456:Strata/Target.lean:1-2")
        for bad in ("/etc/x.lean:1", "../x.lean:1", "Strata/x.txt:1"):
            with self.assertRaises(ValueError):
                campaign.source_range("Target", bad)

    def test_decl_handle_without_first_starts_at_the_declaration(self):
        located = {
            "root": Path("project"),
            "pin": "abc123",
            "path": "Strata/Target.lean",
            "line": 2,
            "end": 2,
            "qualified": "Target.helper",
            "file_lines": 2,
        }
        with (
            patch("arena.campaign._resolve_declaration_source", return_value=located),
            patch("arena.campaign._source_hint", side_effect=lambda name, symbol: (symbol, None, None)),
        ):
            result = campaign.source_range("Target", "decl:Target.helper")
        self.assertEqual((result["first"], result["text"]), (2, "2: line two"))

    def test_bad_source_range_reports_bounds(self):
        with (
            patch("arena.campaign._source_target", return_value=(Path("project"), "abc123", "Strata/Target.lean")),
            self.assertRaisesRegex(ValueError, "2 lines; first=3 is out of range"),
        ):
            campaign.source_range("Target", "Strata/Target.lean", 3)

    def test_dependency_path_alias_resolves_to_dependency_pin(self):
        self.assertEqual(campaign._canonical_source_path(self.row, "mathlib:Mathlib/Basic.lean"), "Mathlib/Basic.lean")
        self.assertEqual(campaign._canonical_source_path(self.row, "strata/Strata/Target.lean"), "Strata/Target.lean")
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            dependency = Path(directory) / "mathlib"
            project.mkdir()
            (dependency / "Mathlib").mkdir(parents=True)
            (dependency / "Mathlib" / "Basic.lean").write_text("theorem x : True := by trivial\n")
            with patch("arena.campaign._package_roots", return_value=[(dependency, "dep123", "mathlib")]):
                source_project, pin, path = campaign._source_target(project, "main123", "Mathlib/Basic.lean")
        self.assertEqual((source_project, pin, path), (dependency, "dep123", "Mathlib/Basic.lean"))


class PinnedPathAliasTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())

    def test_legacy_path_aliases_replay_with_exact_pinned_line_ranges(self):
        calls = [call for call in self.fixture["calls"] if call["replay"] == "resolve_pinned_path_alias"]
        self.assertEqual(len(calls), 6)
        for call in calls:
            with self.subTest(run=call["run"], request=call["request"]):
                request = call["request"]
                first, last = request["first"], request["last"]
                result = campaign.source_range(call["theorem"], request["handle"], first, last)
                self.assertEqual(result["first"], first)
                self.assertEqual(result["last"], last)
                self.assertNotIn("strata:", result["path"])
                self.assertEqual(len(result["text"].splitlines()), last - first + 1)


if __name__ == "__main__":
    unittest.main()
