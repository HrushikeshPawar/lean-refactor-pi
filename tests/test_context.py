import json
import unittest

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

    def test_occurrences_keep_position_and_origin_and_dependencies_stay_separate(self):
        output = "\n".join([
            'ARENA_CTX ' + json.dumps({"kind": "source", "name": "A.foo", "line": 4, "origin": "statement", "decl": "theorem", "module": "A", "sig": "A.foo : True"}),
            'ARENA_CTX ' + json.dumps({"kind": "source", "name": "A.foo", "line": 8, "origin": "proof", "decl": "theorem", "module": "A", "sig": "A.foo : True"}),
            'ARENA_CTX ' + json.dumps({"kind": "dependency", "name": "B.helper", "decl": "theorem", "module": "B", "sig": "B.helper : True"}),
            'ARENA_CTX ' + json.dumps({"kind": "end"}),
        ])
        parsed = context.parse_context(output, 0, 1)
        self.assertEqual([item["origin"] for item in parsed["source"]], ["statement", "proof"])
        self.assertEqual([item["proof_line"] for item in parsed["source"]], [4, 8])
        self.assertEqual(parsed["dependency"][0]["name"], "B.helper")

    def test_source_occurrence_origin_uses_the_boundary_even_on_one_line(self):
        output = "\n".join([
            'ARENA_CTX ' + json.dumps({"kind": "source", "name": "A.foo", "line": 1, "column": 12}),
            'ARENA_CTX ' + json.dumps({"kind": "source", "name": "A.bar", "line": 1, "column": 28}),
            'ARENA_CTX ' + json.dumps({"kind": "end"}),
        ])
        parsed = context.parse_context(output, 0, 1, (1, 20))
        self.assertEqual([item["origin"] for item in parsed["source"]], ["statement", "proof"])

    def test_constant_index_filters_all_dimensions(self):
        inventory = {"constant": [
            {"name": "A.foo", "kind": "theorem", "origin": "elaborated-proof"},
            {"name": "A.Bar.mk", "kind": "constructor", "origin": "elaborated-proof"},
        ]}
        self.assertEqual(context.constant_index(inventory, kind="theorem")[0]["name"], "A.foo")
        self.assertEqual(context.constant_index(inventory, name="A.foo", origin="elaborated-proof")[0]["kind"],
                         "theorem")

    def test_proof_boundary_ignores_comments_and_nested_type_syntax(self):
        self.assertEqual(context._proof_boundary("theorem x : (let y := 1; y = 1) := by trivial", 1), (1, 32))

    def test_manifest_reports_required_sections_and_certification_fails_closed(self):
        inventory = {"source": [], "dependency": [], "complete": True}
        rendered = context.packet_manifest([("Pinned environment and candidate", ["Lean x"]),
                                            ("Source-named declarations", [])], inventory)
        self.assertEqual(rendered["sections"]["Pinned environment and candidate"],
                         {"expected": True, "present": True})
        self.assertFalse(context.certify_manifest(rendered, ["Pinned environment and candidate",
                                                              "Elaborated proof dependencies"])["certified"])

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
        self.assertIn("Core.updatedStatesInit [theorem]", self.text)

    def test_pinned_constant_index_keeps_elaborated_constructor_queryable(self):
        indexed = context.constant_index(context.lean_context(NAME), name="Exists.intro",
                                         kind="constructor", origin="elaborated-proof")
        self.assertEqual(len(indexed), 1)

    def test_source_occurrences_can_appear_in_both_statement_and_proof(self):
        items = [item for item in context.lean_context(NAME)["source"] if item["name"] == "Core.updatedStates"]
        self.assertEqual({item["origin"] for item in items}, {"statement", "proof"})

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
            sources = {"context": context.LEAN_FILE.read_text().replace("@@ROOTS@@", '"Strata"')
                       .replace("@@TARGET@@", context._lean_name(NAME)),
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


class ScopeTests(unittest.TestCase):
    """The packet's scope section is syntactic, so it works for every corpus."""

    def test_open_and_variable_of_closed_scopes_are_dropped(self):
        from arena.context import scope_lines
        source = ("import X\n/-! notes\nopen Fake -/\nnamespace A\nopen B\nsection S\nvariable (x : Nat)\n"
                  "  (y : Nat)\nopen C in\ntheorem t : True := trivial\nend S\nvariable {Y} [Foo Y]\n"
                  "open D in\n")
        self.assertEqual(scope_lines(source), ["namespace A", "open B", "variable {Y} [Foo Y]", "open D in"])

    def test_stale_open_in_does_not_leak(self):
        from arena.context import scope_lines
        self.assertEqual(scope_lines("open E in\ntheorem u : True := trivial\n\n"), ["(root namespace)"])
