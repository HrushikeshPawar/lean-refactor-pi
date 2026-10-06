import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena.engine import (WRAPPER_LINES, ROOT, candidate_file, declaration_head, evaluate,
                          instrument_sorries, map_measured_line, parse_diagnostics, problem,
                          reconstruct, structure_diagnostics, validate_proof)

NAME = "Core.InitsUpdatesComm"
FIXTURE = (ROOT / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt")
LEAN = unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir() and FIXTURE.exists(),
                           "Strata fixture environment is not provisioned")


class EvaluatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.row = problem("Core.InitsUpdatesComm")

    def test_exact_reference_reconstructs_from_pinned_git(self):
        path, source = reconstruct(self.row, self.row["src"], "v4.29.1",
                                   self.row["version_info"][0]["v4.29.1"])
        self.assertIn(self.row["src"], source)
        self.assertEqual(path.name, "strata-v4.29.1")

    def test_forbidden_and_statement_changes_fail_before_compile(self):
        with self.assertRaisesRegex(ValueError, "FORBIDDEN: sorry"):
            validate_proof(self.row, self.row["statement"] + " := by sorry")
        with self.assertRaisesRegex(ValueError, "STATEMENT_MODIFIED"):
            validate_proof(self.row, "theorem Wrong := by trivial")
        drifted = self.row["statement"].replace("ks' vs' σ₁", "ks vs σ₁", 1) + " := by trivial"
        with self.assertRaisesRegex(ValueError, r"first difference on statement line \d+: expected"):
            validate_proof(self.row, drifted)
        with self.assertRaisesRegex(ValueError, "EXTRA_COMMAND"):
            validate_proof(self.row, self.row["src"] + "\ntheorem Extra : True := by trivial")

    def test_fast_checks_one_version_and_full_checks_all(self):
        with patch("arena.engine.compile_version", return_value={"passed": True, "heartbeats": 4399}) as compile_mock:
            fast = evaluate(self.row["name"], self.row["src"], "fast")
            self.assertEqual(compile_mock.call_count, 1)
            self.assertEqual(fast["tokens"], 224)
            self.assertEqual(fast["heartbeat"], 4399)
            compile_mock.reset_mock()
            full = evaluate(self.row["name"], self.row["src"], "full")
            self.assertEqual(compile_mock.call_count, 3)
            self.assertIsNone(full["score"])
            self.assertEqual(full["local_proxy"], 32.17)


