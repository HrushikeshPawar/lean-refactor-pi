import json
import unittest
from pathlib import Path

from arena import context
from arena.engine import ROOT

NAME = "Core.InitsUpdatesComm"
LEAN = unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir(), "Strata fixture environment is not provisioned")
DENYLIST = ("induct-first", "witness", "factor-premises", "focused-goals", "Structural exploration",
            "opportunity map", "scheduled idea", "Rotate to another", "local-golf", "arena-candidate-126",
            "before versus after", "known solution")


class ParseTests(unittest.TestCase):
    def test_records_are_grouped_and_lines_mapped_past_the_instrumentation(self):
        output = "\n".join([
            'noise line',
            'ARENA_CTX ' + json.dumps({"kind": "goal", "line": 130, "endLine": 131, "text": "⊢ True"}),
            'ARENA_CTX ' + json.dumps({"kind": "used", "line": 132, "name": "foo", "decl": "theorem", "module": "M", "sig": "foo : True"}),
            'ARENA_CTX ' + json.dumps({"kind": "end"}),
        ])
        parsed = context.parse_context(output, shift=100, start_line=20)
        self.assertTrue(parsed["complete"])
        self.assertEqual((parsed["goal"][0]["proof_line"], parsed["goal"][0]["end_proof_line"]), (11, 12))
        self.assertEqual(parsed["used"][0]["proof_line"], 13)

    def test_incomplete_output_is_not_trusted(self):
        self.assertFalse(context.parse_context("ARENA_CTX " + json.dumps({"kind": "goal", "line": 1, "endLine": 1, "text": ""}), 0, 1)["complete"])


class TruncationTests(unittest.TestCase):
    def test_over_budget_packets_shed_the_lowest_priority_entries_deterministically(self):
        big = [f"entry {i} " + "x" * 200 for i in range(40)]
        parts = [("Head", ["keep me"]), ("Goal before each top-level tactic of the reference proof", big[:10]),
                 ("Signatures of constants the reference proof mentions", big[:20]),
                 ("Lemmas declared earlier in this file", big)]
        first = context._fit(parts, 6000)
        second = context._fit(parts, 6000)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 6000)
        self.assertIn("keep me", first)
        self.assertIn("entry 0 ", first)
        self.assertNotIn("entry 39 ", first)


@LEAN
class FixturePacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = context.render_packet(NAME)

    def test_statement_types_are_defined_with_constructors(self):
        self.assertIn("Core.UpdateStates.update_some", self.text)
        self.assertIn("Core.InitStates.init_some", self.text)
        self.assertIn("Imperative.SemanticStore", self.text)

    def test_earlier_lemmas_and_used_constants_include_namespaced_and_library_names(self):
        self.assertIn("Core.InitStatesSomeMonotone", self.text)
        self.assertIn("List.unzip_zip", self.text)
        self.assertIn("Exists.intro", self.text)
        self.assertIn("[theorem · this file] Core.updatedStatesInit", self.text)

    def test_goal_trace_profile_and_exchange_rates_are_present(self):
        self.assertIn("-- before proof line 11", self.text)
        self.assertIn("⊢ ∃ σ₁", self.text)
        self.assertIn("Heartbeat profile of the reference proof", self.text)
        self.assertIn("Top self costs", self.text)
        self.assertIn("1 token = 0.149 pt", self.text)
        self.assertIn("100 heartbeats = 0.784 pt", self.text)
        self.assertIn("one lost toolchain version = 11.11 pt", self.text)

    def test_packet_is_deterministic_bounded_and_strategy_free(self):
        self.assertEqual(self.text, context.render_packet(NAME))
        self.assertLessEqual(len(self.text), context.MAX_PACKET_CHARS + 2)
        for phrase in DENYLIST:
            self.assertNotIn(phrase, self.text, phrase)


@LEAN
class PortabilityTests(unittest.TestCase):
    def test_wrappers_run_on_every_provisioned_toolchain_of_the_fixture(self):
        from arena import profile as profiler
        from arena.engine import candidate_file, problem, run_lean, versions

        row = problem(NAME)
        ran = 0
        for version, commit in versions(row):
            if not (ROOT / "workspaces" / f"strata-{version}").is_dir():
                continue
            built = candidate_file(row, row["src"], version, commit)
            sources = {"context": context.LEAN_FILE.read_text().replace("@@ROOTS@@", '"Strata"'),
                       "profile": profiler.preamble(profiler.MAX_DEPTH)}
            for label, inserted in sources.items():
                text = built["text"][:built["offset"]] + inserted + built["text"][built["offset"]:]
                code, output = run_lean(row, built["path"], text)
                marker = '"kind":"end"' if label == "context" else "ARENA_PROFILE_TOTAL"
                self.assertIn(marker, output, f"{label} wrapper failed on {version}: {output[:300]}")
            ran += 1
        self.assertGreaterEqual(ran, 1)


if __name__ == "__main__":
    unittest.main()
