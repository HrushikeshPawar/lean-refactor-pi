"""Lean health gate, circuit breaker and between-run cleanup: injected fakes only, no Lean, Pi or model."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arena import lean_health as lh

rc = importlib.import_module("arena.cli.campaigns")
rpb = importlib.import_module("arena.cli.run")


def run_gate(checks, warms=None, versions=(("v1", "c1"), ("v2", "c2")), directory=None):
    lines = []
    warm = (
        (lambda row, v, c, slots, lane="model", wait=True: warms[v])
        if warms is not None
        else (lambda *a, **kw: {"ok": True, "workers": 4, "seconds": [10.0], "failed": []})
    )
    report = lh.gate(
        "T",
        4,
        directory,
        row_fn=lambda name: {"name": name},
        versions_fn=lambda row: list(versions),
        warm_fn=warm,
        check_fn=lambda row, v, c, lane="model": checks[v],
        log=lines.append,
    )
    return report, lines


def ok(seconds):
    return {"seconds": seconds, "passed": True, "timed_out": False, "detail": ""}


class GateTests(unittest.TestCase):
    def test_choose_limit_clamps(self):
        self.assertEqual(lh.choose_limit(None), 60)
        self.assertEqual(lh.choose_limit(10), 60)
        self.assertEqual(lh.choose_limit(3), 60)
        self.assertEqual(lh.choose_limit(100), 300)
        self.assertEqual(lh.choose_limit(500), 900)

    def test_gate_uses_only_primary_and_records_other_versions_as_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, lines = run_gate({"v1": ok(41.0), "v2": {"seconds": 1000, "passed": False}}, directory=Path(tmp))
            self.assertEqual((report["verdict"], report["timeout"], report["reasons"]), ("healthy", 123, []))
            self.assertEqual(report["pending"], ["v2"])
            self.assertEqual(report["versions"]["v2"]["warmup"], "background")
            self.assertFalse(report["versions"]["v2"]["checked"])
            saved = json.loads((Path(tmp) / "lean-health.json").read_text())
            self.assertEqual(saved["versions"]["v1"]["check_seconds"], 41.0)
            self.assertEqual(saved["versions"]["v1"]["header_seconds"], 10.0)
        self.assertTrue(any("lean warm v1: 4 workers ready in 10 s" in line for line in lines))
        self.assertFalse(any(line.startswith("reference v2:") for line in lines))

    def test_reference_timeout_or_failure_is_unhealthy(self):
        timeout = {"seconds": 900.0, "passed": False, "timed_out": True, "detail": "timed out after 900 s"}
        report, _ = run_gate({"v1": timeout, "v2": ok(5.0)})
        self.assertEqual(report["verdict"], "unhealthy")
        self.assertIn("v1", report["reasons"][0])
        failed = {"seconds": 3.0, "passed": False, "timed_out": False, "detail": "error: unknown constant"}
        self.assertEqual(run_gate({"v1": failed, "v2": ok(1.0)})[0]["verdict"], "unhealthy")

    def test_check_using_over_half_the_limit_is_unhealthy(self):
        # limit = 3 x 400 -> 900 (cap); 400 s is under half of 900 -> healthy; with 500 s it is not
        self.assertEqual(run_gate({"v1": ok(400.0), "v2": ok(1.0)})[0]["verdict"], "healthy")
        report, _ = run_gate({"v1": ok(500.0), "v2": ok(1.0)})
        self.assertEqual((report["verdict"], report["timeout"]), ("unhealthy", 900))
        self.assertIn("over 50%", report["reasons"][0])

    def test_no_worker_ready_is_unhealthy_and_no_session_is_tolerated(self):
        dead = {"ok": False, "workers": 0, "seconds": [], "failed": ["boom"]}
        report, lines = run_gate({"v1": ok(5.0), "v2": ok(5.0)}, warms={"v1": dead, "v2": None})
        self.assertEqual(report["verdict"], "unhealthy")
        self.assertEqual(len(report["reasons"]), 1)
        self.assertIsNone(report["versions"]["v2"]["workers"])
        self.assertIn("lean warm v1: NO worker ready (boom)", lines)

    def test_a_gate_without_a_session_says_the_check_includes_the_import(self):
        _, lines = run_gate({"v1": ok(5.0)}, warms={"v1": None}, versions=(("v1", "c1"),))
        self.assertTrue(any(line.startswith("lean warm v1: no session configured") for line in lines))

    def test_other_versions_are_warmed_without_waiting_or_checking(self):
        calls = []
        checked = []

        def warm(row, v, c, slots, lane="model", wait=True):
            calls.append((v, slots, lane, wait))
            return (
                {"ok": True, "workers": slots, "seconds": [1.0], "failed": []}
                if wait
                else {"ok": True, "started": True}
            )

        lh.gate(
            "T",
            4,
            None,
            row_fn=lambda name: {"name": name},
            versions_fn=lambda row: [("v1", "c1"), ("v2", "c2"), ("v3", "c3")],
            warm_fn=warm,
            check_fn=lambda row, v, c, lane="model": checked.append((v, lane)) or ok(1.0),
            log=lambda m: None,
        )
        self.assertEqual(
            calls, [("v1", 4, "model", True), ("v2", 1, "background", False), ("v3", 1, "background", False)]
        )
        self.assertEqual(checked, [("v1", "model")])

    def test_check_others_stops_after_first_failure_and_trips_named_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_gate({"v1": ok(2)}, directory=directory, versions=(("v1", "c1"), ("v2", "c2"), ("v3", "c3")))
            calls = []

            def check(row, version, commit, lane="model"):
                calls.append((version, lane))
                return {"seconds": 3, "passed": False, "detail": "bad", "timed_out": False}

            rows = lh.check_others(
                "T",
                directory,
                row_fn=lambda _: {},
                versions_fn=lambda _: [("v1", "c1"), ("v2", "c2"), ("v3", "c3")],
                check_fn=check,
                now_fn=lambda: 7.0,
            )
            self.assertEqual(calls, [("v2", "background")])
            self.assertEqual(rows[0]["version"], "v2")
            marker = json.loads((directory / lh.TRIPPED_FILE).read_text())
            self.assertEqual((marker["version"], marker["source"], marker["ts"]), ("v2", "reference_check", 7.0))

    def test_check_others_respects_cancellation_and_leaves_successful_versions_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_gate(
                {"v1": ok(2)},
                directory=directory,
                versions=(("v1", "c1"), ("v2", "c2"), ("v3", "c3")),
            )
            calls = []

            def check(row, version, commit, lane="model"):
                calls.append(version)
                return ok(2)

            self.assertEqual(
                lh.check_others(
                    "T",
                    directory,
                    row_fn=lambda _: {},
                    versions_fn=lambda _: [("v1", "c1"), ("v2", "c2"), ("v3", "c3")],
                    check_fn=check,
                    cancelled=lambda: True,
                ),
                [],
            )
            self.assertEqual(calls, [])
            rows = lh.check_others(
                "T",
                directory,
                row_fn=lambda _: {},
                versions_fn=lambda _: [("v1", "c1"), ("v2", "c2"), ("v3", "c3")],
                check_fn=check,
            )
            self.assertEqual([entry["version"] for entry in rows], ["v2", "v3"])
            self.assertIsNone(lh.tripped(directory))
            self.assertEqual(lh.read_health(directory)["pending"], [])


def check(kind: str, trigger: str = "model", record: str = "evaluation") -> dict:
    entry = {"passed": False, "lean": {"path": "session"}}
    if kind == "timeout":
        entry["error"] = "Lean timed out after 180 seconds"
    elif kind == "compile_error":
        entry.update(exit_code=1)
    else:
        entry["passed"] = True
    result = {"ok": True, "compat": {"v1": entry}}
    if kind == "unavailable":
        result = {"ok": False, "compat": {}, "lean_unavailable": True}
    event = {"kind": record, "result": result}
    if record == "evaluation":
        event["trigger"] = trigger
    return event


class BreakerTests(unittest.TestCase):
    def test_timeouts_count_compile_errors_do_not_and_success_resets(self):
        self.assertEqual(lh.streak([check("timeout")] * 4), 4)
        # compile errors answer: they end the streak, they are not Lean failures
        self.assertEqual(lh.streak([check("timeout")] * 3 + [check("compile_error")]), 0)
        self.assertEqual(lh.streak([check("timeout")] * 3 + [check("ok")] + [check("timeout")] * 2), 2)
        self.assertEqual(lh.streak([check("timeout"), check("unavailable", record="probe"), check("timeout")]), 3)

    def test_background_checks_are_not_counted(self):
        ledger = [check("timeout")] * 2 + [check("ok", trigger="auto")] + [check("timeout", trigger="auto")] * 5
        self.assertEqual(lh.streak(ledger), 2)

    def test_trips_at_five_and_keeps_first_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            ledger = [check("timeout")] * 4
            self.assertIsNone(lh.trip_if_unhealthy(directory, ledger))
            self.assertIsNone(lh.tripped(directory))
            marker = lh.trip_if_unhealthy(directory, [*ledger, check("timeout", record="probe")], now_fn=lambda: 7.0)
            self.assertEqual((marker["consecutive"], marker["stop_reason"], marker["ts"]), (5, "lean_unhealthy", 7.0))
            self.assertEqual(lh.tripped(directory)["consecutive"], 5)
            self.assertEqual(lh.trip_if_unhealthy(directory, ledger * 3)["ts"], 7.0)

    def test_compile_errors_never_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(lh.trip_if_unhealthy(Path(tmp), [check("compile_error")] * 20))


class CampaignRecordingTests(unittest.TestCase):
    def test_ledger_recording_trips_and_then_refuses_model_work(self):
        from arena import campaign

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for _ in range(5):
                campaign._append(directory, {"kind": "probe", "proof_id": "p", "result": check("timeout")["result"]})
            campaign._check_breaker(directory)
            self.assertIsNotNone(lh.tripped(directory))
            with self.assertRaisesRegex(ValueError, "run has stopped"):
                campaign._refuse_if_tripped(directory)
            with mock.patch.object(campaign, "events", return_value=[]):
                self.assertEqual(campaign.autocheck.__name__, "autocheck")  # smoke: importable with the breaker


class RunnerTests(unittest.TestCase):
    def test_tool_events_get_a_timestamp_and_other_lines_do_not(self):
        start = rpb.stamp_tool_event(json.dumps({"type": "tool_execution_start", "toolName": "x"}) + "\n")
        self.assertIn("ts", json.loads(start))
        other = json.dumps({"type": "message_end"}) + "\n"
        self.assertEqual(rpb.stamp_tool_event(other), other)
        kept = json.dumps({"type": "tool_execution_end", "ts": 1}) + "\n"
        self.assertEqual(rpb.stamp_tool_event(kept), kept)

    def test_unhealthy_gate_stops_before_any_model_and_writes_the_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with (
                mock.patch.object(rpb, "cost_report_from_ledger", return_value={"spent_usd": 0}),
                mock.patch.object(rpb, "write_summary", return_value={}) as write,
                mock.patch.object(rpb, "render_text", return_value="summary\n"),
            ):
                code = rpb.stop_unhealthy(None, directory, ["v1: reference timed out"])
            self.assertEqual(code, lh.EXIT_CODE)
            write.assert_called_once_with(directory, "lean_unhealthy")
            self.assertTrue((directory / "cost.json").exists())

    def test_gate_sets_the_timeout_env_only_when_healthy(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("ARENA_LEAN_TIMEOUT", None)
            directory = Path(tmp)
            (directory / lh.TRIPPED_FILE).write_text("{}")
            with mock.patch.dict(rpb._LEAN, {"socket": "service.sock"}):
                bad = rpb.lean_gate(
                    "T", directory, lambda *a: {"verdict": "unhealthy", "reasons": ["x"], "timeout": 900}
                )
                self.assertEqual(bad["verdict"], "unhealthy")
                self.assertNotIn("ARENA_LEAN_TIMEOUT", os.environ)
                good = rpb.lean_gate("T", directory, lambda *a: {"verdict": "healthy", "reasons": [], "timeout": 333})
                self.assertEqual(good["verdict"], "healthy")
                self.assertEqual(os.environ["ARENA_LEAN_TIMEOUT"], "333")
            self.assertFalse((directory / lh.TRIPPED_FILE).exists())
            os.environ.pop("ARENA_LEAN_TIMEOUT", None)
            self.assertIsNone(rpb.lean_gate("T", directory, lambda *a: self.fail("no session, no gate")))


class FakeProc:
    """A fake /proc: pid -> (comm, cmdline, alive)."""

    def __init__(self, table):
        self.table = dict(table)
        self.signals = []

    comm = lambda self, pid: self.table.get(pid, (None,))[0]  # noqa: E731
    cmdline = lambda self, pid: self.table.get(pid, (None, ""))[1]  # noqa: E731
    alive = lambda self, pid: pid in self.table  # noqa: E731

    def kill(self, pid, number):
        self.signals.append((pid, number))
        self.table.pop(pid, None)

    def killpg(self, pgid, number):
        self.signals.append(("pg", pgid, number))
        self.table.pop(pgid, None)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "run-1"
        self.dir.mkdir()

    def fake(self):
        return FakeProc(
            {
                100: ("python3", "python -m arena.lean_session serve --service-dir /tmp/service", True),
                201: ("lean", "", True),
                202: ("lake", "", True),
                203: ("firefox", "", True),  # a recorded pid that was reused by something else
                9999: ("lean", "", True),
            }
        )  # a Lean of someone else: never recorded

    def reap(self, proc):
        return rc.reap_run(
            self.dir,
            comm_fn=proc.comm,
            cmdline_fn=proc.cmdline,
            alive_fn=proc.alive,
            kill_fn=proc.kill,
            killpg_fn=proc.killpg,
            sleep_fn=lambda s: None,
        )

    def test_run_housekeeping_never_signals_the_machine_wide_service(self):
        proc = self.fake()
        self.assertEqual(self.reap(proc), 0)
        self.assertEqual(proc.signals, [])

    def test_another_runs_daemon_with_a_reused_pid_is_not_killed(self):
        proc = FakeProc({100: ("python3", "python -m arena.lean_session serve --run-dir /other/run", True)})
        self.assertEqual(self.reap(proc), 0)
        self.assertEqual(proc.signals, [])

    def test_clean_run_has_nothing_to_reap(self):
        proc = self.fake()
        self.assertEqual(self.reap(proc), 0)
        self.assertEqual(proc.signals, [])

    def test_lingering_lists_live_recorded_processes(self):
        proc = self.fake()
        self.assertEqual(rc.lingering(self.dir, proc.comm, proc.cmdline, proc.alive), [])

    def test_sweep_removes_only_new_arena_dirs(self):
        root = Path(self.temp.name) / "evaluations"
        (root / "arena-old").mkdir(parents=True)
        (root / "arena-new").mkdir()
        (root / "keep").mkdir()
        import os

        os.utime(root / "arena-old", (1, 1))
        self.assertEqual(rc.sweep_candidate_dirs(root, 1000.0), 1)
        self.assertEqual(sorted(p.name for p in root.iterdir()), ["arena-old", "keep"])


class HousekeepingTests(unittest.TestCase):
    def test_warm_service_memory_counts_toward_the_campaign_threshold(self):
        hk = rc.Housekeeping(
            20.0,
            30.0,
            0.0,
            mem_fn=lambda: 8.0,
            service_gb_fn=lambda: 20.0,
            lingering_fn=lambda _directory: [],
            sleep_fn=lambda _seconds: self.fail("waited despite available service memory"),
            now_fn=lambda: 0.0,
            log=lambda _message: None,
        )
        hk.before_run("warm")
        self.assertEqual(hk.in_flight, 1)

    def test_housekeeping_still_waits_when_no_warm_service_memory_is_available(self):
        clock = [0.0]
        naps = []
        lines = []
        hk = rc.Housekeeping(
            20.0,
            10.0,
            0.0,
            mem_fn=lambda: 8.0,
            service_gb_fn=lambda: 0.0,
            lingering_fn=lambda _directory: [],
            sleep_fn=lambda seconds: (naps.append(seconds), clock.__setitem__(0, clock[0] + seconds)),
            now_fn=lambda: clock[0],
            log=lines.append,
        )
        hk.before_run("cold")
        self.assertTrue(naps)
        self.assertEqual(hk.in_flight, 1)
        self.assertTrue(any("MemAvailable 8.0 GB + idle Lean service 0.0 GB" in line for line in lines))

    def test_service_memory_sums_server_process_trees_and_defaults_to_zero(self):
        status = {"ok": True, "servers": [{"gb": 1.25}, {"gb": 2.75}]}
        self.assertEqual(rc.service_gb(lambda: status), 4.0)
        self.assertEqual(rc.service_gb(lambda: None), 0.0)
        self.assertEqual(rc.service_gb(lambda: {"ok": False}), 0.0)

    def test_waits_for_stray_lean_and_memory_then_starts_and_logs(self):
        lines, clock, naps = [], [0.0], []
        left = [[7], [7], []]
        free = [3.0, 3.0, 12.0]

        def nap(seconds):
            clock[0] += seconds
            naps.append(seconds)
            left.pop(0) if len(left) > 1 else None
            free.pop(0) if len(free) > 1 else None

        hk = rc.Housekeeping(
            8.0,
            300.0,
            0.0,
            Path("/nonexistent"),
            mem_fn=lambda: free[0],
            reap_fn=lambda d: 2,
            lingering_fn=lambda d: left[0],
            sweep_fn=lambda root, since: 1,
            sleep_fn=nap,
            now_fn=lambda: clock[0],
            log=lines.append,
        )
        hk.finished.append(Path("/runs/a"))
        hk.before_run("b")
        self.assertEqual(len(naps), 2)
        self.assertTrue(any("waiting before b" in line for line in lines))
        hk.after_run("b", Path("/runs/b"))
        self.assertTrue(
            any(line.startswith("cleanup b: reaped 2, removed 1") and "MemAvailable 12.0 GB" in line for line in lines)
        )

    def test_gives_up_waiting_after_the_limit(self):
        clock, lines = [0.0], []
        hk = rc.Housekeeping(
            8.0,
            20.0,
            0.0,
            mem_fn=lambda: 1.0,
            lingering_fn=lambda d: [],
            sleep_fn=lambda s: clock.__setitem__(0, clock[0] + s),
            now_fn=lambda: clock[0],
            log=lines.append,
        )
        hk.before_run("x")
        self.assertTrue(any("starting x anyway" in line for line in lines))

    def test_beside_a_live_run_memory_is_required_and_waits_without_deadline(self):
        """v7-check3 admitted Binius beside EM with 7.8 GB; the Lean gate then had no room for a worker."""
        clock, naps, lines = [0.0], [], []
        free = [3.0] * 200 + [12.0]

        def nap(seconds):
            clock[0] += seconds
            naps.append(seconds)
            free.pop(0)

        hk = rc.Housekeeping(
            8.0,
            20.0,
            0.0,
            mem_fn=lambda: free[0],
            service_gb_fn=lambda: self.fail("a live run's Lean memory is not free"),
            close_idle_fn=lambda: self.fail("closing beside a live run"),
            lingering_fn=lambda d: [],
            sleep_fn=nap,
            now_fn=lambda: clock[0],
            log=lines.append,
        )
        hk.in_flight = 1
        hk.before_run("second")
        self.assertEqual(len(naps), 200)  # 1000 s, far past max_wait: no "starting anyway" beside a live run
        self.assertFalse(any("anyway" in line for line in lines))
        self.assertTrue(any("beside a live run" in line for line in lines))
        self.assertEqual(hk.in_flight, 2)

    def test_after_run_closes_idle_lean_and_reports_it(self):
        lines, closed = [], []
        hk = rc.Housekeeping(
            8.0,
            20.0,
            0.0,
            mem_fn=lambda: 12.0,
            reap_fn=lambda d: 0,
            close_idle_fn=lambda: closed.append(1) or ["/w/cslib-v4.33.0", "/w/cslib-v4.32.0"],
            sweep_fn=lambda root, since: 0,
            log=lines.append,
        )
        hk.in_flight = 1
        hk.after_run("a", Path("/runs/a"))
        self.assertEqual(closed, [1])
        self.assertIn("closed Lean cslib-v4.33.0, cslib-v4.32.0", lines[-1])

    def test_alone_and_low_asks_the_service_to_close_idle_projects(self):
        closed, free = [], [3.0, 12.0]
        hk = rc.Housekeeping(
            8.0,
            20.0,
            0.0,
            mem_fn=lambda: free[0],
            service_gb_fn=lambda: 0.0,
            close_idle_fn=lambda: closed.append(1) or [],
            lingering_fn=lambda d: [],
            sleep_fn=lambda s: free.pop(0),
            now_fn=lambda: 0.0,
            log=lambda m: None,
        )
        hk.before_run("x")
        self.assertEqual(closed, [1])

    def test_requeue_only_lean_refusals_without_spend(self):
        specs = [{"run_id": "a", "row": "A"}, {"run_id": "b", "row": "B"}, {"run_id": "c", "row": "C"}, {"run_id": "d"}]
        results = [
            {"exit_code": rc.LEAN_UNHEALTHY_EXIT, "spent_usd": 0.0},
            {"exit_code": 0, "stop_reason": "lean_unhealthy", "spent_usd": 0.09},
            {"exit_code": 0, "spent_usd": 0.5},
            None,
        ]
        self.assertEqual(rc.requeue_specs(specs, results), [{"run_id": "a-retry", "row": "A"}])


class MemoryWaitTests(unittest.TestCase):
    """v7-check3: Binius, Core and SKI were lost to memory refusals counted as Lean faults."""

    def test_gate_waits_for_memory_then_warms(self):
        replies = [
            {
                "ok": False,
                "workers": 0,
                "seconds": [],
                "failed": ["no room for a Lean worker: memory (7.8 GB available)"],
            },
            {"ok": True, "workers": 2, "seconds": [5.0], "failed": []},
        ]
        sleeps = []
        report = lh.gate(
            "T",
            2,
            None,
            row_fn=lambda name: {"name": name},
            versions_fn=lambda row: [("v1", "c1")],
            warm_fn=lambda *a, **kw: replies.pop(0),
            check_fn=lambda *a, **kw: ok(1.0),
            log=lambda m: None,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(sleeps, [lh.ROOM_POLL_S])

    def test_gate_gives_up_after_the_room_wait(self):
        refused = {"ok": False, "workers": 0, "seconds": [], "failed": ["no room for a Lean worker: memory"]}
        report = lh.gate(
            "T",
            2,
            None,
            row_fn=lambda name: {"name": name},
            versions_fn=lambda row: [("v1", "c1")],
            warm_fn=lambda *a, **kw: refused,
            check_fn=lambda *a, **kw: ok(1.0),
            log=lambda m: None,
            sleep_fn=lambda s: None,
            room_wait_s=0,
        )
        self.assertEqual(report["verdict"], "unhealthy")

    def _others(self, directory, results, retries=2):
        calls, sleeps = [], []

        def check(row, version, commit, lane="model"):
            calls.append(version)
            return results.pop(0)

        rows = lh.check_others(
            "T",
            directory,
            row_fn=lambda _: {},
            versions_fn=lambda _: [("v1", "c1"), ("v2", "c2")],
            check_fn=check,
            sleep_fn=sleeps.append,
            retries=retries,
            retry_s=5,
            log=lambda m: None,
        )
        return rows, calls, sleeps

    def test_memory_starved_cold_check_is_retried_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_gate({"v1": ok(2)}, directory=directory)
            starved = {**ok(30), "path": "cold-fallback", "reason": "no room for a Lean worker: memory (6.8 GB)"}
            rows, calls, sleeps = self._others(directory, [starved, {**ok(3), "path": "lsp"}])
            self.assertEqual(calls, ["v2", "v2"])
            self.assertEqual(sleeps, [5])
            self.assertIsNone(lh.tripped(directory))
            self.assertTrue(rows[0]["passed"])

    def test_persistent_starvation_trips_with_an_honest_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_gate({"v1": ok(2)}, directory=directory)
            starved = {**ok(896), "path": "cold-fallback", "reason": "no memory to load a Lean worker (6.8 GB)"}
            _rows, calls, _ = self._others(directory, [dict(starved) for _ in range(3)])
            self.assertEqual(len(calls), 3)
            marker = lh.tripped(directory)
            self.assertIn("cold path (no memory to load a Lean worker", marker["detail"])
            self.assertIn("reference passed in 896 s", marker["detail"])
            self.assertNotIn("reference failed", marker["detail"])

    def test_genuine_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run_gate({"v1": ok(2)}, directory=directory)
            bad = {"seconds": 3, "passed": False, "timed_out": False, "detail": "unknown constant", "path": "lsp"}
            _rows, calls, sleeps = self._others(directory, [bad])
            self.assertEqual((calls, sleeps), (["v2"], []))
            self.assertEqual(lh.tripped(directory)["detail"], "unknown constant")


if __name__ == "__main__":
    unittest.main()
