import unittest
from unittest.mock import patch

from arena import profile as profiler

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


class DegradationTests(unittest.TestCase):
    row = {"name": "T", "statement": "theorem t : True", "file_path": "T.lean"}

    def fake_instrumented(self, row, proof, version, commit, depth):
        if depth:
            raise ValueError("instrumented compile failed: boom")
        records, total = profiler.parse_profile("ARENA_PROFILE 5 2 0 5 7\nARENA_PROFILE_TOTAL 7", 0, 1)
        return records, total, {"text": "a\nb\nc\nd\ne\n"}, ""

    def test_failed_instrumentation_degrades_to_the_outermost_tactics(self):
        with patch.object(profiler, "problem", return_value=self.row), \
             patch.object(profiler, "versions", return_value=[("v1", "c")]), \
             patch.object(profiler, "_instrumented", side_effect=self.fake_instrumented):
            result = profiler.profile("T", "theorem t : True := by\n  trivial", measured=9)
        self.assertEqual(result["granularity"], "top_level")
        self.assertIn("degraded", result["note"])
        self.assertEqual(result["measured_total"], 9)

    def test_non_compiling_and_sorry_proofs_get_one_line_actionable_errors(self):
        with patch.object(profiler, "problem", return_value=self.row), \
             patch.object(profiler, "versions", return_value=[("v1", "c")]), \
             patch.object(profiler, "_instrumented", side_effect=ValueError("instrumented compile failed: x")), \
             patch.object(profiler, "compile_version", return_value={"passed": False,
                          "error_headlines": ["line 3 (proof line 2): unsolved goals"]}):
            with self.assertRaisesRegex(ValueError, "does not compile.*unsolved goals"):
                profiler.profile("T", "theorem t : True := by\n  skip")
            with self.assertRaisesRegex(ValueError, "without sorry"):
                profiler.profile("T", "theorem t : True := by\n  sorry")


if __name__ == "__main__":
    unittest.main()
