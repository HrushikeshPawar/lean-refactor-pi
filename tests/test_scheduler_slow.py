"""One real-service check for the scheduler's primary-header warm path."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import engine, lean_session
from tests.slow import slow


@slow
class SchedulerWarmIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        (Path(__file__).resolve().parents[1] / "workspaces/strata-v4.29.1").is_dir(),
        "Core's v4.29.1 workspace is not provisioned",
    )
    def test_warmed_primary_compile_reuses_worker_after_lease(self):
        row = engine.problem("Core.InitsUpdatesComm")
        version, commit = engine.measure_version(row)
        socket_path = lean_session.ensure_service()
        primary = str(engine.workspace(row, version, commit))
        run_id = f"scheduler-warm-{os.getpid()}"
        with patch.dict(os.environ, {lean_session.ENV: socket_path}):
            self.assertIsNotNone(engine.warm_session(row, version, commit, slots=1, lane="model"))
            lease = lean_session.request(
                {
                    "op": "lease",
                    "protocol": lean_session.PROTOCOL,
                    "run_id": run_id,
                    "pid": os.getpid(),
                    "primary": primary,
                    "others": [],
                },
                5,
                socket_path,
            )
            self.assertTrue(lease and lease.get("ok"), lease)
            proof = row["statement"] + " := by\n  intros\n  sorry"
            try:
                with patch.dict(os.environ, {lean_session.RUN_ID_ENV: run_id}):
                    result = engine.compile_version(row, proof, version, commit, probe=True)
                self.assertEqual(result["lean"]["path"], "session", result["lean"])
                self.assertIs(result["lean"]["new_worker"], False)
                self.assertIsNone(result["lean"].get("header_seconds"))
            finally:
                lean_session.request(
                    {"op": "release", "protocol": lean_session.PROTOCOL, "run_id": run_id}, 5, socket_path
                )


if __name__ == "__main__":
    unittest.main()
