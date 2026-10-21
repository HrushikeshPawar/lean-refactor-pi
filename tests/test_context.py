import json
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import campaign, context
from arena.engine import ROOT
from tests.slow import slow

NAME = "Core.InitsUpdatesComm"
LEAN = unittest.skipUnless(
    (ROOT / "workspaces/strata-v4.29.1").is_dir(), "Strata fixture environment is not provisioned"
)
DENYLIST = (
    "induct-first",
    "witness",
    "factor-premises",
    "focused-goals",
    "Structural exploration",
    "opportunity map",
    "scheduled idea",
    "Rotate to another",
    "local-golf",
    "arena-candidate-126",
    "before versus after",
    "known solution",
)


class ParseTests(unittest.TestCase):
    def test_cached_packet_prices_steps_and_keeps_library_ahead_of_locals(self):
        fixtures = Path(__file__).parent / "fixtures/agent_text"
        inventory = json.loads((fixtures / "core-context.json").read_text())
        measured = json.loads((fixtures / "core-profile.json").read_text())
        with (
            patch.object(context, "cached_context", return_value=inventory),
            patch.object(context, "reference_profile", return_value=measured),
        ):
            packet = context.render_packet(NAME, cache_only=True)
        self.assertLess(packet.index("Original proof"), packet.index("| step | lines |"))
        self.assertLess(packet.index("| step | lines |"), packet.index("before s1"))
        self.assertLess(packet.index("before s1"), packet.index("Imported declarations"))
        self.assertIn("s1", packet)
        self.assertNotIn("Heartbeat profile of the reference proof", packet)
        self.assertNotIn("Kickoff inventory manifest", packet)

    def test_kickoff_declaration_names_are_source_handles(self):
        inventory = {
            "source": [
                {
                    "name": "A.foo",
                    "decl": "theorem",
                    "origin": "proof",
                    "proof_line": 2,
                    "sig": "A.foo : True",
                    "module": "A",
                }
            ],
            "dependency": [
                {"name": "A.helper", "decl": "theorem", "tag": "helper", "sig": "A.helper : True", "module": "A"}
            ],
        }
        self.assertIn("decl:A.foo", "\n".join(context._used_section(inventory)))
        self.assertIn("decl:A.helper", "\n".join(context._dependency_section(inventory)))

    def test_records_are_grouped_and_lines_mapped_past_the_instrumentation(self):
        output = "\n".join(
            [
                "noise line",
                "ARENA_CTX " + json.dumps({"kind": "goal", "line": 130, "endLine": 131, "text": "⊢ True"}),
                "ARENA_CTX "
                + json.dumps(
                    {"kind": "used", "line": 132, "name": "foo", "decl": "theorem", "module": "M", "sig": "foo : True"}
                ),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, shift=100, start_line=20)
        self.assertTrue(parsed["complete"])
        self.assertEqual((parsed["goal"][0]["proof_line"], parsed["goal"][0]["end_proof_line"]), (11, 12))
        self.assertEqual(parsed["used"][0]["proof_line"], 13)

    def test_occurrences_keep_position_and_origin_and_dependencies_stay_separate(self):
        output = "\n".join(
            [
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "source",
                        "name": "A.foo",
                        "line": 4,
                        "origin": "statement",
                        "decl": "theorem",
                        "module": "A",
                        "sig": "A.foo : True",
                    }
                ),
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "source",
                        "name": "A.foo",
                        "line": 8,
                        "origin": "proof",
                        "decl": "theorem",
                        "module": "A",
                        "sig": "A.foo : True",
                    }
                ),
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "dependency",
                        "name": "B.helper",
                        "decl": "theorem",
                        "module": "B",
                        "sig": "B.helper : True",
                    }
                ),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, 0, 1)
        self.assertEqual([item["origin"] for item in parsed["source"]], ["statement", "proof"])
        self.assertEqual([item["proof_line"] for item in parsed["source"]], [4, 8])
        self.assertEqual(parsed["dependency"][0]["name"], "B.helper")

    def test_source_occurrence_origin_uses_the_boundary_even_on_one_line(self):
        output = "\n".join(
            [
                "ARENA_CTX " + json.dumps({"kind": "source", "name": "A.foo", "line": 1, "column": 12}),
                "ARENA_CTX " + json.dumps({"kind": "source", "name": "A.bar", "line": 1, "column": 28}),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, 0, 1, (1, 20))
        self.assertEqual([item["origin"] for item in parsed["source"]], ["statement", "proof"])

    def test_missing_proof_boundary_marks_origin_unknown_and_renders_it(self):
        output = "\n".join(
            [
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "source",
                        "name": "A.foo",
                        "line": 4,
                        "column": 2,
                        "decl": "theorem",
                        "module": "A",
                        "tag": "helper",
                        "sig": "A.foo : True",
                    }
                ),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, 0, 1, None)
        self.assertEqual(parsed["source"][0]["origin"], "unknown")
        text = "\n".join(context._used_section(parsed))
        self.assertIn("A.foo [theorem] S:- P:- U:4", text)

    def test_dependency_tags_split_helpers_from_glue_and_counts_agree(self):
        def dep(name, tag, module="Other"):
            return {"name": name, "decl": "theorem", "module": module, "tag": tag, "sig": f"{name} : True"}

        inventory = {
            "source": [
                {
                    "name": "Src.named",
                    "decl": "theorem",
                    "module": "Lib",
                    "tag": "helper",
                    "origin": "proof",
                    "proof_line": 1,
                    "sig": "Src.named : True",
                }
            ],
            "dependency": [
                dep("Src.named", "helper", "Lib"),
                dep("Lib.zeta", "helper", "Lib"),
                dep("Proj.alpha", "helper", "Proj.Basic"),
                dep("Here.beta", "helper", "this file"),
                dep("List.mem_cons._simp_1", "generated", "Init"),
                dep("IsOrdered.toPosMulMono", "instance"),
                dep("of_eq_true", "core", "Init"),
                dep("propext", "axiom", "Init"),
                dep("Mathlib.Tactic.Ring.add_congr", "tactic", "Mathlib.Tactic.Ring"),
            ],
            "root": "Proj",
        }
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
        self.assertEqual(
            [i["name"] for i in context._preview(helpers, "Proj")], ["Here.beta", "Proj.alpha", "Lib.zeta"]
        )

    def test_previews_put_project_first_and_never_show_glue(self):
        items = [
            {"name": n, "tag": t, "module": m, "decl": "theorem", "sig": f"{n} : True"}
            for n, t, m in [
                ("And.right", "core", "Init"),
                ("Eq.symm", "core", "Init"),
                ("Zed.lib", "helper", "Mathlib.X"),
                ("Abe.lib", "helper", "Mathlib.Y"),
                ("Proj.lemma", "helper", "Proj.A"),
                ("Local.l", "helper", "this file"),
                ("x._simp_1", "generated", "Init"),
                ("inst", "instance", "Mathlib.Z"),
            ]
        ]
        self.assertEqual(
            [i["name"] for i in context._preview(items, "Proj")], ["Local.l", "Proj.lemma", "Abe.lib", "Zed.lib"]
        )

    def test_constant_index_tags_are_queryable(self):
        inventory = {
            "constant": [
                {"name": "A._simp_1", "kind": "theorem", "origin": "elaborated-proof", "tag": "generated"},
                {"name": "A.foo", "kind": "theorem", "origin": "elaborated-proof", "tag": "helper"},
            ]
        }
        self.assertEqual([i["name"] for i in context.constant_index(inventory, tag="generated")], ["A._simp_1"])

    def test_constant_index_filters_all_dimensions(self):
        inventory = {
            "constant": [
                {"name": "A.foo", "kind": "theorem", "origin": "elaborated-proof"},
                {"name": "A.Bar.mk", "kind": "constructor", "origin": "elaborated-proof"},
            ]
        }
        self.assertEqual(context.constant_index(inventory, kind="theorem")[0]["name"], "A.foo")
        self.assertEqual(
            context.constant_index(inventory, name="A.foo", origin="elaborated-proof")[0]["kind"], "theorem"
        )

    def test_proof_boundary_ignores_comments_and_nested_type_syntax(self):
        self.assertEqual(context._proof_boundary("theorem x : (let y := 1; y = 1) := by trivial", 1), (1, 32))

    def test_manifest_reports_required_sections_and_certification_fails_closed(self):
        inventory = {"source": [], "dependency": [], "complete": True}
        pinned = context.REQUIRED_SECTIONS[0]
        rendered = context.packet_manifest([(pinned, ["Lean x"]), ("Source-named declarations", [])], inventory)
        self.assertEqual(rendered["sections"][pinned], {"expected": True, "present": True})
        self.assertFalse(context.certify_manifest(rendered, [pinned, "Source-named declarations"])["certified"])

    def test_incomplete_output_is_not_trusted(self):
        self.assertFalse(
            context.parse_context(
                "ARENA_CTX " + json.dumps({"kind": "goal", "line": 1, "endLine": 1, "text": ""}), 0, 1
            )["complete"]
        )

    def test_v8_context_retains_target_facts(self):
        """One fixture packet keeps the conclusion, the ninth statement predicate, and truthful coordinates."""
        from arena.engine import problem

        base = problem(NAME)
        proof = "theorem t (h : Nat := by omega) : Close := by\n  exact a\n  exact b\n  exact c\n"
        row = {
            **base,
            "file_path": "",
            "header": "public import Public.Mod\nprivate import Secret.Mod\n",
            "statement": "theorem t (h : Nat := by omega) : Close",
            "src": proof,
            "proof_length": 4,
        }
        conclusion = "⊢ hammingClose target"
        raw = "\n".join(
            [
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "goal",
                        "line": 101,
                        "endLine": 101,
                        "text": "h : "
                        + ("H " * 500)
                        + "\n"
                        + conclusion
                        + "\n\ncase other\nh : "
                        + ("H " * 500)
                        + "\n⊢ otherCase",
                    }
                ),
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "source",
                        "line": 12,
                        "column": 4,
                        "name": "Ext.pred",
                        "decl": "def",
                        "module": "Other.File",
                        "tag": "helper",
                        "sig": "Ext.pred : Prop",
                    }
                ),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(raw, shift=0, start_line=100, proof_boundary=(2, 0))
        external = parsed["source"][0]
        self.assertEqual(external["origin"], "external")
        self.assertEqual(external["source_line"], 12)
        self.assertNotIn("proof_line", external)
        parsed["complete"] = True
        parsed["target"] = [{"consts": ["Proj.hammingClose"], "core_consts": [], "concl_head": "Close"}]
        parsed["type"] = [
            {
                "name": f"Aux.gen{i}",
                "decl": "def",
                "sig": f"Aux.gen{i} : Unit",
                "value": "()",
                "role": "auxiliary",
            }
            for i in range(8)
        ] + [
            {
                "name": f"Proj.pred{i}",
                "decl": "def",
                "sig": f"Proj.pred{i} : Prop",
                "value": "true",
                "role": "statement",
            }
            for i in range(8)
        ] + [
            {
                "name": "Proj.hammingClose",
                "decl": "def",
                "sig": "Proj.hammingClose : Prop",
                "value": "true",
                "role": "statement",
            }
        ]
        parsed["earlier"] = [
            {
                "name": "Proj.reuseLemma",
                "decl": "theorem",
                "line": 90,
                "sig": "Proj.reuseLemma : Close",
                "consts": ["Proj.hammingClose"],
                "core_consts": [],
                "concl_head": "Proj.hammingClose",
                "lhs_head": "",
                "rhs_head": "",
                "rel": "",
                "uses": [],
            }
        ]
        parsed["local"] = [
            {
                "name": f"noise{i}",
                "type": "Unit " * 40,
                "scope": "theorem proof context",
                "proof_line": 2,
            }
            for i in range(220)
        ]
        profile = {"ok": True, "measured_total": 1, "profiled_total": 1, "unattributed": 0, "line_profile": []}
        with (
            patch.object(context, "problem", lambda _name: row),
            patch.object(context, "cached_context", return_value=parsed),
            patch.object(context, "reference_profile", return_value=profile),
        ):
            packet = context.render_packet(NAME, cache_only=True)
        self.assertIn(conclusion, packet)
        self.assertIn("⊢ otherCase", packet)
        self.assertIn("case other", packet)
        self.assertIn("decl:Proj.hammingClose", packet)
        self.assertIn("public import Public.Mod", packet)
        self.assertNotIn("private import", packet)
        self.assertIn("file line 12", packet)
        self.assertNotRegex(packet, r"S:-\d+")
        self.assertIn("decl:Proj.reuseLemma", packet)
        self.assertNotIn("goal:s1", packet)
        self.assertIn("goal(node=<original proof node>, line=<proof line>)", packet)
        self.assertIn("1 captured of 3", packet)
        self.assertIn("Extraction complete", packet)
        self.assertLess(packet.count("(unavailable)"), 2)
        self.assertLess(packet.count("noise"), 220)
        coverage = context.context_coverage(parsed, proof)
        self.assertTrue(parsed["complete"])
        self.assertEqual(coverage["goals_captured"], 1)
        self.assertEqual(coverage["goals_expected"], 3)
        self.assertGreater(coverage["display_clipped"], 0)

        with self.subTest("complete scoped multiline conclusions"):
            goal = "case first\nh : Shared\n⊢ firstTarget\n  continuation one\ncase second\nh : Shared\n⊢ secondTarget\n  continuation two"
            shown, clipped = context._show_goal(goal, 10)
            self.assertTrue(clipped)
            for fragment in ("case first", "case second", "firstTarget\n  continuation one", "secondTarget\n  continuation two"):
                self.assertIn(fragment, shown)
            single, _ = context._show_goal("h : Shared\n⊢ result", 100)
            self.assertEqual(single.count("h : Shared"), 1)

        with self.subTest("coverage includes steps beyond display cap and rejects empty states"):
            long_proof = "theorem long : True := by\n" + "  exact trivial\n" * 45
            steps = context.split_steps(long_proof)
            inventory = {"complete": True, "goal": [
                {"proof_line": step.first_line, "text": "⊢ True"} for step in steps
            ]}
            inventory["goal"][0]["text"] = ""
            coverage = context.context_coverage(inventory, long_proof)
            self.assertEqual(coverage["goals_expected"], 45)
            self.assertEqual(coverage["goals_captured"], 44)
            self.assertEqual(coverage["goals_omitted"], 1)
            self.assertEqual(coverage["goals_displayed"], context.LIMITS["goals"])
            self.assertEqual(coverage["goal_display_omitted"], 44 - context.LIMITS["goals"])
            body = context._goal_section(inventory, long_proof)
            title = context.template("packet/sections.titles.goals").strip()
            fitted = context._fit_sections([(title, body)], len(context._join_sections([(title, body)])) - 25)
            fitted_text = context._join_sections(fitted)
            self.assertIn("44 captured of 45", fitted_text)
            self.assertIn("Packet fitting omitted", fitted_text)
            self.assertLess(len(fitted[0][1]), len(body))

        with self.subTest("restart fitting removes whole multiline goal entries"):
            inventory = {"complete": True, "goal": [
                {"proof_line": step.first_line,
                 "text": f"⊢ target{index}\n  continuation{index}"}
                for index, step in enumerate(context.split_steps(long_proof))
            ]}
            body = context._goal_section(inventory, long_proof)
            content = title + "\n" + "\n".join(body)
            for cut in (1, 25, 70, 120, 150):
                fitted = campaign._kickoff_within([(title, content)], len(content) - cut)
                for index in range(context.LIMITS["goals"]):
                    if f"⊢ target{index}\n" in fitted:
                        self.assertIn(f"⊢ target{index}\n  continuation{index}", fitted)
                self.assertIn("45 captured of 45", fitted)
                self.assertIn("Packet fitting omitted", fitted)

        with self.subTest("wrapper offsets preserve external lines and reject wrapper syntax"):
            records = "\n".join("ARENA_CTX " + json.dumps({
                "kind": "source", "name": name, "line": line, "column": 0, "decl": "def",
                "module": "this file", "tag": "helper",
            }) for name, line in (("earlier", 12), ("wrapper", 30), ("target", 122)))
            mapped = context.parse_context(records, 100, 20, (2, 0), insertion_line=18)
            earlier, wrapper, target = mapped["source"]
            self.assertEqual(earlier["source_line"], 12)
            self.assertEqual(earlier["origin"], "external")
            self.assertEqual(wrapper["origin"], "unknown")
            self.assertNotIn("source_line", wrapper)
            self.assertNotIn("proof_line", wrapper)
            self.assertEqual(target["proof_line"], 3)
            self.assertEqual(target["origin"], "proof")
            rendered = "\n".join(context._used_section(mapped))
            self.assertIn("U:?", rendered)
            self.assertIn("file line 12", rendered)

        with self.subTest("strict implicit binder default precedes actual proof"):
            strict = "theorem t ⦃h : Nat := by omega⦄ : True := by trivial"
            self.assertEqual(context._proof_boundary(strict, 1), (1, strict.rindex(":=")))

        with self.subTest("legacy type cache does not silently drop the ninth target"):
            legacy = {"type": [{key: value for key, value in item.items() if key != "role"}
                               for item in parsed["type"]]}
            types = "\n".join(context._types_section(legacy))
            self.assertIn("decl:Proj.hammingClose", types)
            self.assertIn("Unknown statement roles: 17", types)