class DiagnosticMappingTests(unittest.TestCase):
    def test_wrapper_shift_is_applied_once_after_insertion_point(self):
        self.assertEqual(WRAPPER_LINES, 14)
        self.assertEqual(map_measured_line(10, 20), (10, False))
        self.assertEqual(map_measured_line(20 + 5, 20), (20, True))
        self.assertEqual(map_measured_line(20 + WRAPPER_LINES, 20), (20, False))
        self.assertEqual(map_measured_line(20 + WRAPPER_LINES + 7, 20), (27, False))

    def test_messages_split_by_header_with_continuation_lines(self):
        output = ("a.lean:5:2: error: unsolved goals\ncase x\n⊢ False\n"
                  "a.lean:9:0: warning: unused variable `h`\n"
                  "a.lean:1:0: info: ARENA_HEARTBEATS 12")
        found = parse_diagnostics(output)
        self.assertEqual([item["severity"] for item in found], ["error", "warning", "info"])
        self.assertIn("⊢ False", found[0]["message"])

    def test_unpositioned_info_lines_are_not_glued_to_the_previous_error(self):
        # Lean's command line prints logInfo output with no position header.
        output = ("a.lean:2:19: error: Type mismatch\n  rfl\nhas type\n  ?m.8 = ?m.8\n"
                  "ARENA_HEARTBEATS 7\nTry this:\n  [apply] simp only")
        found = parse_diagnostics(output)
        self.assertEqual([item["severity"] for item in found], ["error", "info", "info"])
        self.assertNotIn("ARENA_HEARTBEATS", found[0]["message"])
        self.assertNotIn("Try this", found[0]["message"])
        result = structure_diagnostics(output, "x\ny\nz\n", 1, 3)
        self.assertEqual(result["error_headlines"], ["line 2 (proof line 2): Type mismatch"])

    def test_other_toolchains_report_lines_in_the_primary_file(self):
        # The target starts at line 30 in this version's file but at line 10 in
        # the materialized primary file the model inspects.
        text = "\n".join(f"line{i}" for i in range(1, 41)) + "\n"
        result = structure_diagnostics("f.lean:32:2: error: unknown tactic", text, 30, 35,
                                       report_start_line=10)
        item = result["diagnostics"][0]
        self.assertEqual((item["file_line"], item["proof_line"]), (12, 3))
        self.assertEqual(item["source_line_text"], "line32")
        self.assertEqual(result["error_headlines"], ["line 12 (proof line 3): unknown tactic"])

    def test_only_target_span_becomes_headlines_and_text_matches_file(self):
        text = "\n".join(f"line{i}" for i in range(1, 31)) + "\n"
        # Measured file: wrapper inserted before line 10; an error on text line 12
        # is reported at 12 + 14, one on line 3 stays at 3, a warning on line 25 is outside.
        output = (f"f.lean:{12 + WRAPPER_LINES}:4: error: boom\n"
                  "f.lean:3:0: error: earlier trouble\n"
                  f"f.lean:{25 + WRAPPER_LINES}:0: warning: elsewhere\n"
                  "f.lean:10:0: info: ARENA_HEARTBEATS 5")
        result = structure_diagnostics(output, text, 10, 20, wrapper_start=10)
        self.assertEqual(len(result["diagnostics"]), 1)
        item = result["diagnostics"][0]
        self.assertEqual((item["file_line"], item["proof_line"]), (12, 3))
        self.assertEqual(item["source_line_text"], "line12")
        self.assertEqual(result["outside_target"]["errors"], 1)
        self.assertEqual(result["outside_target"]["warnings"], 1)
        self.assertEqual(result["error_headlines"], ["line 12 (proof line 3): boom"])

    def test_wrappers_go_before_a_doc_comment_and_attributes(self):
        # A command inserted between a doc comment and its declaration does not parse
        # ("unexpected token 'open'; expected 'lemma'"), as on the CSLib and PhysLib rows.
        text = "def a := 1\n\n/-- doc -/\n@[simp]\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index("/--"))
        plain = "def a := 1\n\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(plain, plain.index("theorem")), plain.index("theorem"))
        # A binder list ending in `]` and a `@[expose] public section` line are not attributes
        # of the declaration (PhysLib).
        physlib = ("@[expose] public section\n\nvariable {Y} [MeasurableSpace Y]\n\n/-- doc -/\n"
                   "lemma t : True := trivial\n")
        self.assertEqual(declaration_head(physlib, physlib.index("lemma")), physlib.index("/--"))
        module_doc = "/-! module notes -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(module_doc, module_doc.index("theorem")), module_doc.index("theorem"))

    def test_sorry_instrumentation_keeps_line_count(self):
        proof = "theorem t : True := by\n  constructor\n  · sorry\n  sorry\n  exact (by sorry)"
        out = instrument_sorries(proof)
        self.assertEqual(out.count("\n"), proof.count("\n"))
        self.assertEqual(out.count("trace_state; sorry"), 3)

    def test_probe_is_the_only_mode_that_accepts_sorry(self):
        row = problem(NAME)
        draft = row["statement"] + " := by\n  sorry"
        with self.assertRaisesRegex(ValueError, "FORBIDDEN: sorry"):
            validate_proof(row, draft)
        self.assertGreater(validate_proof(row, draft, allow_sorry=True), 0)


