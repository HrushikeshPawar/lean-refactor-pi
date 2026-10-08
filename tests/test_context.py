import json
import unittest

from tests.slow import slow
from arena import campaign, context
from arena.engine import ROOT

NAME = "Core.InitsUpdatesComm"
LEAN = unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir(), "Strata fixture environment is not provisioned")
DENYLIST = ("induct-first", "witness", "factor-premises", "focused-goals", "Structural exploration",
            "opportunity map", "scheduled idea", "Rotate to another", "local-golf", "arena-candidate-126",
            "before versus after", "known solution")


class ParseTests(unittest.TestCase):
    def test_kickoff_declaration_names_are_source_handles(self):
        inventory = {"source": [{"name": "A.foo", "decl": "theorem", "origin": "proof", "proof_line": 2,
                                 "sig": "A.foo : True", "module": "A"}],
                     "dependency": [{"name": "A.helper", "decl": "theorem", "tag": "helper",
                                     "sig": "A.helper : True", "module": "A"}]}
        self.assertIn("decl:A.foo", "\n".join(context._used_section(inventory)))
        self.assertIn("decl:A.helper", "\n".join(context._dependency_section(inventory)))

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

    def test_missing_proof_boundary_marks_origin_unknown_and_renders_it(self):
        output = "\n".join([
            'ARENA_CTX ' + json.dumps({"kind": "source", "name": "A.foo", "line": 4, "column": 2, "decl": "theorem",
                                       "module": "A", "tag": "helper", "sig": "A.foo : True"}),
            'ARENA_CTX ' + json.dumps({"kind": "end"}),
        ])
        parsed = context.parse_context(output, 0, 1, None)
        self.assertEqual(parsed["source"][0]["origin"], "unknown")
        text = "\n".join(context._used_section(parsed))
        self.assertIn("A.foo [theorem] S:- P:- U:4", text)

    def test_dependency_tags_split_helpers_from_glue_and_counts_agree(self):
        def dep(name, tag, module="Other"):
            return {"name": name, "decl": "theorem", "module": module, "tag": tag, "sig": f"{name} : True"}
        inventory = {"source": [{"name": "Src.named", "decl": "theorem", "module": "Lib", "tag": "helper",
                                 "origin": "proof", "proof_line": 1, "sig": "Src.named : True"}],
                     "dependency": [dep("Src.named", "helper", "Lib"), dep("Lib.zeta", "helper", "Lib"),
                                    dep("Proj.alpha", "helper", "Proj.Basic"), dep("Here.beta", "helper", "this file"),
                                    dep("List.mem_cons._simp_1", "generated", "Init"),
                                    dep("IsOrdered.toPosMulMono", "instance"), dep("of_eq_true", "core", "Init"),
                                    dep("propext", "axiom", "Init"), dep("Mathlib.Tactic.Ring.add_congr", "tactic", "Mathlib.Tactic.Ring")],
                     "root": "Proj"}
        helpers, counts, named = context._extra_dependencies(inventory)
        self.assertEqual([i["name"] for i in helpers], ["Here.beta", "Proj.alpha", "Lib.zeta"])
        self.assertEqual(counts, {"generated": 1, "instance": 1, "axiom": 1, "tactic": 1, "core": 1})
        self.assertEqual(named, 1)
        section = "\n".join(context._dependency_section(inventory))
        self.assertNotIn("_simp_1\n", section)
        self.assertNotIn("of_eq_true", section)
        self.assertIn("generated 1, instance 1, axiom 1, tactic 1, core 1", section)
        self.assertIn("3 shown of 3 helpers", section)
        # the section's helper list and the manifest line agree on the same numbers
        self.assertEqual(len(helpers), 3)
        self.assertEqual([i["name"] for i in context._preview(helpers, "Proj")], ["Here.beta", "Proj.alpha", "Lib.zeta"])

    def test_previews_put_project_first_and_never_show_glue(self):
        items = [{"name": n, "tag": t, "module": m, "decl": "theorem", "sig": f"{n} : True"}
                 for n, t, m in [("And.right", "core", "Init"), ("Eq.symm", "core", "Init"),
                                 ("Zed.lib", "helper", "Mathlib.X"), ("Abe.lib", "helper", "Mathlib.Y"),
                                 ("Proj.lemma", "helper", "Proj.A"), ("Local.l", "helper", "this file"),
                                 ("x._simp_1", "generated", "Init"), ("inst", "instance", "Mathlib.Z")]]
        self.assertEqual([i["name"] for i in context._preview(items, "Proj")],
                         ["Local.l", "Proj.lemma", "Abe.lib", "Zed.lib"])

    def test_constant_index_tags_are_queryable(self):
        inventory = {"constant": [
            {"name": "A._simp_1", "kind": "theorem", "origin": "elaborated-proof", "tag": "generated"},
            {"name": "A.foo", "kind": "theorem", "origin": "elaborated-proof", "tag": "helper"},
        ]}
        self.assertEqual([i["name"] for i in context.constant_index(inventory, tag="generated")], ["A._simp_1"])

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


