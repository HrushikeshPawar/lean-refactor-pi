"""Kernel-term extraction for route fingerprints: parsing and file assembly offline, the Lean read behind `slow`."""

import json
import unittest
from unittest.mock import patch

from arena import route_features
from tests.slow import slow


class ParsingTests(unittest.TestCase):
    def test_records_are_keyed_by_tag_and_other_output_is_ignored(self):
        output = "warning: unused\nARENA_ROUTE " + json.dumps({"tag": "a", "ok": True, "lemmas": ["x"]}) + \
            "\nARENA_ROUTE not json\nARENA_ROUTE " + json.dumps({"tag": "b", "ok": False, "error": "e"}) + "\n"
        found = route_features.parse_features(output)
        self.assertEqual(sorted(found), ["a", "b"])
        self.assertEqual(found["a"]["lemmas"], ["x"])

    def test_short_name_skips_open_and_namespace(self):
        self.assertEqual(route_features.short_name("open A in theorem B.c {x : Nat} : x = x"), "c")
        self.assertEqual(route_features.short_name("lemma foo' (h : p) : q"), "foo'")

    def test_extract_reports_a_timeout_and_a_missing_record_per_proof(self):
        row = {"name": "T"}
        with patch.object(route_features, "problem", return_value=row), \
                patch.object(route_features, "extraction_text", return_value=("p", "text", 0)), \
                patch.object(route_features, "run_lean", return_value=None):
            self.assertEqual(route_features.extract("T", {"a": "x"})["a"]["error"], "timeout")
        with patch.object(route_features, "problem", return_value=row), \
                patch.object(route_features, "extraction_text", return_value=("p", "text", 0)), \
                patch.object(route_features, "run_lean", return_value=(1, "f.lean:1:0: error: boom")):
            result = route_features.extract("T", {"a": "x"})["a"]
            self.assertFalse(result["ok"])
            self.assertIn("boom", result["error"])

    def test_extractor_source_defines_the_command(self):
        text = route_features.LEAN_FILE.read_text()
        self.assertIn('elab "arena_route "', text)
        self.assertIn("ARENA_ROUTE", text)


@slow
class LeanTests(unittest.TestCase):
    def test_the_original_reads_as_induction_on_update_states_and_synonyms_agree(self):
        from arena.engine import problem

        row = problem("Core.InitsUpdatesComm")
        synonym = row["src"].replace("exists (updatedStates σ ks' vs')", "refine ⟨updatedStates σ ks' vs', ?_⟩")
        self.assertNotEqual(synonym, row["src"])
        got = route_features.extract("Core.InitsUpdatesComm", {"orig": row["src"], "syn": synonym}, timeout=600)
        self.assertTrue(got["orig"]["ok"], got["orig"])
        self.assertIn("rec:Core.UpdateStates", got["orig"]["recursion"])
        from arena import routes
        score = routes.similarity(routes.fingerprint(row["src"], features=got["orig"]),
                                  routes.fingerprint(synonym, features=got["syn"]))
        self.assertGreaterEqual(score, 0.9)


if __name__ == "__main__":
    unittest.main()
