"""Lean speed gate against the recorded baseline.

Run once at the end of every ticket that touches Lean machinery: 08a, 08b, 08c, 08d, 10b, 12. Never in the fast suite.
"""

import os
import tempfile
import unittest
from pathlib import Path

from arena import engine
from arena.cli import lean_bench
from tests.slow import slow


class LeanSpeedGateTests(unittest.TestCase):
    @slow
    def test_current_lean_speed_matches_recorded_baseline(self):
        baseline = lean_bench.load_baseline(engine.ROOT / "benchmark/derived/lean-baseline.json")
        requested = os.environ.get("ARENA_GATE_ROWS")
        rows = [name.strip() for name in requested.split(",") if name.strip()] if requested else list(baseline["rows"])
        versions = {}
        available_rows = []
        for row_name in rows:
            if row_name not in baseline["rows"]:
                self.fail(f"row {row_name} is missing from the recorded Lean speed baseline")
            row = engine.problem(row_name)
            provisioned = [
                version
                for version, commit in engine.versions(row)
                if version in baseline["rows"][row_name] and engine.workspace(row, version, commit).is_dir()
            ]
            if provisioned:
                versions[row_name] = provisioned
                available_rows.append(row_name)
            elif requested:
                self.fail(f"no baseline workspaces are provisioned for requested row {row_name}")
        if not available_rows:
            self.skipTest("no Lean speed baseline workspaces are provisioned")
        with tempfile.TemporaryDirectory(prefix="arena-lean-gate-") as directory:
            current = lean_bench.measure(
                available_rows,
                versions,
                baseline["settings"]["repeats"],
                baseline["settings"].get("timeout", 180),
                Path(directory),
            )
        regressions = lean_bench.compare(baseline, current)
        self.assertEqual(regressions, [], lean_bench.format_report(regressions))