@slow
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

    def test_cached_constant_ranges_match_one_based_source_coordinates(self):
        indexed = context.constant_index(context.lean_context(NAME), name="Core.updatedStates")
        self.assertEqual(len(indexed), 1)
        entry = indexed[0]
        source = campaign.declaration(NAME, "decl:Core.updatedStates")
        self.assertEqual((entry["start_line"], entry["end_line"]),
                         (source["line"], source["end_line"]))

    def test_tags_classify_generated_instance_core_and_project_constants(self):
        tags = {item["name"]: item["tag"] for item in context.lean_context(NAME)["constant"]}
        self.assertTrue(all(tag == "generated" for name, tag in tags.items() if "_simp_" in name))
        self.assertEqual(tags.get("Eq.symm", "core"), "core")
        self.assertEqual(tags.get("Core.updatedStatesInit"), "helper")
        self.assertNotIn("of_eq_true\n", self.text)

    def test_pins_and_imports_are_stated_once(self):
        self.assertEqual(self.text.count("Available imports"), 1)
        self.assertEqual(self.text.count("Lean toolchain and source revisions"), 1)

    def test_source_occurrences_can_appear_in_both_statement_and_proof(self):
        items = [item for item in context.lean_context(NAME)["source"] if item["name"] == "Core.updatedStates"]
        self.assertEqual({item["origin"] for item in items}, {"statement", "proof"})

    def test_goal_trace_profile_and_exchange_rates_are_present(self):
        self.assertIn("-- before proof line 11", self.text)
        self.assertIn("⊢ ∃ σ₁", self.text)
        self.assertIn("Heartbeat profile of the reference proof", self.text)
        self.assertIn("Top self costs", self.text)
        self.assertIn("Top-ten starting lines by score-equivalent baseline cost", self.text)
        self.assertIn("tactic spans: proof", self.text)
        self.assertIn("1 token = 0.149 pt", self.text)
        self.assertIn("100 heartbeats = 0.784 pt", self.text)
        self.assertIn("one lost toolchain version = 11.11 pt", self.text)

    def test_packet_is_deterministic_bounded_and_strategy_free(self):
        self.assertEqual(self.text, context.render_packet(NAME))
        self.assertLessEqual(len(self.text), context.MAX_PACKET_CHARS + 2)
        for phrase in DENYLIST:
            self.assertNotIn(phrase, self.text, phrase)


@slow
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


@slow
@unittest.skipUnless((ROOT / "workspaces/physlib-v4.32.0").is_dir(), "PhysLib fixture environment is not provisioned")
class PhyslibInventoryTests(unittest.TestCase):
    name = "fundamental_theorem_of_variational_calculus'"

    @classmethod
    def setUpClass(cls):
        cls.context = context.lean_context(cls.name)
        cls.packet = context.render_packet(cls.name)

    def test_every_source_and_helper_name_survives_bounded_packet_fitting(self):
        source_names = {item["name"] for item in self.context["source"]}
        helpers = context._extra_dependencies(self.context)[0]
        for name in source_names | {item["name"] for item in helpers}:
            self.assertIn(name, self.packet, name)
        self.assertLess(len(helpers), len({item["name"] for item in self.context["dependency"]}) / 2)
        self.assertIn(f"{len(helpers)} helpers shown", self.packet)
        self.assertLessEqual(len(self.packet), context.MAX_PACKET_CHARS + 1)
        self.assertIn("Source names:", self.packet)
        self.assertIn("Extra direct theorem/lemma dependencies:", self.packet)

    def test_constant_index_and_packet_are_stable_for_the_same_pin(self):
        all_constants = context.constant_index(self.context)
        self.assertTrue(all_constants)
        self.assertTrue(all(item["origin"] == "elaborated-proof" and item.get("kind")
                            for item in all_constants))
        self.assertEqual(self.packet, context.render_packet(self.name))


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


if __name__ == "__main__":
    unittest.main()
