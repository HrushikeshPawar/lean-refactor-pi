import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.slow import slow
from arena.campaign import run_dir
from arena.engine import ROOT
from arena.traces import PATCH_SHA256
from tests.pi_support import FAKE, NAME, PI_AVAILABLE
from tools import run_experiment_matrix as matrix


class PlanTests(unittest.TestCase):
    def test_exactly_one_factor_varies(self):
        specs = matrix.plan("thinking", ["low", "high"], "gpt-6-luna", "medium", "ab")
        self.assertEqual([s["run_id"] for s in specs], ["ab-thinking-low", "ab-thinking-high"])
        for spec in specs:
            self.assertEqual((spec["model"], spec["skill"]), ("gpt-6-luna", "on"))
        self.assertEqual({s["thinking"] for s in specs}, {"low", "high"})
        skill = matrix.plan("skill", ["on", "off"], "qwen3.8-flash", "high", "sk")
        self.assertEqual({s["model"] for s in skill}, {"qwen3.8-flash"})
        self.assertIn("--no-skill", matrix.command(skill[1], NAME, 0.1, []))
        self.assertNotIn("--no-skill", matrix.command(skill[0], NAME, 0.1, []))

    def test_bad_declarations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            matrix.plan("model", ["gpt-6-luna"], "gpt-6-luna", "high", "x")
        with self.assertRaisesRegex(ValueError, "invalid thinking"):
            matrix.plan("thinking", ["low", "wild"], "gpt-6-luna", "high", "x")
        with self.assertRaisesRegex(ValueError, "factor must be"):
            matrix.plan("cap", ["1", "2"], "gpt-6-luna", "high", "x")

    def test_matrix_defaults_to_the_three_dollar_per_problem_allowance(self):
        prefix = f"test-default-{uuid.uuid4().hex[:8]}"
        proc = subprocess.run(
            [sys.executable, "tools/run_experiment_matrix.py", "--theorem", NAME, "--prefix", prefix,
             "--factor", "thinking", "--values", "low,high", "--dry-run"],
            cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("cap $3 each", proc.stdout)

    def test_parallelism_follows_free_memory_and_never_exceeds_runs(self):
        gb = 1024 * 1024
        # 4.5 GB per run: Pi, the Lean server and one Lean process per lane.
        self.assertEqual(matrix.parallelism("auto", 5, 10 * gb), 2)
        self.assertEqual(matrix.parallelism("auto", 5, 14 * gb), 3)
        self.assertEqual(matrix.parallelism("auto", 2, 64 * gb), 2)
        self.assertEqual(matrix.parallelism("auto", 4, 1 * gb), 1)
        self.assertEqual(matrix.parallelism("3", 2, 0), 2)
        with self.assertRaises(ValueError):
            matrix.parallelism("0", 2, 0)

    def test_comparison_flags_mismatched_packets(self):
        row = {"run_id": "r", "factor": "thinking", "value": "low", "exit_code": 0, "packet_sha256": "aa",
               "summary": {"cost": {"spent_usd": 0.05, "requests": 7, "bookkeeping_and_rejected_pct": 3.0},
                           "progress": {"best": {"tokens": {"value": 90}}}, "evaluations": 4}}
        self.assertTrue(matrix.compare([row], "aa")["identical_packets"])
        report = matrix.compare([row], "bb")
        self.assertFalse(report["identical_packets"])
        self.assertEqual(report["runs"][0]["best_tokens"], 90)

    def test_matrix_uses_score_tokens_and_heartbeats_from_one_candidate(self):
        row = {"run_id": "r", "factor": "thinking", "value": "low", "exit_code": 0, "packet_sha256": "aa",
               "summary": {"cost": {}, "progress": {
                   "best": {"tokens": {"value": 90}, "heartbeats": {"value": 300}, "proxy": {"value": 62}},
                   "best_verified_candidate": {"candidate": "#3", "tokens": 70,
                                               "heartbeats": 800, "proxy": 60.5}}, "evaluations": 4}}
        result = matrix.compare([row], "aa")["runs"][0]
        self.assertEqual((result["best_candidate"], result["best_tokens"], result["best_heartbeats"],
                          result["best_proxy"]), ("#3", 70, 800, 60.5))


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class MatrixRunTests(unittest.TestCase):
    def test_runs_share_one_packet_and_differ_only_in_the_factor(self):
        prefix = f"test-{uuid.uuid4().hex[:8]}"
        work = Path(tempfile.mkdtemp())
        script = work / "script.json"
        script.write_text(json.dumps([{"text": "done"}] * 8))
        receipt = work / "preflight.json"
        receipt.write_text(json.dumps({"status": "pass", "patch_sha256": PATCH_SHA256,
                                       "models": {"gpt-6-luna": {"session_id": "s", "trace_ids": ["t"]}}}))
        env = {**os.environ, "ARENA_FAKE_SCRIPT": str(script), "ARENA_PREFLIGHT_RECEIPT": str(receipt)}
        try:
            proc = subprocess.run(
                [sys.executable, "tools/run_experiment_matrix.py", "--theorem", NAME, "--prefix", prefix,
                 "--factor", "thinking", "--values", "low,high", "--cap", "0.1", "--parallel", "2",
                 "--", "--no-mcp", "--no-langfuse", "--test-extension", str(FAKE)],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=600)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            report = json.loads((ROOT / "runs/pi-budget" / f"{prefix}-matrix" / "matrix.json").read_text())
            self.assertTrue(report["identical_packets"])
            self.assertEqual([r["thinking"] for r in report["runs"]], ["low", "high"])
            configs = [json.loads((run_dir(f"{prefix}-thinking-{v}") / "run-config.json").read_text())
                       for v in ("low", "high")]
            self.assertEqual(configs[0]["packet_sha256"], configs[1]["packet_sha256"])
            self.assertEqual([c["thinking"] for c in configs], ["low", "high"])
            self.assertTrue((ROOT / "runs/pi-budget" / f"{prefix}-matrix" / "matrix.txt").exists())
            clash = subprocess.run(
                [sys.executable, "tools/run_experiment_matrix.py", "--theorem", NAME, "--prefix", prefix,
                 "--factor", "thinking", "--values", "low,high", "--dry-run"],
                cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(clash.returncode, 0)
            self.assertIn("already exist", clash.stderr)
        finally:
            for value in ("low", "high"):
                shutil.rmtree(run_dir(f"{prefix}-thinking-{value}"), ignore_errors=True)
            shutil.rmtree(ROOT / "runs/pi-budget" / f"{prefix}-matrix", ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
