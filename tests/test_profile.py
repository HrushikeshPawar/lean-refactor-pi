import unittest
from unittest.mock import patch

from arena import profile as profiler
from arena.engine import ROOT, _proof_length, problem

OUTPUT = """ARENA_PROFILE 120 2 0 120 10
ARENA_PROFILE 121 4 1 121 30
ARENA_PROFILE 122 4 1 122 20
ARENA_PROFILE 121 2 0 122 55
ARENA_PROFILE 123 2 0 123 5
ARENA_PROFILE 123 2 0 123 7
ARENA_PROFILE_TOTAL 80
"""


class AggregationTests(unittest.TestCase):
    def setUp(self):
        # 100 lines of instrumentation sit before the theorem, which starts at file line 10.
        self.records, self.total = profiler.parse_profile(OUTPUT, shift=100, start_line=10)

    def test_lines_map_back_to_the_candidate_file(self):
        self.assertEqual(self.total, 80)
        first = self.records[0]
        self.assertEqual((first["file_line"], first["proof_line"], first["depth"]), (20, 11, 0))
        self.assertEqual((first["end_file_line"], first["end_proof_line"]), (20, 11))

    def test_repeated_calls_on_one_line_are_summed(self):
        repeated = next(r for r in self.records if r["file_line"] == 23)
        self.assertEqual((repeated["hb"], repeated["calls"]), (12, 2))

    def test_self_cost_excludes_nested_tactics(self):
        profiler.attribute(self.records)
        block = next(r for r in self.records if r["file_line"] == 21 and r["depth"] == 0)
        self.assertEqual((block["hb"], block["self_hb"]), (55, 5))

    def test_summary_reports_totals_shares_and_cumulative_top_costs(self):
        lines = [f"line {i}" for i in range(1, 40)]
        summary = profiler.summarize(self.records, lines, measured=100, instrumented=80)
        self.assertEqual(summary["profiled_total"], 10 + 55 + 12)
        self.assertEqual(summary["unattributed"], 100 - 77)
        top = summary["top_self_cost"]
        self.assertEqual(top[0]["self_hb"], 30)
        self.assertEqual(top[0]["cumulative_share_pct"], 30.0)
        self.assertGreater(top[1]["cumulative_share_pct"], top[0]["cumulative_share_pct"])
        nested = next(e for e in summary["entries"] if e["depth"] == 1 and e["lines"] == "12")
        self.assertEqual(nested["share_pct"], 30.0)
        self.assertNotIn("recommend", str(summary).lower())

    def test_hotspots_rank_full_self_costs_and_include_both_line_coordinates(self):
        tokens = {11: 4, 12: 7, 13: 2}
        summary = profiler.summarize(self.records, [f"line {i}" for i in range(1, 40)],
                                     measured=100, instrumented=80, line_tokens=tokens,
                                     reference_tokens=130, reference_heartbeats=100, proof_tokens=13)
        self.assertTrue(summary["token_attribution_available"])
        self.assertEqual(summary["line_tokens_total"], 13)
        hotspot = summary["hotspots"][0]
        self.assertEqual((hotspot["proof_line"], hotspot["file_line"], hotspot["end_file_line"]), (12, 21, 22))
        self.assertEqual(hotspot["self_hb"], 35)
        self.assertIn("not predicted savings", summary["hotspot_label"])
        self.assertEqual({span["column"] for span in hotspot["tactic_spans"]}, {2, 4})
        self.assertEqual(summary["line_profile"], [])

    @staticmethod
    def _record(proof_line, end_proof_line, depth, self_hb):
        return {"file_line": proof_line + 9, "end_file_line": end_proof_line + 9, "proof_line": proof_line,
                "end_proof_line": end_proof_line, "depth": depth, "column": 2 + 2 * depth, "hb": self_hb,
                "self_hb": self_hb, "calls": 1}

    def _hotspots(self, records, tokens):
        with patch.object(profiler, "attribute"):
            return profiler.summarize(records, [f"line {i}" for i in range(1, 40)], measured=100, instrumented=80,
                                      line_tokens=tokens, reference_tokens=100, reference_heartbeats=100,
                                      proof_tokens=sum(tokens.values()), file_start_line=10)["hotspots"]

    def test_ranked_candidates_carry_every_proof_token(self):
        tokens = {1: 5, 2: 6, 3: 7, 4: 1, 5: 9, 7: 2}
        records = [self._record(2, 4, 0, 10), self._record(3, 3, 1, 5)]
        hotspots = self._hotspots(records, tokens)
        self.assertEqual(sum(item["tokens"] for item in hotspots), sum(tokens.values()))

    def test_multi_line_tactic_collects_its_continuation_lines(self):
        hotspots = self._hotspots([self._record(2, 4, 0, 10), self._record(3, 3, 1, 5)],
                                  {1: 5, 2: 6, 3: 7, 4: 1})
        outer = next(item for item in hotspots if item["proof_line"] == 2)
        inner = next(item for item in hotspots if item["proof_line"] == 3)
        self.assertEqual((outer["tokens"], outer["self_hb"], outer["end_proof_line"], outer["end_file_line"]),
                         (7, 10, 4, 13))
        self.assertEqual(inner["tokens"], 7)  # the innermost span owns its own line
        self.assertEqual((inner["end_proof_line"], inner["self_hb"]), (3, 5))

    def test_uncovered_line_is_a_token_only_entry(self):
        hotspots = self._hotspots([self._record(2, 4, 0, 10)], {1: 5, 2: 6, 7: 2})
        loose = next(item for item in hotspots if item["proof_line"] == 7)
        self.assertEqual((loose["self_hb"], loose["tokens"], loose["file_line"], loose["tactic_spans"]),
                         (0, 2, 16, []))
        self.assertEqual(next(item for item in hotspots if item["proof_line"] == 1)["tokens"], 5)

    def test_token_attribution_is_unavailable_when_counts_do_not_reconcile(self):
        summary = profiler.summarize(self.records, [f"line {i}" for i in range(1, 40)],
                                     measured=100, instrumented=80, line_tokens={11: 3})
        self.assertFalse(summary["token_attribution_available"])
        self.assertIsNone(summary["line_tokens_total"])
        self.assertEqual(summary["hotspots"], [])

    def test_competition_tokenizer_attribution_reconciles_on_source_lines(self):
        proof = "theorem sample : True := by\n  exact True.intro\n"
        counts = profiler._line_token_counts(proof, _proof_length(proof))
        self.assertEqual(counts, {1: 1, 2: 2})
        self.assertEqual(sum(counts.values()), _proof_length(proof))


