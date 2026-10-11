"""Pure behavior of the Lean speed benchmark and regression gate."""

import json
import tempfile
import unittest
from pathlib import Path

from arena.cli import lean_bench


def row(source: str = "theorem sample : True := by\n  trivial\n  exact True.intro") -> dict:
    statement, _body = source.split(" := by", 1)
    return {"name": "sample", "statement": statement, "src": source}


class SpliceTests(unittest.TestCase):
    def test_splices_after_first_and_last_body_line_and_keeps_statement(self):
        source = row()
        early = lean_bench.make_splice(source, "early", 3)
        late = lean_bench.make_splice(source, "late", 3)

        self.assertTrue(early.startswith(source["statement"]))
        self.assertIn("  trivial\n  -- bench splice early 3\n  exact", early)
        self.assertIn("  exact True.intro\n  -- bench splice late 3", late)
        self.assertNotEqual(early, late)

    def test_one_line_body_has_no_splice(self):
        self.assertIsNone(lean_bench.make_splice(row("theorem sample : True := by\n  trivial"), "early", 1))


class PlanAndSummaryTests(unittest.TestCase):
    def test_plan_is_deterministic_and_records_each_measurement_kind_per_repeat(self):
        plan = lean_bench.plan_checks(2)
        self.assertEqual(plan, lean_bench.plan_checks(2))
        self.assertEqual(
            plan[:8],
            [
                ("sorry", True),
                ("reference", True),
                ("edit", True),
                ("error", True),
                ("reference", False),
                ("splice_late", True),
                ("reference", False),
                ("splice_early", True),
            ],
        )
        self.assertEqual(
            [kind for kind, recorded in plan if recorded],
            ["sorry", "reference", "edit", "error", "splice_late", "splice_early"] * 2,
        )
        self.assertEqual(len(plan), 16)

    def test_check_summary_excludes_timed_out_measurements(self):
        summary = lean_bench.summarise_checks(
            [
                {"kind": "reference", "seconds": 1.0, "timed_out": False},
                {"kind": "reference", "seconds": 100.0, "timed_out": True},
                {"kind": "reference", "seconds": 3.0, "timed_out": False},
            ]
        )

        self.assertEqual(summary["reference"], {"n": 2, "p50": 2.0, "p95": 2.9, "max": 3.0, "timeouts": 1})

    def test_pss_summary_reports_idle_workers_and_peak(self):
        summary = lean_bench.summarise_pss([{10: 0.4, 11: 0.5}, {10: 0.8, 11: 0.6}], {10, 11})

        self.assertEqual(summary, {"workers_idle_gb": [0.4, 0.5], "worker_peak_gb": 0.8})


class ComparisonTests(unittest.TestCase):
    def baseline(self, p50: float = 1.0, p95: float = 1.0) -> dict:
        return {
            "settings": {"repeats": 2},
            "rows": {"sample": {"v4.1.0": {"checks": {"reference": {"p50": p50, "p95": p95}}}}},
        }

    def current(self, p50: float = 1.0, p95: float = 1.0) -> dict:
        return {
            "settings": {"repeats": 2},
            "rows": {"sample": {"v4.1.0": {"checks": {"reference": {"p50": p50, "p95": p95}}}}},
        }

    def test_relative_limits_and_absolute_noise_floor_both_apply(self):
        baseline = self.baseline()
        self.assertEqual(lean_bench.compare(baseline, self.current(p50=1.09)), [])
        self.assertEqual(lean_bench.compare(baseline, self.current(p50=1.11)), [])
        self.assertEqual(len(lean_bench.compare(self.baseline(10.0), self.current(10.9))), 0)
        self.assertEqual(len(lean_bench.compare(self.baseline(10.0), self.current(11.1))), 1)
        self.assertEqual(len(lean_bench.compare(self.baseline(p95=10.0), self.current(p95=11.9))), 0)
        self.assertEqual(len(lean_bench.compare(self.baseline(p95=10.0), self.current(p95=12.1))), 1)
        self.assertEqual(lean_bench.compare(baseline, self.current(p50=0.5, p95=0.5)), [])

    def test_missing_figures_are_named_and_missing_baseline_rows_are_rejected(self):
        current = self.current()
        current["rows"]["sample"]["v4.1.0"]["checks"].clear()
        regressions = lean_bench.compare(self.baseline(), current)

        self.assertEqual([item.figure for item in regressions], ["missing", "missing"])
        with self.assertRaisesRegex(ValueError, "other"):
            lean_bench.compare(self.baseline(), {"settings": {"repeats": 2}, "rows": {"other": {}}})

    def test_repeat_mismatch_is_rejected_and_report_names_regression(self):
        with self.assertRaisesRegex(ValueError, "repeats"):
            lean_bench.compare(self.baseline(), {**self.current(), "settings": {"repeats": 3}})
        regression = lean_bench.compare(self.baseline(10.0), self.current(12.0))[0]

        self.assertIn(
            "sample | v4.1.0 | reference.p50 | 10.00 -> 12.00 | +20% (limit +10%)",
            lean_bench.format_report([regression]),
        )

    def test_baseline_rows_not_requested_are_skipped_and_bad_schema_is_rejected(self):
        self.assertEqual(lean_bench.compare(self.baseline(), {"settings": {"repeats": 2}, "rows": {}}), [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps({"schema": 2}))
            with self.assertRaisesRegex(ValueError, "schema must be 1"):
                lean_bench.load_baseline(path)


if __name__ == "__main__":
    unittest.main()
