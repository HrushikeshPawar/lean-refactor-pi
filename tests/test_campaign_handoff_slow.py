"""Campaign handoff: one row to the next on the real Lean service, with the scripted model.

v7-check3 lost Binius, Core and SKI to memory: finished rows' toolchains stayed open (held for queued rows), a second
run was admitted beside a live one without a memory check, and memory refusals were counted as Lean faults. This test
drives a real two-row campaign (strata, then cslib) and checks that nothing of the first row is in memory when the
second starts, that both gates are healthy, and that nothing is left once the campaign ends.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from arena import lean_session
from arena.engine import ROOT
from tests.pi_support import FAKE, PI_AVAILABLE
from tests.slow import slow
from tests.test_runner import SPEND_90_PCT, cheap_tool

RUNS = ROOT / "runs/pi-budget"
FIRST, SECOND = "Core.InitsUpdatesComm", "Cslib.SKI.parallelReduction_diamond"
WORKSPACES = ("strata-v4.29.1", "cslib-v4.33.0-rc2")


@slow
@unittest.skipUnless(
    PI_AVAILABLE and all((ROOT / "workspaces" / name).is_dir() for name in WORKSPACES),
    "pi and the strata and cslib workspaces are required",
)
class CampaignHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix = f"test-handoff-{uuid.uuid4().hex[:6]}"
        cls.work = Path(tempfile.mkdtemp())
        cls.service = cls.work / "lean"
        script = cls.work / "script.json"
        # One turn spends into the final tenth of the $0.1 limit. A text-only turn does not end a run; the
        # scripted provider keeps answering "done" after the script until the actual-cost limit ends each run.
        steps = [cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), {"text": "done"}]
        script.write_text(json.dumps(steps))
        env = {
            **os.environ,
            "ARENA_FAKE_SCRIPT": str(script),
            "ARENA_FAKE_LOG": str(cls.work / "requests.jsonl"),
            lean_session.SERVICE_DIR_ENV: str(cls.service),
        }
        command = [
            sys.executable,
            "-m",
            "arena.cli",
            "campaign",
            "--prefix",
            cls.prefix,
            "--rows",
            f"{FIRST},{SECOND}",
            "--models",
            "deepseek-v4.1-flash",
            "--replicates",
            "1",
            "--limit-usd",
            "0.1",
            "--jobs",
            "1",
            "--skip-preflight",
            "--plain",
            "--",
            "--test-extension",
            str(FAKE),
            "--no-langfuse",
        ]
        cls.status_after = None
        try:
            cls.result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=2400)
            cls.status_after = lean_session.request(
                {"op": "status", "protocol": lean_session.PROTOCOL}, 10, str(lean_session.socket_path(cls.service))
            )
            log = cls.service / "service.log"
            cls.service_log = log.read_text().splitlines() if log.exists() else []
            cls.runs = sorted(RUNS.glob(f"{cls.prefix}-*-r1"))
            cls.health = {
                path.name: json.loads((path / "lean-health.json").read_text())
                for path in cls.runs
                if (path / "lean-health.json").exists()
            }
            cls.summaries = {
                path.name: json.loads((path / "summary.json").read_text())
                for path in cls.runs
                if (path / "summary.json").exists()
            }
        finally:
            if cls.service.exists():
                lean_session.stop_service(cls.service)

    @classmethod
    def tearDownClass(cls):
        for path in [*RUNS.glob(f"{cls.prefix}-*"), cls.work]:
            shutil.rmtree(path, ignore_errors=True)

    def output(self) -> str:
        return (self.result.stdout + self.result.stderr)[-3000:]

    def test_campaign_finished_both_rows_with_healthy_gates(self):
        self.assertEqual(self.result.returncode, 0, self.output())
        self.assertEqual(len(self.runs), 2, self.output())
        for name, report in self.health.items():
            with self.subTest(run=name):
                self.assertEqual(report.get("verdict"), "healthy", report)
        for name, summary in self.summaries.items():
            with self.subTest(run=name):
                self.assertNotEqual(summary.get("stop_reason"), "lean_unhealthy", summary)

    def test_first_row_toolchains_close_before_the_second_row_opens_any(self):
        started = [i for i, line in enumerate(self.service_log) if " server cslib-" in line and "started" in line]
        self.assertTrue(started, "\n".join(self.service_log[-40:]))
        strata_open = {line.split("server ", 1)[1].split()[0] for line in self.service_log if " server strata-" in line}
        self.assertTrue(strata_open, "\n".join(self.service_log[-40:]))
        for project in strata_open:
            closed = [i for i, line in enumerate(self.service_log) if "closed" in line and f"({project})" in line]
            with self.subTest(project=project):
                self.assertTrue(closed, f"{project} never closed")
                self.assertLess(closed[0], started[0], f"{project} was still open when the cslib row started")

    def test_cleanup_reports_the_closed_toolchains(self):
        self.assertIn("closed Lean strata-", self.result.stdout, self.output())

    def test_nothing_is_left_in_memory_after_the_campaign(self):
        status = self.status_after or {}
        self.assertEqual(status.get("servers", []), [], status)


if __name__ == "__main__":
    unittest.main()
