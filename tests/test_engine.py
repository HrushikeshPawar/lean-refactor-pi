import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from arena import campaign, engine
from arena.engine import (
    ROOT,
    WRAPPER_LINES,
    _proof_length,
    declaration_head,
    evaluate,
    instrument_sorries,
    locate_source,
    map_measured_line,
    measure_version,
    parse_diagnostics,
    problem,
    reconstruct,
    structure_diagnostics,
    toolchain_key,
    validate_proof,
)
from tests.slow import slow

NAME = "Core.InitsUpdatesComm"
FIXTURE = ROOT / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"
LEAN = unittest.skipUnless(
    (ROOT / "workspaces/strata-v4.29.1").is_dir() and FIXTURE.exists(), "Strata fixture environment is not provisioned"
)


class EvaluatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.row = problem("Core.InitsUpdatesComm")

    def test_exact_reference_reconstructs_from_pinned_git(self):
        path, source = reconstruct(self.row, self.row["src"], "v4.29.1", self.row["version_info"][0]["v4.29.1"])
        self.assertIn(self.row["src"], source)
        self.assertEqual(path.name, "strata-v4.29.1")

    def test_forbidden_and_statement_changes_fail_before_compile(self):
        with self.assertRaisesRegex(ValueError, "Forbidden construct: sorry"):
            validate_proof(self.row, self.row["statement"] + " := by sorry")
        with self.assertRaisesRegex(ValueError, "statement differs"):
            validate_proof(self.row, "theorem Wrong := by trivial")
        drifted = self.row["statement"].replace("ks' vs' σ₁", "ks vs σ₁", 1) + " := by trivial"
        with self.assertRaisesRegex(ValueError, r"at statement line \d+: expected"):
            validate_proof(self.row, drifted)
        with self.assertRaisesRegex(ValueError, "second top-level command"):
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


class NewestMeasurementVersionTests(unittest.TestCase):
    def test_all_benchmark_rows_measure_on_the_newest_listed_toolchain(self):
        expected = {
            "CallElimCorrect.substOldPostSubset": "v4.26.0",
            "CallElimCorrect.extractedOldExprInVars": "v4.26.0",
            "Core.InitsUpdatesComm": "v4.29.1",
            "fundamental_theorem_of_variational_calculus'": "v4.32.0",
            "Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema": "v4.32.0",
            "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time": "v4.32.0",
            "Cslib.LambdaCalculus.LocallyNameless.Fsub.Typing.progress": "v4.33.0-rc2",
            "Cslib.SKI.parallelReduction_diamond": "v4.33.0-rc2",
            "Cslib.CCS.bisimilarity_congr_choice": "v4.33.0-rc2",
            "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius": "v4.31.0",
            "Binius.BinaryBasefold.fold_advances_evaluation_poly": "v4.31.0",
            "interleaved_affine_gaps_imply_tensor_gaps": "v4.31.0",
            "putnam_1964_a4": "v4.27.0",
            "putnam_1964_b2": "v4.26.0",
            "putnam_1995_a3": "v4.27.0",
        }
        rows = [json.loads(line) for line in engine.BENCHMARK.read_text().splitlines()]
        self.assertEqual({row["name"]: measure_version(row)[0] for row in rows}, expected)

    def test_toolchain_order_handles_releases_rcs_and_unparseable_names(self):
        self.assertLess(toolchain_key("v4.25.0"), toolchain_key("v4.29.1"))
        self.assertLess(toolchain_key("v4.33.0-rc2"), toolchain_key("v4.33.0"))
        with self.assertRaisesRegex(ValueError, "v4.next"):
            toolchain_key("v4.next")


