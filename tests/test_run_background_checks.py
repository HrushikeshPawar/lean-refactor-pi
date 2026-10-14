"""Background Lean health checks and stop propagation: injected fakes only."""

import importlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from arena import lean_health

run_module = importlib.import_module("arena.cli.run")


class BackgroundCheckTests(unittest.TestCase):
    def test_no_pending_versions_starts_no_thread(self):
        self.assertIsNone(run_module.start_background_checks("T", Path("."), {"pending": []}))

    def test_background_failure_sets_the_failure_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / lean_health.HEALTH_FILE).write_text(
                json.dumps({"versions": {"v1": {"checked": True}}, "pending": ["v2"]})
            )
            run_module._BACKGROUND["stop"].clear()
            run_module._BACKGROUND["failed"].clear()

            def check(_row, version, _commit, lane="model"):
                self.assertEqual((version, lane), ("v2", "background"))
                return {"seconds": 1, "passed": False, "detail": "compiler rejected reference"}

            with (
                mock.patch.object(lean_health, "gate_versions", return_value=[("v1", "c1"), ("v2", "c2")]),
                mock.patch("arena.engine.problem", return_value={"name": "T"}),
            ):
                thread = run_module.start_background_checks("T", directory, {"pending": ["v2"]}, check)
                assert thread is not None
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(run_module._BACKGROUND["failed"].is_set())
            marker = lean_health.tripped(directory)
            assert marker is not None
            self.assertEqual((marker["version"], marker["detail"]), ("v2", "compiler rejected reference"))

    def test_passing_checks_do_not_set_the_failure_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / lean_health.HEALTH_FILE).write_text(
                json.dumps({"versions": {"v1": {"checked": True}}, "pending": ["v2"]})
            )
            run_module._BACKGROUND["stop"].clear()
            run_module._BACKGROUND["failed"].clear()
            with (
                mock.patch.object(lean_health, "gate_versions", return_value=[("v1", "c1"), ("v2", "c2")]),
                mock.patch("arena.engine.problem", return_value={"name": "T"}),
            ):
                thread = run_module.start_background_checks(
                    "T", directory, {"pending": ["v2"]}, lambda *_args, **_kwargs: {"seconds": 1, "passed": True}
                )
                assert thread is not None
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(run_module._BACKGROUND["failed"].is_set())

    def test_unavailable_cold_fallback_trips_even_when_reference_compile_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / lean_health.HEALTH_FILE).write_text(
                json.dumps({"versions": {"v1": {"checked": True}}, "pending": ["v2"]})
            )
            run_module._BACKGROUND["stop"].clear()
            run_module._BACKGROUND["failed"].clear()
            with (
                mock.patch.object(lean_health, "gate_versions", return_value=[("v1", "c1"), ("v2", "c2")]),
                mock.patch("arena.engine.problem", return_value={"name": "T"}),
            ):
                thread = run_module.start_background_checks(
                    "T",
                    directory,
                    {"pending": ["v2"]},
                    lambda *_args, **_kwargs: {
                        "seconds": 1,
                        "passed": True,
                        "path": "cold-fallback",
                        "detail": "worker unavailable",
                    },
                )
                assert thread is not None
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(run_module._BACKGROUND["failed"].is_set())
            marker = lean_health.tripped(directory)
            assert marker is not None
            self.assertEqual(marker["source"], "reference_check")

    def test_watcher_stops_once_with_the_marker_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            lean_health.trip_unhealthy(directory, "v2", "compiler rejected reference")
            failed = threading.Event()
            calls = []
            watcher = run_module.watch_background_failure(failed, directory, calls.append)
            failed.set()
            watcher.join(2)
            self.assertFalse(watcher.is_alive())
            self.assertEqual(
                calls,
                ["Lean unhealthy on v2: compiler rejected reference; stopping before further spend"],
            )

    def test_watcher_does_not_stop_while_no_failure_is_signalled(self):
        failed = threading.Event()
        calls = []
        watcher = run_module.watch_background_failure(failed, Path("."), calls.append)
        self.assertTrue(watcher.is_alive())
        self.assertEqual(calls, [])
        failed.set()
        watcher.join(2)

    def test_reference_check_failure_finishes_as_lean_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with (
                mock.patch.object(run_module, "cost_report_from_ledger", return_value={"spent_usd": 0}),
                mock.patch.object(run_module, "submission", return_value={"reason": "none"}),
                mock.patch.object(run_module, "write_state"),
                mock.patch.object(run_module, "write_summary", return_value={}) as write_summary,
                mock.patch.object(run_module, "render_text", return_value="summary\n"),
            ):
                result = run_module.finish(
                    mock.Mock(theorem="T", run_id="run"),
                    directory,
                    directory / "events.jsonl",
                    0,
                    0,
                    None,
                    tripped=True,
                )
            self.assertEqual(result, lean_health.EXIT_CODE)
            write_summary.assert_called_once_with(directory, lean_health.STOP_REASON)

    def finish_with(self, directory, interrupted, autocheck):
        calls = []
        with (
            mock.patch.object(run_module, "cost_report_from_ledger", return_value={"spent_usd": 0}),
            mock.patch.object(
                run_module, "autocheck", side_effect=lambda *a, **k: calls.append("drain") or autocheck()
            ),
            mock.patch.object(
                run_module, "submission", side_effect=lambda _run: calls.append("submission") or {"reason": "none"}
            ),
            mock.patch.object(run_module, "write_state"),
            mock.patch.object(run_module, "write_summary", return_value={}),
            mock.patch.object(run_module, "render_text", return_value="summary\n"),
        ):
            result = run_module.finish(
                mock.Mock(theorem="T", run_id="run"), directory, directory / "events.jsonl", 0, 0, interrupted
            )
        return result, calls

    def test_operator_interrupt_still_drains_before_choosing_the_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = self.finish_with(Path(tmp), 2, lambda: {"checked": ["#3"], "remaining": []})
        self.assertEqual(result, 130)
        self.assertEqual(calls, ["drain", "submission"])

    def test_a_further_stop_request_skips_the_drain_but_still_chooses(self):
        import os
        import signal

        def interrupted_drain():
            os.kill(os.getpid(), signal.SIGINT)
            raise AssertionError("the drain should have been cut")

        previous = signal.getsignal(signal.SIGINT)
        with tempfile.TemporaryDirectory() as tmp:
            result, calls = self.finish_with(Path(tmp), 2, interrupted_drain)
        self.assertEqual(result, 130)
        self.assertEqual(calls, ["drain", "submission"])
        self.assertIs(signal.getsignal(signal.SIGINT), previous)


if __name__ == "__main__":
    unittest.main()