class RankingTests(unittest.TestCase):
    @staticmethod
    def lemma(name, line, consts, **extra):
        return {
            "name": name,
            "line": line,
            "decl": "theorem",
            "sig": f"{name} : ...",
            "consts": consts,
            "core_consts": extra.pop("core", []),
            "uses": extra.pop("uses", []),
            "rel": extra.pop("rel", ""),
            "concl_head": extra.pop("head", ""),
            "lhs_head": "",
            "rhs_head": "",
            "lhs_consts": [],
            **extra,
        }

    def inventory(self):
        noise = [self.lemma(f"N.noise{i}", 100 + i, ["N.Ctx", "N.Wf"]) for i in range(12)]
        earlier = [
            *noise,
            self.lemma("N.near", 999, ["N.Ctx", "N.other"]),
            self.lemma(
                "N.far_rw", 5, ["N.step", "N.Ctx"], rel="eq", lhs_head="N.step", rhs_head="N.run", lhs_consts=["N.step"]
            ),
            self.lemma("N.far_mention", 6, ["N.step", "N.Ctx"], head="N.Reach"),
            self.lemma("N.libonly", 7, ["N.lemma_free"], core=["List.map", "Nat.add"]),
            self.lemma("N.helper", 8, ["N.Ctx", "N.zip"]),
            self.lemma("N.user", 9, ["N.step", "N.run"], uses=["N.helper"]),
        ]
        return {
            "earlier": earlier,
            "target": [{"consts": ["N.step", "N.run", "N.Ctx"], "core_consts": ["List.map"]}],
            "constant": [
                {"name": "N.run", "tag": "helper", "module": "this file"},
                {"name": "Nat.add", "tag": "core", "module": "Init.Prelude"},
            ],
            "goal": [
                {
                    "consts": ["N.step"],
                    "core_consts": [],
                    "concl_head": "N.Reach",
                    "lhs_head": "",
                    "rhs_head": "",
                    "rel": "",
                }
            ],
        }

    def test_relevant_far_lemmas_beat_nearby_noise_and_generic_constants_score_zero(self):
        ranked = [entry["item"]["name"] for entry in context.score_earlier(self.inventory())]
        for name in ("N.far_rw", "N.far_mention", "N.user"):
            self.assertLess(ranked.index(name), ranked.index("N.near"))
        self.assertLess(ranked.index("N.far_mention"), ranked.index("N.libonly"))
        by_name = {e["item"]["name"]: e for e in context.score_earlier(self.inventory())}
        self.assertEqual(by_name["N.noise0"]["relevance"], 0)  # N.Ctx is in most statements: no signal

    def test_reasons_name_shared_constants_equations_and_goal_heads(self):
        by_name = {e["item"]["name"]: e for e in context.score_earlier(self.inventory())}
        self.assertIn("equation overlap", by_name["N.far_rw"]["reason"])
        self.assertIn("mentions step", by_name["N.far_rw"]["reason"])
        self.assertIn("concludes Reach", by_name["N.far_mention"]["reason"])
        self.assertIn("used by nearby declarations", by_name["N.helper"]["reason"])

    def test_section_orders_by_score_keeps_handles_and_fits_the_character_budget(self):
        lines = context._earlier_section(self.inventory())
        self.assertTrue(lines[0].startswith("line "))
        self.assertIn("[decl:N.", lines[0])
        self.assertLess(
            next(i for i, line in enumerate(lines) if "decl:N.far_rw " in line),
            next(i for i, line in enumerate(lines) if "decl:N.near " in line),
        )
        context.LIMITS["earlier_budget"], saved = 300, context.LIMITS["earlier_budget"]
        try:
            short = context._earlier_section(self.inventory())
        finally:
            context.LIMITS["earlier_budget"] = saved
        self.assertLessEqual(sum(len(line) + 1 for line in short), 300)
        self.assertEqual(short, lines[: len(short)])

    def test_zero_relevance_filler_is_capped_and_empty_context_is_safe(self):
        lines = context._earlier_section(self.inventory())
        zero_relevance = {
            entry["item"]["name"] for entry in context.score_earlier(self.inventory()) if entry["relevance"] == 0
        }
        self.assertLessEqual(sum(any(f"decl:{name} " in line for name in zero_relevance) for line in lines), 5)
        self.assertEqual(context._earlier_section({}), [])

    def test_parse_context_keeps_target_and_relevance_fields(self):
        output = "\n".join(
            [
                "ARENA_CTX " + json.dumps({"kind": "target", "consts": ["A"]}),
                "ARENA_CTX "
                + json.dumps(
                    {
                        "kind": "earlier",
                        "name": "A.b",
                        "line": 3,
                        "decl": "theorem",
                        "sig": "",
                        "uses": [],
                        "consts": ["A"],
                    }
                ),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, 0, 1)
        self.assertEqual(parsed["target"][0]["consts"], ["A"])
        self.assertEqual(parsed["earlier"][0]["consts"], ["A"])


class LibrarySectionTests(unittest.TestCase):
    @staticmethod
    def record(name, score, shared=("A.foo", "B.bar"), sig=None):
        return {
            "kind": "library",
            "name": name,
            "score": str(score),
            "module": "Mathlib.X",
            "shared": list(shared),
            "concl_shared": [],
            "sig": sig or f"{name} : A.foo x -> B.bar x",
        }

    def test_records_are_parsed_in_order_and_rendered_with_handles_and_signatures(self):
        output = "\n".join(
            [
                "ARENA_CTX " + json.dumps(self.record("L.best", 9)),
                "ARENA_CTX " + json.dumps(self.record("L.next", 8)),
                "ARENA_CTX "
                + json.dumps({"kind": "library_scan", "scanned": 5, "pool": 3, "truncated": False, "ms": 1}),
                "ARENA_CTX " + json.dumps({"kind": "end"}),
            ]
        )
        parsed = context.parse_context(output, 0, 1)
        self.assertEqual([r["name"] for r in parsed["library"]], ["L.best", "L.next"])
        lines = context._library_section(parsed)
        self.assertTrue(lines[0].startswith("1. decl:L.best · Mathlib.X · L.best :"))
        self.assertNotIn("mentions", lines[0])
        self.assertTrue(lines[1].startswith("2. decl:L.next"))

    def test_names_the_reference_already_uses_are_skipped_and_empty_is_safe(self):
        parsed = {
            "library": [self.record("L.used", 9), self.record("L.new", 8)],
            "source": [{"name": "L.used"}],
            "dependency": [],
        }
        lines = context._library_section(parsed)
        self.assertFalse(any("L.used" in line for line in lines))
        self.assertIn("1. decl:L.new", lines[0])
        self.assertEqual(context._library_section({}), [])
        self.assertEqual(
            context._library_section({"library": [self.record("L.used", 9)], "source": [{"name": "L.used"}]}), []
        )

    def test_section_respects_line_and_character_budgets_and_is_shed_before_the_goals(self):
        parsed = {"library": [self.record(f"L.n{i}", 9 - i / 100, sig="L.n : " + "t " * 400) for i in range(60)]}
        lines = context._library_section(parsed)
        self.assertLessEqual(len(lines), context.LIMITS["library"])
        self.assertLessEqual(sum(len(line) + 1 for line in lines), context.LIMITS["library_budget"])
        self.assertTrue(all(len(line) < context.LIMITS["library_chars"] + 120 for line in lines))
        parts = [
            ("Head", ["keep"]),
            (context.template("packet/sections.titles.goals").strip(), ["goal"]),
            (context.LIBRARY_TITLE, lines),
            (context.EARLIER_TITLE, ["e " * 100] * 10),
        ]
        text = context._fit(parts, 3000)
        self.assertLessEqual(len(text), 3000)
        self.assertIn("goal", text)

    def test_counter_facts_match_the_pinned_counter(self):
        from arena.engine import ROOT as root

        if not (root / "vendor/lean-refactor").is_dir():
            self.skipTest("pinned counter not vendored")
        from arena.engine import _proof_length

        head = "theorem t : True"
        self.assertEqual(_proof_length(head + " := by\n  exact ⟨a, b⟩"), 7)  # ⟨ a , b ⟩ are five tokens
        self.assertEqual(_proof_length(head + " := by\n\n  trivial\n"), 2)  # blank lines and indentation are free
        self.assertEqual(_proof_length(head + " := by\n \t trivial"), 3)  # a tab is a token
        self.assertEqual(_proof_length(head + " := fun x => x.1 -- note"), 4)  # `=>` once, comment removed


class LocalSheddingTests(unittest.TestCase):
    GOALS = context.template("packet/sections.titles.goals").strip()

    def parts(self, locals_=76, goals=12, library=30):
        return [
            ("Head", ["keep head"]),
            ("Reference proof", ["ref " + "r" * 100] * 3),
            ("Source-named declarations", ["used " + "u" * 100] * 3),
            ("Elaborated proof dependencies", ["dep " + "d" * 100] * 3),
            ("Environment", ["env " + "e" * 100] * 3),
            (self.GOALS, [f"goal {i} " + "g" * 200 for i in range(goals)]),
            (context.LOCAL_TITLE, ["Hdr local names"] + [f"loc{i} : " + "l" * 200 for i in range(locals_)]),
            (context.LIBRARY_TITLE, [f"lib{i} " + "b" * 200 for i in range(library)]),
        ]

    def count(self, text, prefix):
        return sum(1 for line in text.split("\n") if line.startswith(prefix))

    def test_under_budget_packet_is_untouched(self):
        parts = self.parts()
        text = context._fit(parts, 10**7)
        self.assertEqual(self.count(text, "loc"), 76)
        self.assertEqual(self.count(text, "lib"), 30)
        self.assertEqual(self.count(text, "goal "), 12)

    def test_all_locals_are_shed_before_any_library_line(self):
        parts = self.parts(goals=context.GOALS_FLOOR)
        keep = [p for p in parts if p[0] != context.LOCAL_TITLE]
        limit = len(context._fit(keep, 10**7))
        text = context._fit(parts, limit)
        self.assertEqual(self.count(text, "loc"), 0)
        self.assertEqual(self.count(text, "lib"), 30)
        self.assertEqual(self.count(text, "goal "), context.GOALS_FLOOR)
        for required in ("keep head", "ref ", "used ", "dep ", "env "):
            self.assertIn(required, text)

    def test_remaining_goals_shed_after_locals_and_library(self):
        parts = self.parts(goals=context.GOALS_FLOOR)
        keep = [p for p in parts if p[0] not in (context.LIBRARY_TITLE, context.LOCAL_TITLE)]
        text = context._fit(parts, len(context._fit(keep, 10**7)) - 600)
        self.assertEqual(self.count(text, "lib"), 0)
        self.assertEqual(self.count(text, "loc"), 0)
        self.assertLess(self.count(text, "goal "), context.GOALS_FLOOR)
        self.assertGreaterEqual(self.count(text, "goal "), 1)

    def test_required_sections_are_never_shed(self):
        parts = self.parts()
        required = [
            p
            for p in parts
            if p[0]
            in ("Head", "Reference proof", "Source-named declarations", "Elaborated proof dependencies", "Environment")
        ]
        with self.assertRaisesRegex(ValueError, "Required kickoff inventory exceeds packet budget"):
            context._fit(parts, len(context._fit(required, 10**7)) - 1)


class LocalContextLeanTests(unittest.TestCase):
    def test_context_lean_does_not_bind_ext_as_a_pattern_variable(self):
        # `ext` is a reserved token in ArkLib's environment, so `(ext, entries)` is an unsupported pattern.
        text = (ROOT / "arena/lean/context.lean").read_text(encoding="utf-8")
        code = "\n".join(line for line in text.split("\n") if not line.strip().startswith("--"))
        self.assertNotIn("for (ext,", code)
        self.assertNotRegex(code, r"\(ext\s*,")
        self.assertIn("`ext`", text)  # the explaining comment stays
        self.assertIn("for (extName, entries)", text)


class TruncationTests(unittest.TestCase):
    def test_over_budget_packets_shed_the_lowest_priority_entries_deterministically(self):
        big = [f"entry {i} " + "x" * 200 for i in range(40)]
        parts = [
            ("Head", ["keep me"]),
            (context.template("packet/sections.titles.goals").strip(), big[:10]),
            ("Signatures of constants the reference proof mentions", big[:20]),
            (context.EARLIER_TITLE, big),
        ]
        first = context._fit(parts, 6000)
        second = context._fit(parts, 6000)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 6000)
        self.assertIn("keep me", first)
        self.assertIn("entry 0 ", first)
        self.assertNotIn("entry 39 ", first)


