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


class CpuTests(unittest.TestCase):
    def write(self, root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_reads_the_fastest_core_and_the_package_temperature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "1800000\n")
            self.write(root, "devices/system/cpu/cpu1/cpufreq/scaling_cur_freq", "3800000\n")
            self.write(root, "class/thermal/thermal_zone0/type", "acpitz\n")
            self.write(root, "class/thermal/thermal_zone0/temp", "20000\n")
            self.write(root, "class/thermal/thermal_zone1/type", "x86_pkg_temp\n")
            self.write(root, "class/thermal/thermal_zone1/temp", "77000\n")

            self.assertEqual(lean_bench.read_cpu(root), {"mhz": 3800.0, "temp_c": 77.0})

    def test_a_machine_without_the_files_reports_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(lean_bench.read_cpu(Path(directory)), {"mhz": None, "temp_c": None})

    def test_summary_takes_median_and_lowest_clock_and_hottest_temperature(self):
        samples = [{"mhz": 3800.0, "temp_c": 70.0}, {"mhz": 3000.0, "temp_c": 81.0}, {"mhz": 3600.0, "temp_c": None}]

        self.assertEqual(lean_bench.summarise_cpu(samples), {"mhz_p50": 3600.0, "mhz_min": 3000.0, "temp_max_c": 81.0})
        self.assertEqual(lean_bench.summarise_cpu([]), {"mhz_p50": None, "mhz_min": None, "temp_max_c": None})

    def test_a_clock_well_below_the_baseline_is_named(self):
        def result(mhz):
            cpu = {"mhz_p50": mhz, "mhz_min": mhz, "temp_max_c": 80.0} if mhz else None
            return {"rows": {"putnam": {"v4.25.0": {"cpu": cpu}}}}

        self.assertEqual(lean_bench.cpu_speed_warnings(result(3800.0), result(3500.0)), [])
        warnings = lean_bench.cpu_speed_warnings(result(3800.0), result(3000.0))
        self.assertEqual(len(warnings), 1)
        self.assertIn("putnam | v4.25.0 | CPU clock 3000 MHz vs 3800 MHz", warnings[0])
        self.assertEqual(lean_bench.cpu_speed_warnings(result(None), result(3000.0)), [])


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

    def test_first_open_is_reported_but_not_gated(self):
        baseline, current = self.baseline(), self.current()
        baseline["rows"]["sample"]["v4.1.0"].update(open_cold_s=4.0, open_warm_s=4.0)
        current["rows"]["sample"]["v4.1.0"].update(open_cold_s=19.0, open_warm_s=5.1)

        self.assertEqual([item.figure for item in lean_bench.compare(baseline, current)], ["open_warm_s"])

    def test_cold_page_cache_is_named_only_when_first_open_is_much_slower(self):
        result = {
            "rows": {
                "putnam": {"v4.25.0": {"open_cold_s": 18.8, "open_warm_s": 5.1}},
                "core": {"v4.29.1": {"open_cold_s": 1.8, "open_warm_s": 1.85}},
            }
        }

        warnings = lean_bench.cold_cache_warnings(result)

        self.assertEqual(len(warnings), 1)
        self.assertIn("putnam | v4.25.0", warnings[0])

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


class GateTierTests(unittest.TestCase):
    """The quick gate measures three rows on their first toolchain; --full measures what the baseline holds."""

    def run_bench(self, arguments: list[str], baseline_rows: dict) -> tuple[int, list]:
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch

        from arena import engine
        from arena.cli import app

        listed = {"A": [("v1", "c1"), ("v2", "c2"), ("v3", "c3")], "B": [("v2", "c2")]}
        calls = []

        def measure(rows, versions, repeats, timeout, out):
            calls.append((list(rows), versions))
            return {"settings": {"repeats": repeats}, "rows": {}, "measurement_note": ""}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps({"schema": 1, "settings": {"repeats": 5}, "rows": baseline_rows}))
            arguments = [part.replace("BASELINE", str(path)) for part in arguments]
            with (
                redirect_stdout(StringIO()),
                patch.object(engine, "problem", lambda name: {"name": name}),
                patch.object(engine, "versions", lambda row: listed.get(row["name"], [("v1", "c1")])),
                patch.object(engine, "workspace", lambda row, version, commit: Path(directory)),
                patch.object(lean_bench, "measure", measure),
            ):
                status = app(["lean", "bench", *arguments, "--out", directory])
        return status, calls

    def test_full_measures_each_baseline_toolchain_once_and_nothing_else(self):
        baseline = {"A": {"v1": {"checks": {}}, "v3": {"checks": {}}}, "B": {"v2": {"checks": {}}}}
        status, calls = self.run_bench(["--full", "--compare", "BASELINE"], baseline)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [(["A", "B"], {"A": ["v1", "v3"], "B": ["v2"]})])

    def test_full_without_a_baseline_is_refused(self):
        status, calls = self.run_bench(["--full"], {})
        self.assertEqual((status, calls), (2, []))

    def test_the_quick_gate_measures_the_three_quick_rows_on_their_first_toolchain(self):
        status, calls = self.run_bench(["--compare", "BASELINE"], {})
        self.assertEqual(status, 0)
        self.assertEqual(calls, [(list(lean_bench.QUICK_ROWS), "first")])
