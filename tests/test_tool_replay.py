"""Sanitized replay checks for the valid-intent errors seen in the v5 Pi runs."""

import json
import unittest
from pathlib import Path

from arena import campaign


FIXTURE = Path(__file__).parent / "fixtures" / "proof_tool_replay.json"


class ProofToolReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())

    def test_fixture_covers_all_historical_error_calls_without_proof_bodies(self):
        fixture = self.fixture
        calls = fixture["calls"]
        self.assertEqual((fixture["run_count"], fixture["error_call_count"]), (14, 32))
        self.assertEqual(len(calls), fixture["error_call_count"])
        self.assertEqual(len({call["run"] for call in calls}), fixture["run_count"])
        self.assertTrue(all("proof" not in call and "proof" not in call["request"] for call in calls))
        preventable = [call for call in calls if call["preventable"]]
        self.assertEqual(len(preventable), 16)
        self.assertTrue(all(call["replay"] != "preserve_expected_error" for call in preventable))
        genuine = [call for call in calls if not call["preventable"]]
        self.assertEqual(len(genuine), 16)
        self.assertTrue(all(call["replay"] == "preserve_expected_error" for call in genuine))
        sources = [call for call in calls if call["old_tool"] == "arena_source"]
        self.assertTrue(all(call["old_request"]["path"] == call["request"]["handle"]
                            for call in sources))

    def test_legacy_path_aliases_replay_with_exact_pinned_line_ranges(self):
        calls = [call for call in self.fixture["calls"]
                 if call["replay"] == "resolve_pinned_path_alias"]
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

    def test_legacy_declaration_and_proof_tool_names_map_to_valid_intent(self):
        calls = self.fixture["calls"]
        declarations = [call for call in calls if call["replay"] == "map_symbol_to_items"]
        self.assertEqual(len(declarations), 1)
        self.assertEqual(declarations[0]["old_tool"], "mcp__arena_lean__lean_declaration")
        self.assertEqual(declarations[0]["legacy_tool"], "arena_declaration")
        self.assertEqual(declarations[0]["old_request"], {"symbol": "Imperative.UpdateState"})
        self.assertEqual(declarations[0]["tool"], "arena_declarations")
        self.assertEqual(declarations[0]["request"], {"items": ["Imperative.UpdateState"]})

        routed = [call for call in calls if call["replay"] == "route_draft_to_probe"]
        self.assertEqual(len(routed), 2)
        self.assertTrue(all(call["tool"] == "arena_probe" for call in routed))
        for call in routed:
            self.assertEqual(call["old_tool"], "arena_evaluate")
            self.assertIn(call["request"]["draft_form"], {"by_body", "complete_or_other"})

    def test_historical_proof_shapes_normalize_against_the_exact_statement(self):
        calls = [call for call in self.fixture["calls"]
                 if call["replay"] == "normalize_proof_body"]
        self.assertEqual(len(calls), 7)
        for call in calls:
            with self.subTest(run=call["run"], theorem=call["theorem"]):
                statement = campaign.problem(call["theorem"])["statement"]
                if call["request"]["draft_form"] == "complete_with_leading_whitespace":
                    draft = "\n" + statement + " := by\n  trivial"
                    expected = statement + " := by\n  trivial"
                else:
                    draft = "\nby\n  trivial"
                    expected = statement + " := by\n  trivial"
                self.assertEqual(campaign.normalize_draft(call["theorem"], draft), expected)


if __name__ == "__main__":
    unittest.main()
