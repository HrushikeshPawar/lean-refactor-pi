"""OpenCode Go peak pricing: the models.yaml window helpers, the settled-price copy the extension reads, and the run guard
(start refusal, dry-run warning, --allow-peak, and the watcher that stops a running run). No Lean, no provider."""

import contextlib
import copy
import importlib
import io
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from arena import models

run_cli = importlib.import_module("arena.cli.run")  # `arena.cli.run` the attribute is the command function
RunOptions = run_cli.RunOptions
DEEPSEEK = "deepseek-v4.1-flash"
SOL = "gpt-6.1-sol"
FLASH_OR = "deepseek-v4.1-flash-or"  # OpenRouter: no peak block
THEOREM = "Core.InitsUpdatesComm"
UTC = timezone.utc
MON_PEAK = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)  # Monday 02:00 UTC: inside 01:00-04:00
SAT_OFF = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)  # Saturday: off-peak all day


class PeakWindowTests(unittest.TestCase):
    def test_window_boundaries_on_weekdays(self):
        at = lambda when: models.in_peak(DEEPSEEK, when)  # noqa: E731
        self.assertTrue(at(datetime(2026, 10, 26, 1, 0, tzinfo=UTC)))  # Mon 01:00 starts peak
        self.assertFalse(at(datetime(2026, 10, 26, 0, 59, 59, tzinfo=UTC)))
        self.assertTrue(at(datetime(2026, 10, 26, 3, 59, 59, tzinfo=UTC)))
        self.assertFalse(at(datetime(2026, 10, 26, 4, 0, tzinfo=UTC)))  # Mon 04:00 is off-peak
        self.assertTrue(at(datetime(2026, 10, 23, 9, 59, tzinfo=UTC)))  # Fri 09:59 peak
        self.assertFalse(at(datetime(2026, 10, 23, 10, 0, tzinfo=UTC)))  # Fri 10:00 off-peak
        self.assertFalse(at(SAT_OFF))
        self.assertFalse(at(datetime(2026, 10, 25, 2, 0, tzinfo=UTC)))  # Sunday

    def test_peak_is_read_in_utc_whatever_the_local_zone(self):
        cest = timezone(timedelta(hours=2))
        self.assertTrue(models.in_peak(DEEPSEEK, datetime(2026, 10, 26, 3, 30, tzinfo=cest)))  # 01:30 UTC
        self.assertFalse(models.in_peak(DEEPSEEK, datetime(2026, 10, 26, 6, 0, tzinfo=cest)))  # 04:00 UTC

    def test_multiplier_is_two_at_peak_and_one_otherwise(self):
        self.assertEqual(models.peak_multiplier(DEEPSEEK, MON_PEAK), 2.0)
        self.assertEqual(models.peak_multiplier(DEEPSEEK, SAT_OFF), 1.0)
        self.assertEqual(models.peak_multiplier(SOL, MON_PEAK), 1.0)  # no peak block
        self.assertFalse(models.in_peak(SOL, MON_PEAK))
        self.assertFalse(models.in_peak(FLASH_OR, MON_PEAK))

    def test_next_off_peak_is_the_close_of_the_current_window(self):
        self.assertEqual(models.next_off_peak(DEEPSEEK, MON_PEAK), datetime(2026, 10, 26, 4, 0, tzinfo=UTC))
        friday = datetime(2026, 10, 23, 9, 30, tzinfo=UTC)
        self.assertEqual(models.next_off_peak(DEEPSEEK, friday), datetime(2026, 10, 23, 10, 0, tzinfo=UTC))
        early = datetime(2026, 10, 23, 6, 30, tzinfo=UTC)  # the 06:00-10:00 window ends later than 04:00
        self.assertEqual(models.next_off_peak(DEEPSEEK, early), datetime(2026, 10, 23, 10, 0, tzinfo=UTC))
        self.assertEqual(models.next_off_peak(DEEPSEEK, SAT_OFF), SAT_OFF)  # already off-peak: the same instant

    def test_naive_times_are_refused(self):
        with self.assertRaises(ValueError):
            models.in_peak(DEEPSEEK, datetime(2026, 10, 26, 2, 0))


class PeakConfigTests(unittest.TestCase):
    def test_yaml_subset_reads_quoted_windows_and_flow_lists(self):
        parsed = models.parse('peak: {multiplier: 2, weekdays: [mon, fri], utc: ["01:00-04:00", "06:00-10:00"]}\n')
        self.assertEqual(parsed, {"peak": {"multiplier": 2, "weekdays": ["mon", "fri"], "utc": ["01:00-04:00", "06:00-10:00"]}})

    def test_pi_json_carries_the_peak_block_to_the_extension(self):
        row = json.loads(models.pi_json())["models"][DEEPSEEK]
        self.assertEqual(row["peak"], {"multiplier": 2, "weekdays": ["mon", "tue", "wed", "thu", "fri"],
                                       "utc": ["01:00-04:00", "06:00-10:00"]})
        self.assertNotIn("peak", json.loads(models.pi_json())["models"][SOL])

    def test_malformed_peak_blocks_are_refused(self):
        good = models.load()
        bad_blocks = [
            {"multiplier": 1, "weekdays": ["mon"], "utc": ["01:00-04:00"]},  # not above 1
            {"multiplier": 2, "weekdays": ["monday"], "utc": ["01:00-04:00"]},  # unknown day
            {"multiplier": 2, "weekdays": ["mon"], "utc": ["04:00-01:00"]},  # start after end
            {"multiplier": 2, "weekdays": ["mon"], "utc": ["25:00-26:00"]},  # not a clock time
            {"multiplier": 2, "weekdays": ["mon"]},  # no windows
        ]
        for block in bad_blocks:
            config = copy.deepcopy(good)
            config["models"][DEEPSEEK]["peak"] = block
            with self.subTest(block=block), self.assertRaises(models.ModelConfigError):
                models.validate(config)


class PeakRunGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.absent = Path(self.directory.name) / "absent-run"

    def run_with_clock(self, now: datetime, dry_run: bool, **flags) -> tuple[int, str]:
        options = RunOptions(model=flags.pop("model", SOL), theorem=THEOREM, run_id="peak-guard-test", limit_usd=1.0,
                             dry_run=dry_run, plain=True, **flags)
        err = io.StringIO()
        with (patch.object(run_cli, "_now", return_value=now), patch.object(run_cli, "run_dir", return_value=self.absent),
              contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO())):
            code = run_cli.run(options)
        return code, err.getvalue()

    def test_start_is_refused_in_a_peak_window_before_any_lean_or_pi_work(self):
        code, err = self.run_with_clock(MON_PEAK, dry_run=False)
        self.assertEqual(code, 2)
        self.assertIn(f"error: peak hours: {DEEPSEEK} (worker, 2x) billed at peak pricing now", err)
        self.assertIn("off-peak starts 2026-10-26 04:00 UTC", err)
        self.assertIn("rerun with --allow-peak to run anyway", err)
        self.assertFalse(self.absent.exists())

    def test_the_orchestrator_is_named_when_it_is_the_peak_model(self):
        code, err = self.run_with_clock(MON_PEAK, dry_run=False, model=DEEPSEEK, worker_model=FLASH_OR)
        self.assertEqual(code, 2)
        self.assertIn(f"{DEEPSEEK} (orchestrator, 2x)", err)
        self.assertNotIn("worker", err)

    def test_a_resumed_run_is_judged_by_its_own_worker_model(self):
        self.absent.mkdir()
        (self.absent / "run-config.json").write_text(json.dumps({"worker_model": DEEPSEEK}))
        options = dict(model=FLASH_OR, resume_run=True)
        code, err = self.run_with_clock(MON_PEAK, dry_run=False, **options)
        self.assertEqual(code, 2)
        self.assertIn(f"{DEEPSEEK} (worker, 2x)", err)

    def test_no_refusal_off_peak(self):
        code, err = self.run_with_clock(SAT_OFF, dry_run=True)
        self.assertEqual(code, 0)
        self.assertNotIn("peak", err)

    def test_allow_peak_runs_through_a_peak_window(self):
        code, err = self.run_with_clock(MON_PEAK, dry_run=True, allow_peak=True)
        self.assertEqual(code, 0)
        self.assertNotIn("peak", err)

    def test_dry_run_in_a_peak_window_warns_and_exits_as_a_dry_run(self):
        code, err = self.run_with_clock(MON_PEAK, dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("warning: peak hours:", err)
        self.assertIn("rerun with --allow-peak to run anyway", err)

    def test_models_without_a_peak_block_never_trigger(self):
        code, err = self.run_with_clock(MON_PEAK, dry_run=True, model=FLASH_OR, worker_model=FLASH_OR)
        self.assertEqual(code, 0)
        self.assertNotIn("peak", err)

    def test_watcher_stops_the_run_when_a_peak_window_begins(self):
        clock = {"now": SAT_OFF}
        stops: list[str] = []
        done = threading.Event()
        with patch.object(run_cli, "_now", side_effect=lambda: clock["now"]):
            thread = run_cli.watch_peak([("orchestrator", DEEPSEEK)], stops.append, done, interval_s=0.01)
            time.sleep(0.1)
            self.assertEqual(stops, [])  # off-peak: nothing happens
            clock["now"] = MON_PEAK
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(stops), 1)
        self.assertIn("Stopping Pi for peak hours: deepseek-v4.1-flash (orchestrator, 2x)", stops[0])
        self.assertIn("off-peak starts 2026-10-26 04:00 UTC", stops[0])
        self.assertIn("--resume-run after off-peak starts, or --resume-run --allow-peak now", stops[0])

    def test_watcher_ends_quietly_when_the_run_is_done(self):
        stops: list[str] = []
        done = threading.Event()
        with patch.object(run_cli, "_now", return_value=MON_PEAK):
            thread = run_cli.watch_peak([("orchestrator", DEEPSEEK)], stops.append, done, interval_s=0.01)
            done.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(stops, [])


if __name__ == "__main__":
    unittest.main()