@LEAN
class RealLeanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = FIXTURE.read_text()
        cls.broken = cls.good.replace("exact Exists.intro σ'' ⟨InitStatesUpdated Hinit, Hinit, UpdateStates.update_none⟩",
                                      "exact rfl")
        assert cls.broken != cls.good
        cls.run_id = f"test-{uuid.uuid4().hex[:10]}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(campaign.run_dir(cls.run_id), ignore_errors=True)

    def test_fast_estimate_is_labelled_and_full_reproduces_the_proxy(self):
        fast = evaluate(NAME, self.good, "fast")
        self.assertEqual(fast["tokens"], 126)
        self.assertIsNone(fast["local_proxy"])
        self.assertTrue(fast["metrics"]["assumes_full_compat"])
        self.assertNotIn("proxy", fast["metrics"])
        self.assertAlmostEqual(fast["metrics"]["axes"]["tokens"]["contribution"], 14.58)
        full = evaluate(NAME, self.good, "full")
        self.assertEqual(full["local_proxy"], 76.72)
        self.assertEqual(full["metrics"]["proxy"], 76.72)
        self.assertEqual(full["heartbeat"], fast["heartbeat"])
        self.assertEqual(full["metrics"]["deltas"]["vs_reference"]["tokens"], -98)

    def test_reported_lines_match_the_file_lean_goal_reads(self):
        result = evaluate(NAME, self.broken, "fast")
        primary = next(iter(result["compat"].values()))
        self.assertFalse(primary["passed"])
        self.assertTrue(primary["diagnostics"])
        location = campaign.materialize(NAME, self.run_id, self.broken)
        materialized = Path(location["candidate_path"]).read_text().splitlines()
        for item in primary["diagnostics"]:
            self.assertEqual(materialized[item["file_line"] - 1], item["source_line_text"])
            self.assertEqual(item["file_line"], location["start_line"] + item["proof_line"] - 1)
        self.assertEqual(primary["diagnostics"][0]["severity"], "error")
        self.assertIn("rfl", primary["diagnostics"][0]["source_line_text"])

    def test_every_toolchains_lines_match_the_materialized_primary_file(self):
        # The target starts on a different line in each version's file.
        result = evaluate(NAME, self.broken, "full")
        location = campaign.materialize(NAME, self.run_id, self.broken)
        materialized = Path(location["candidate_path"]).read_text().splitlines()
        self.assertEqual(len(result["compat"]), 3)
        for version, outcome in result["compat"].items():
            self.assertTrue(outcome["diagnostics"], version)
            for item in outcome["diagnostics"]:
                self.assertEqual(materialized[item["file_line"] - 1], item["source_line_text"], version)
                self.assertNotIn("ARENA_HEARTBEATS", item["message"])

    def test_materialized_file_is_the_compiled_file_minus_wrapper_and_truncated(self):
        row = problem(NAME)
        version, commit = next(iter(row["version_info"][0].items()))
        built = candidate_file(row, self.good, version, commit)
        self.assertTrue(built["text"].endswith(self.good.rstrip("\n") + "\n"))
        full = reconstruct(row, self.good, version, commit)[1]
        self.assertGreater(len(full), len(built["text"]))

    def test_probe_returns_goals_and_never_scores(self):
        draft = problem(NAME)["statement"] + " := by\n  intros Hup Hinit\n  sorry"
        result = evaluate(NAME, draft, "probe")
        self.assertFalse(result["scored"])
        self.assertIsNone(result["local_proxy"])
        self.assertTrue(result["contains_sorry"])
        self.assertEqual(len(result["goals"]), 1)
        self.assertIn("Hup", result["goals"][0]["goals"])
        self.assertEqual(result["goals"][0]["proof_line"], 11)
        self.assertEqual(result["goals"][0]["file_line"], 950 + 10)
        with self.assertRaisesRegex(ValueError, "FORBIDDEN: sorry"):
            evaluate(NAME, draft, "fast")


if __name__ == "__main__":
    unittest.main()