def _live_packet(test):
    def wrapped(self):
        if type(self).text is None:
            type(self).text = context.render_packet(NAME)
        return test(self)

    wrapped.__name__ = test.__name__
    return slow(LEAN(wrapped))


class FixturePacketTests(unittest.TestCase):
    text = None

    @_live_packet
    def test_statement_types_are_defined_with_constructors(self):
        self.assertIn("Core.UpdateStates.update_some", self.text)
        self.assertIn("Core.InitStates.init_some", self.text)
        self.assertIn("Imperative.SemanticStore", self.text)

    @_live_packet
    def test_earlier_lemmas_and_used_constants_include_namespaced_and_library_names(self):
        self.assertIn("Core.InitStatesSomeMonotone", self.text)
        self.assertIn("List.unzip_zip", self.text)
        self.assertIn("Core.updatedStatesInit [theorem]", self.text)

    @_live_packet
    def test_relevant_lemmas_are_ranked_ahead_of_nearby_unrelated_ones(self):
        ranked = [e["item"]["name"] for e in context.score_earlier(context.lean_context(NAME))]
        for name in ("Core.updatedStatesUpdate", "Core.updatedStatesDefMonotone", "Core.updatedStatesComm"):
            self.assertIn(f"decl:{name} ", self.text)
            self.assertLess(ranked.index(name), 12, name)
        self.assertIn(context.EARLIER_TITLE, self.text)

    @_live_packet
    def test_pinned_constant_index_keeps_elaborated_constructor_queryable(self):
        indexed = context.constant_index(
            context.lean_context(NAME), name="Exists.intro", kind="constructor", origin="elaborated-proof"
        )
        self.assertEqual(len(indexed), 1)

    @_live_packet
    def test_cached_constant_ranges_match_one_based_source_coordinates(self):
        indexed = context.constant_index(context.lean_context(NAME), name="Core.updatedStates")
        self.assertEqual(len(indexed), 1)
        entry = indexed[0]
        source = campaign.source_range(NAME, "decl:Core.updatedStates")
        self.assertEqual((entry["start_line"], entry["end_line"]), (source["line"], source["end_line"]))

    @_live_packet
    def test_tags_classify_generated_instance_core_and_project_constants(self):
        tags = {item["name"]: item["tag"] for item in context.lean_context(NAME)["constant"]}
        self.assertTrue(all(tag == "generated" for name, tag in tags.items() if "_simp_" in name))
        self.assertEqual(tags.get("Eq.symm", "core"), "core")
        self.assertEqual(tags.get("Core.updatedStatesInit"), "helper")
        self.assertNotIn("of_eq_true\n", self.text)

    @_live_packet
    def test_pins_and_imports_are_stated_once(self):
        self.assertEqual(self.text.count("Available imports"), 1)
        self.assertEqual(self.text.count("Lean toolchain and source revisions"), 1)

    @_live_packet
    def test_source_occurrences_can_appear_in_both_statement_and_proof(self):
        items = [item for item in context.lean_context(NAME)["source"] if item["name"] == "Core.updatedStates"]
        self.assertEqual({item["origin"] for item in items}, {"statement", "proof"})

    @_live_packet
    def test_goal_steps_prices_and_exchange_rates_are_present(self):
        from arena.engine import problem, versions
        from arena.scoring import exchange_rates

        rates = exchange_rates(NAME, len(versions(problem(NAME))))
        self.assertIn("before s1", self.text)
        self.assertIn("⊢ ∃ σ₁", self.text)
        self.assertIn("| step | lines | tokens |", self.text)
        self.assertIn(str(rates["points_per_token"]), self.text)
        self.assertIn(str(rates["points_per_100_heartbeats"]), self.text)
        self.assertIn(str(rates["points_per_lost_version"]), self.text)

    @_live_packet
    def test_packet_is_deterministic_bounded_and_strategy_free(self):
        self.assertEqual(self.text, context.render_packet(NAME))
        self.assertLessEqual(len(self.text), context.MAX_PACKET_CHARS + 2)
        for phrase in DENYLIST:
            self.assertNotIn(phrase, self.text, phrase)

    def test_v8_packet_nested_hotspot_and_retrieval(self):
        import json
        from pathlib import Path
        from unittest.mock import patch

        from arena.engine import problem
        from arena.steps import split_steps

        ski = "Cslib.SKI.parallelReduction_diamond"
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "agent_text" / "ski-context.json").read_text()
        )
        try:
            profile = context.reference_profile(ski, cache_only=True)
        except ValueError:
            profile = {}
        if not profile:
            profile = json.loads(
                (Path(__file__).parent / "fixtures" / "agent_text" / "ski-profile.json").read_text()
            )
        with patch.object(context, "cached_context", return_value=fixture), patch.object(
            context, "reference_profile", return_value=profile
        ):
            packet = context.render_packet(ski, cache_only=True)
        nested = max(
            (entry for entry in profile["entries"] if int(entry.get("depth") or 0) > 0 and entry.get("hb")),
            key=lambda entry: int(entry["hb"]),
        )
        parent = next(
            step
            for step in split_steps(problem(ski)["src"])
            if step.first_line <= nested["proof_line"] <= step.last_line
        )
        self.assertIn(f"parent {parent.id} lines {parent.first_line}-{parent.last_line}", packet)
        self.assertIn(f"range {nested['proof_line']}-{nested.get('end_proof_line') or nested['proof_line']}", packet)
        self.assertIn("Proof total (not a step)", packet)
        self.assertNotIn("| total |", packet)
        self.assertNotIn("pts_if_gone", packet)
        self.assertNotIn("self_hb |", packet)
        self.assertIn("not tied to any line", packet)
        self.assertNotIn("tokens missing", packet)
        self.assertIn("zero (measured), not missing", packet)
        self.assertIn("Full detail: read(node=n1, view=tree:2) proof=reference", packet)
        self.assertIn("Not a splice target", packet)
        self.assertIn("Inclusive costs are not summed", packet)
        self.assertNotRegex(packet, r"source revision [0-9a-f]")
        self.assertIn("whole-structure theorem", packet)
        self.assertIn(str(profile["measured_total"]), packet)


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
            sources = {
                "context": context.LEAN_FILE.read_text()
                .replace("@@ROOTS@@", '"Strata"')
                .replace("@@TARGET@@", context._lean_name(NAME)),
                "profile": profiler.preamble(profiler.MAX_DEPTH),
            }
            for label, inserted in sources.items():
                text = built["text"][: built["offset"]] + inserted + built["text"][built["offset"] :]
                result = run_lean(row, built["path"], text)
                if result is None:
                    self.fail(f"{label} wrapper timed out on {version}")
                _code, output = result
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
        self.assertIn(context.template("packet/sections.titles.source").strip(), self.packet)
        self.assertIn(context.template("packet/sections.titles.dependencies").strip(), self.packet)

    def test_the_library_lemma_that_decides_the_row_is_ranked_in_the_packet(self):
        winner = "Continuous.integral_pos_of_hasCompactSupport_nonneg_nonzero"
        ranked = [item["name"] for item in self.context["library"]]
        self.assertLess(ranked.index(winner), 10)
        self.assertIn(context.LIBRARY_TITLE, self.packet)
        self.assertIn(f"decl:{winner} ", self.packet)
        self.assertFalse(self.context["library_scan"][0]["truncated"])

    def test_constant_index_and_packet_are_stable_for_the_same_pin(self):
        all_constants = context.constant_index(self.context)
        self.assertTrue(all_constants)
        self.assertTrue(all(item["origin"] == "elaborated-proof" and item.get("kind") for item in all_constants))
        self.assertEqual(self.packet, context.render_packet(self.name))