class DegradationTests(unittest.TestCase):
    row = {"name": "T", "statement": "theorem t : True", "file_path": "T.lean"}

    def fake_instrumented(self, row, proof, version, commit, depth):
        if depth:
            raise ValueError("instrumented compile failed: boom")
        records, total = profiler.parse_profile("ARENA_PROFILE 5 2 0 5 7\nARENA_PROFILE_TOTAL 7", 0, 1)
        return records, total, {"text": "a\nb\nc\nd\ne\n", "start_line": 1}, ""

    def test_failed_instrumentation_degrades_to_the_outermost_tactics(self):
        with patch.object(profiler, "problem", return_value=self.row), \
             patch.object(profiler, "measure_version", return_value=("v1", "c")), \
             patch.object(profiler, "versions", return_value=[("v1", "c")]), \
             patch.object(profiler, "exchange_rates", return_value={"reference_tokens": 2,
                                                                      "reference_heartbeats": 9}), \
             patch.object(profiler, "_instrumented", side_effect=self.fake_instrumented):
            result = profiler.profile("T", "theorem t : True := by\n  trivial", measured=9)
        self.assertEqual(result["granularity"], "top_level")
        self.assertIn("degraded", result["note"])
        self.assertEqual(result["measured_total"], 9)

    def test_non_compiling_and_sorry_proofs_get_one_line_actionable_errors(self):
        with patch.object(profiler, "problem", return_value=self.row), \
             patch.object(profiler, "measure_version", return_value=("v1", "c")), \
             patch.object(profiler, "versions", return_value=[("v1", "c")]), \
             patch.object(profiler, "_instrumented", side_effect=ValueError("instrumented compile failed: x")), \
             patch.object(profiler, "compile_version", return_value={"passed": False,
                          "error_headlines": ["line 3 (proof line 2): unsolved goals"]}):
            with self.assertRaisesRegex(ValueError, "does not compile.*unsolved goals"):
                profiler.profile("T", "theorem t : True := by\n  skip")
            with self.assertRaisesRegex(ValueError, "without sorry"):
                profiler.profile("T", "theorem t : True := by\n  sorry")


@unittest.skipUnless((ROOT / "workspaces/physlib-v4.32.0").is_dir(), "PhysLib fixture is not provisioned")
class PinnedPhyslibProfileTests(unittest.TestCase):
    def test_profile_lines_reconcile_and_keep_source_coordinates(self):
        name = "fundamental_theorem_of_variational_calculus'"
        row = problem(name)
        result = profiler.profile(name, row["src"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["token_attribution_available"])
        self.assertEqual(result["line_tokens_total"], result["tokens"])
        self.assertEqual(result["line_profile"][0]["file_line"], row["start_line"])
        self.assertEqual([item["proof_line"] for item in result["line_profile"]],
                         sorted(item["proof_line"] for item in result["line_profile"]))
        self.assertLessEqual(len(result["hotspots"]), 10)
        costs = [item["baseline_cost_points"] for item in result["hotspots"]]
        self.assertEqual(costs, sorted(costs, reverse=True))
        spans = [span for line in result["line_profile"] for span in line["tactic_spans"]]
        self.assertTrue(any(span["depth"] > 0 for span in spans))
        self.assertTrue(any(span["end_file_line"] > span["file_line"] for span in spans))


if __name__ == "__main__":
    unittest.main()