class DiagnosticMappingTests(unittest.TestCase):
    def test_wrapper_shift_is_applied_once_after_insertion_point(self):
        self.assertEqual(map_measured_line(10, 20), (10, False))
        self.assertEqual(map_measured_line(20 + 5, 20), (20, True))
        self.assertEqual(map_measured_line(20 + WRAPPER_LINES, 20), (20, False))
        self.assertEqual(map_measured_line(20 + WRAPPER_LINES + 7, 20), (27, False))

    def test_messages_split_by_header_with_continuation_lines(self):
        output = (
            "a.lean:5:2: error: unsolved goals\ncase x\n⊢ False\n"
            "a.lean:9:0: warning: unused variable `h`\n"
            "a.lean:1:0: info: ARENA_HEARTBEATS 12"
        )
        found = parse_diagnostics(output)
        self.assertEqual([item["severity"] for item in found], ["error", "warning", "info"])
        self.assertIn("⊢ False", found[0]["message"])

    def test_unpositioned_info_lines_are_not_glued_to_the_previous_error(self):
        # Lean's command line prints logInfo output with no position header.
        output = (
            "a.lean:2:19: error: Type mismatch\n  rfl\nhas type\n  ?m.8 = ?m.8\n"
            "ARENA_HEARTBEATS 7\nTry this:\n  [apply] simp only"
        )
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
        result = structure_diagnostics("f.lean:32:2: error: unknown tactic", text, 30, 35, report_start_line=10)
        item = result["diagnostics"][0]
        self.assertEqual((item["file_line"], item["proof_line"]), (12, 3))
        self.assertEqual(item["source_line_text"], "line32")
        self.assertEqual(result["error_headlines"], ["line 12 (proof line 3): unknown tactic"])

    def test_only_target_span_becomes_headlines_and_text_matches_file(self):
        text = "\n".join(f"line{i}" for i in range(1, 31)) + "\n"
        # Measured file: wrapper inserted before line 10; an error on text line 12
        # is reported at 12 + 14, one on line 3 stays at 3, a warning on line 25 is outside.
        output = (
            f"f.lean:{12 + WRAPPER_LINES}:4: error: boom\n"
            "f.lean:3:0: error: earlier trouble\n"
            f"f.lean:{25 + WRAPPER_LINES}:0: warning: elsewhere\n"
            "f.lean:10:0: info: ARENA_HEARTBEATS 5"
        )
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
        physlib = (
            "@[expose] public section\n\nvariable {Y} [MeasurableSpace Y]\n\n/-- doc -/\nlemma t : True := trivial\n"
        )
        self.assertEqual(declaration_head(physlib, physlib.index("lemma")), physlib.index("/--"))
        module_doc = "/-! module notes -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(module_doc, module_doc.index("theorem")), module_doc.index("theorem"))

    def test_sorry_instrumentation_keeps_line_count(self):
        proof = "theorem t : True := by\n  constructor\n  · sorry\n  sorry\n  exact (by sorry)"
        out = instrument_sorries(proof)
        self.assertEqual(out.count("\n"), proof.count("\n"))
        self.assertEqual(out.count("trace_state; sorry"), 3)

    def test_sorry_in_match_and_case_arms_is_instrumented(self):
        proof = (
            "theorem t : True := by\n  rcases h with h | h\n  | inl h => sorry\n  | .inr h => sorry\n"
            "  case foo => sorry\n  next x => sorry\n  exact sorry_lemma\n  exact h_sorry"
        )
        out = instrument_sorries(proof)
        self.assertEqual(out.count("\n"), proof.count("\n"))
        self.assertEqual(out.count("trace_state; sorry"), 4)
        self.assertEqual(instrument_sorries("| case => sorry").count("trace_state; sorry"), 1)
        self.assertEqual(instrument_sorries("  | .inl h => sorry\n").count("trace_state; sorry"), 1)
        self.assertEqual(instrument_sorries("| a => foo\n  x = sorry"), "| a => foo\n  x = sorry")

    def test_probe_is_the_only_mode_that_accepts_sorry(self):
        row = problem(NAME)
        draft = row["statement"] + " := by\n  sorry"
        with self.assertRaisesRegex(ValueError, "Forbidden construct: sorry"):
            validate_proof(row, draft)
        self.assertGreater(validate_proof(row, draft, allow_sorry=True), 0)


class LocateSourceTests(unittest.TestCase):
    def test_exact_match_wins(self):
        source = "a\ntheorem t : True := by\n  trivial\nb\n"
        original = "theorem t : True := by\n  trivial"
        start, end = locate_source(source, original, "v1")
        self.assertEqual((start, end), (2, 2 + len(original)))
        self.assertEqual(source[start:end], original)

    def test_exact_match_beats_a_whitespace_variant_elsewhere(self):
        original = "theorem t : True := trivial"
        source = original + "\n-- theorem  t :  True := trivial\n"
        # Exact count is 1, so the fallback is never consulted.
        self.assertEqual(locate_source(source, original, "v1"), (0, len(original)))

    def test_unique_whitespace_difference_maps_to_original_offsets(self):
        source = "def a := 1\n\ntheorem t :  True := by\n    trivial\n\ndef b := 2\n"
        original = "theorem t : True := by\n  trivial"
        start, end = locate_source(source, original, "v1")
        self.assertEqual(source[start:end], "theorem t :  True := by\n    trivial")
        self.assertEqual(start, source.index("theorem"))
        self.assertEqual(source[end:], "\n\ndef b := 2\n")

    def test_ambiguous_or_absent_declaration_is_file_modified(self):
        original = "theorem t : True := trivial"
        for source in (
            "theorem t : True := trivial\ntheorem t : True := trivial\n",  # two exact
            "theorem t :  True := trivial\ntheorem t : True  := trivial\n",  # two loose
            "theorem u : True := trivial\n",
        ):  # none
            with self.assertRaisesRegex(ValueError, "pinned theorem is absent or ambiguous on v9"):
                locate_source(source, original, "v9")


class ProofLengthStatementTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT / "vendor/lean-refactor").is_dir():
            self.skipTest("pinned counter not vendored")

    def test_top_level_let_in_statement_does_not_cut_the_proof_early(self):
        statement = "theorem t : let x := 1 + 2 + 3; x = 6"
        body = " := by\n  intro x\n  rfl"
        proof = statement + body
        counted_body = _proof_length("theorem x : True" + body)
        self.assertEqual(_proof_length(proof, statement), counted_body)
        # Old behaviour (first depth-0 `:=`) swallowed the rest of the statement.
        self.assertGreater(_proof_length(proof), counted_body)

    def test_rows_without_a_statement_keep_their_counts(self):
        head = "theorem t : True"
        self.assertEqual(_proof_length(head + " := by\n  exact ⟨a, b⟩"), 7)
        self.assertEqual(_proof_length(head + " := by\n  exact ⟨a, b⟩", head), 7)
        # A statement that is not a prefix of the proof leaves it untouched.
        self.assertEqual(_proof_length(head + " := by\n  exact ⟨a, b⟩", "theorem other : True"), 7)


class PrefixCombinatorTests(unittest.TestCase):
    def head_is_before_prefix(self, prefix):
        text = f"def a := 1\n\n{prefix}\n/-- doc -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index(prefix.split("\n")[0]))

    def test_head_goes_before_omit_include_and_set_option_in(self):
        for prefix in ("omit [Foo] in", "include h in", "set_option maxHeartbeats 1 in"):
            with self.subTest(prefix=prefix):
                self.head_is_before_prefix(prefix)

    def test_prefix_without_doc_comment(self):
        text = "def a := 1\n\nomit [Foo] in\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index("omit"))

    def test_multi_line_prefix_and_stacked_prefixes(self):
        text = "def a := 1\n\nomit [Foo]\n  [Bar] in\n/-- doc -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index("omit"))
        stacked = "def a := 1\n\ninclude h in\nomit [Foo] in\n/-- doc -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(stacked, stacked.index("theorem")), stacked.index("include"))

    def test_without_a_prefix_behaviour_is_unchanged(self):
        text = "def a := 1\n\n/-- doc -/\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index("/--"))
        plain = "variable (h : True)\n\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(plain, plain.index("theorem")), plain.index("theorem"))

    def test_prefix_more_than_six_lines_up_is_not_swallowed(self):
        filler = "\n".join(f"  [C{i}]" for i in range(7))
        text = f"omit [Foo]\n{filler} in\ntheorem t : True := trivial\n"
        self.assertEqual(declaration_head(text, text.index("theorem")), text.index("theorem"))


@slow
@LEAN
class RealLeanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = FIXTURE.read_text()
        cls.broken = cls.good.replace(
            "exact Exists.intro σ'' ⟨InitStatesUpdated Hinit, Hinit, UpdateStates.update_none⟩", "exact rfl"
        )
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

    def test_every_toolchains_lines_match_the_materialized_primary_file(self):
        # The target starts on a different line in each version's file.
        result = evaluate(NAME, self.broken, "full")
        location = campaign.materialize(NAME, self.run_id, self.broken)
        materialized = Path(location["candidate_path"]).read_text().splitlines()
        self.assertEqual(len(result["compat"]), 3)
        primary = next(iter(result["compat"].values()))
        self.assertFalse(primary["passed"])
        self.assertIn("rfl", primary["diagnostics"][0]["source_line_text"])
        self.assertEqual(next(iter(result["compat"].values()))["diagnostics"][0]["severity"], "error")
        for version, outcome in result["compat"].items():
            self.assertTrue(outcome["diagnostics"], version)
            for item in outcome["diagnostics"]:
                self.assertEqual(materialized[item["file_line"] - 1], item["source_line_text"], version)
                self.assertEqual(item["file_line"], location["start_line"] + item["proof_line"] - 1, version)
                self.assertNotIn("ARENA_HEARTBEATS", item["message"])


if __name__ == "__main__":
    unittest.main()