class ScopeTests(unittest.TestCase):
    """The packet's scope section is syntactic, so it works for every corpus."""

    def test_open_and_variable_of_closed_scopes_are_dropped(self):
        from arena.context import scope_lines

        source = (
            "import X\n/-! notes\nopen Fake -/\nnamespace A\nopen B\nsection S\nvariable (x : Nat)\n"
            "  (y : Nat)\nopen C in\ntheorem t : True := trivial\nend S\nvariable {Y} [Foo Y]\n"
            "open D in\n"
        )
        self.assertEqual(scope_lines(source), ["namespace A", "open B", "variable {Y} [Foo Y]", "open D in"])

    def test_stale_open_in_does_not_leak(self):
        from arena.context import scope_lines

        self.assertEqual(scope_lines("open E in\ntheorem u : True := trivial\n\n"), ["(root namespace)"])


if __name__ == "__main__":
    unittest.main()


class RouteRuleAgreementTests(unittest.TestCase):
    """The packet, compile description and SKILL.md agree on the current workflow."""

    def test_agent_text_does_not_claim_routes_use_compiled_fingerprints(self):
        sources = {
            "packet": ROOT / "agent-text" / "packet" / "task.md",
            "tool": ROOT / "agent-text" / "tools" / "compile.yaml",
            "skill": ROOT / "agent-text" / "skill" / "SKILL.md",
        }
        for label, path in sources.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(label):
                self.assertNotIn("Routes are fingerprinted from complete proofs", text)
                self.assertNotIn("routes are fingerprinted from complete proofs", text)


class ProfileSectionTests(unittest.TestCase):
    SRC = "theorem foo : P := by\n  intro h\n  have := foo h\n  exact bar"
    PROF: ClassVar[dict] = {
        "line_profile": [
            {"proof_line": 2, "self_hb": 5, "tokens": 2, "text": "intro h"},
            {"proof_line": 3, "self_hb": 80, "tokens": 5, "text": "have := foo h"},
            {"proof_line": 4, "self_hb": 0, "tokens": 2, "text": "exact bar"},
        ],
        "measured_total": 300,
        "profiled_total": 85,
        "unattributed": 215,
    }

    def test_lines_total_and_remainder_are_reported_with_own_name_references(self):
        body = context._profile_section(self.PROF, self.SRC, "A.foo")
        text = "\n".join(body)
        self.assertIn("line 3 · 80 self hb · 5 tokens", text)
        self.assertNotIn("line 4 ·", text)  # zero-cost lines are not listed
        self.assertIn("Measured 300", text)
        self.assertIn("85 are attributed", text)
        self.assertIn("215 (71.7%)", text)
        self.assertIn("proof lines 3", text)  # the header line mentioning the name is not a reference

    def test_no_own_name_reference_means_no_reference_line(self):
        body = context._profile_section(self.PROF, "theorem foo : P := by\n  exact bar", "A.foo")
        self.assertEqual(len(body), 3)
        self.assertNotIn("refers to its own", "\n".join(body))

    def test_missing_profile_gives_no_section(self):
        self.assertEqual(context._profile_section({}, self.SRC, "A.foo"), [])

    def test_ski_packet_has_definitions_and_the_unattributed_remainder(self):
        ski = "Cslib.SKI.parallelReduction_diamond"
        try:
            packet = context.render_packet(ski, cache_only=True)
        except ValueError:
            self.skipTest("SKI packet cache is not provisioned")
        self.assertIn("Cslib.SKI.ParallelReduction.red_S", packet)
        self.assertIn("Relation.Diamond", packet)
        # The cached profile is re-measured when a campaign certifies packets; heartbeats vary by a few units.
        self.assertRegex(packet, r"Measured \d+ heartbeats; \d+ are attributed to lines")
        self.assertRegex(packet, r"\d+ \(\d+\.\d%\) are not tied to any line")
        self.assertIn("proof lines 11, 12", packet)
        self.assertLessEqual(len(packet), context.MAX_PACKET_CHARS)
