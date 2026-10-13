"""Fast, injected coverage for campaign scheduling policy."""

import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from arena import scheduler
from arena.cli import campaigns

provision = importlib.import_module("arena.cli.provision")


class OrderingTests(unittest.TestCase):
    def test_plan_groups_rows_and_keeps_replicates_balanced_per_row(self):
        groups = {"A1": "A", "B1": "B", "A2": "A"}
        rows = scheduler.plan_order(["A1", "B1", "A2"], groups.__getitem__)
        self.assertEqual(rows, ["A1", "A2", "B1"])
        models = list(campaigns.MODELS)
        specs = campaigns.plan("p", ["A1", "B1", "A2"], models, 2, groups.__getitem__)
        self.assertEqual(
            [(s["row"], s["replicate"], s["model"]) for s in specs],
            [(r, k, m) for r in rows for k in (1, 2) for m in models],
        )


class LockTests(unittest.TestCase):
    def test_lock_identifies_process_holder_and_releases_after_crash_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs" / "campaign.lock"
            lock = scheduler.CampaignLock(path)
            info = lock.acquire({"prefix": "owner-campaign", "argv": ["arena", "campaign"]})
            module_root = str(Path(__file__).resolve().parents[1])
            code = f"""\
import sys
sys.path.insert(0, {module_root!r})
from pathlib import Path
from arena.scheduler import CampaignLock, CampaignLocked
try:
    CampaignLock(Path({str(path)!r})).acquire({{'prefix': 'other'}})
except CampaignLocked as error:
    print(error)
else:
    raise SystemExit(4)
"""
            result = subprocess.run([sys.executable, "-I", "-c", code], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(info["pid"]), result.stdout)
            self.assertIn("owner-campaign", result.stdout)
            lock.release()
            self.assertIsNone(scheduler.holder(path))
            second = scheduler.CampaignLock(path)
            second.acquire({"prefix": "second"})
            second.release()


class ProvisionTests(unittest.TestCase):
    def test_provision_refuses_held_campaign_and_runs_after_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "campaign.lock"
            lock = scheduler.CampaignLock(path)
            lock.acquire({"prefix": "busy"})
            err = io.StringIO()
            with (
                mock.patch.object(scheduler, "LOCK_PATH", path),
                mock.patch.object(provision, "row_for", return_value={"name": "known"}),
                mock.patch.object(provision, "provision") as provision_fn,
                contextlib.redirect_stderr(err),
            ):
                code = provision.execute(provision.ProvisionOptions(row="known"))
                self.assertEqual(code, 1)
                provision_fn.assert_not_called()
            self.assertIn("busy", err.getvalue())
            with (
                mock.patch.object(scheduler, "LOCK_PATH", path),
                mock.patch.object(
                    provision, "row_for", return_value={"name": "known", "source": "src", "version_info": []}
                ),
                mock.patch.object(
                    provision,
                    "plan",
                    return_value=[
                        {
                            "version": "v1",
                            "commit": "commit",
                            "worktree": provision.ROOT / "ws",
                            "module": None,
                        }
                    ],
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(provision.execute(provision.ProvisionOptions(row="known", dry_run=True)), 0)
            lock.release()
            row = {"name": "known", "source": "src", "version_info": [{"v1": "commit"}]}
            with (
                mock.patch.object(scheduler, "LOCK_PATH", path),
                mock.patch.object(provision, "row_for", return_value=row),
                mock.patch.object(
                    provision,
                    "plan",
                    return_value=[
                        {"version": "v1", "commit": "commit", "worktree": provision.ROOT / "ws", "module": None}
                    ],
                ),
                mock.patch.object(provision, "LOGS", Path(tmp) / "logs"),
                mock.patch.object(provision, "provision") as provision_fn,
            ):
                self.assertEqual(provision.execute(provision.ProvisionOptions(row="known")), 0)
                provision_fn.assert_called_once()


class PrewarmTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.logged = []
        self.prewarm = scheduler.Prewarm(
            ["A", "B", "C"], 2, lead_s=10, now_fn=lambda: self.clock, warm_fn=lambda _: None, log=self.logged.append
        )
        self.a1, self.a2 = {"row": "A", "run_id": "a1"}, {"row": "A", "run_id": "a2"}

    def test_due_waits_for_all_starts_estimate_and_lead_window_then_fires_once(self):
        self.prewarm.started(self.a1)
        self.assertIsNone(self.prewarm.due(100))
        self.prewarm.started(self.a2)
        self.assertIsNone(self.prewarm.due(100))  # no runtime estimate
        self.assertIsNone(self.prewarm.due(130))
        self.assertEqual(self.logged, ["pre-warm B: no runtime estimate yet"])
        self.prewarm.finished(self.a1, 30)
        self.clock = 10
        self.assertIsNone(self.prewarm.due(19))
        self.assertEqual(self.prewarm.due(20), "B")
        self.assertIsNone(self.prewarm.due(20))

    def test_uses_earlier_row_estimate_and_never_fires_without_next_row(self):
        self.prewarm.finished(self.a1, 20)
        self.prewarm.finished(self.a2, 20)
        b1, b2 = {"row": "B", "run_id": "b1"}, {"row": "B", "run_id": "b2"}
        self.prewarm.started(b1)
        self.prewarm.started(b2)
        self.assertEqual(self.prewarm.due(10), "C")
        one = scheduler.Prewarm(["A"], 1, lead_s=1, now_fn=lambda: 0)
        only = {"row": "A", "run_id": "one"}
        one.started(only)
        self.assertIsNone(one.due(10))


class HoldAndResourceTests(unittest.TestCase):
    def test_row_projects_skips_unprovisioned_versions(self):
        row = {"version_info": [{"v1": "c1"}, {"v2": "c2"}]}

        def workspace(_row, version, _commit):
            if version == "v2":
                raise FileNotFoundError
            return Path("/workspace/v1")

        self.assertEqual(scheduler.row_projects(row, workspace_fn=workspace), [Path("/workspace/v1")])

    def test_holds_cover_unfinished_rows_and_narrow_after_row_finishes(self):
        sent = []
        keeper = scheduler.HoldKeeper("owner", 7, lambda payload, _timeout: sent.append(payload) or {"ok": True})
        keeper.start([("A", [Path("/a")]), ("B", [Path("/b")])])
        keeper.row_finished("A")
        keeper.close()
        self.assertEqual(sent[0]["projects"], ["/a", "/b"])
        self.assertEqual(sent[1]["projects"], ["/b"])
        self.assertEqual(sent[2]["op"], "unhold")

    def test_sampler_records_extrema_and_concurrent_run_peak(self):
        # Feed deterministic readings independently to each reader.
        sampler = scheduler.ResourceSampler(
            mem_fn=iter([8.0, 6.0]).__next__,
            load_fn=iter([1.0, 3.0]).__next__,
            swap_fn=iter([2.0, 4.0]).__next__,
            disk_fn=iter([90.0, 70.0]).__next__,
        )
        sampler.sample()
        sampler.sample()
        sampler.run_started()
        sampler.run_started()
        sampler.run_finished()
        observed = sampler.stop()
        self.assertEqual(
            observed,
            {
                "min_mem_available_gb": 6.0,
                "max_load1": 3.0,
                "max_swap_used_gb": 4.0,
                "min_disk_free_gb": 70.0,
                "max_concurrent_runs": 2,
                "samples": 2,
            },
        )


class CampaignRecordTests(unittest.TestCase):
    def test_campaign_json_has_settings_before_run_and_observations_after(self):
        class FakeSampler:
            def start(self):
                pass

            def run_started(self):
                pass

            def run_finished(self):
                pass

            def stop(self):
                return {"samples": 1, "max_concurrent_runs": 1}

        class FakeHousekeeping:
            def __init__(self, *_args):
                pass

            def before_run(self, _run_id):
                pass

            def after_run(self, _run_id, _directory):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {"name": "A", "source": "src", "version_info": [{"v1": "c1"}]}
            specs = campaigns.plan("fake", ["A"], [campaigns.MODELS[0]], 1)
            args = SimpleNamespace(
                prefix="fake",
                replicates=1,
                jobs=1,
                limit_usd=0.1,
                thinking="high",
                min_free_gb=8.0,
                cleanup_wait=1.0,
                prewarm_minutes=0,
                skip_preflight=True,
                json=True,
            )
            inspected = []

            def fake_run(*_args, **_kwargs):
                payload = json.loads((root / "fake-campaign" / "campaign.json").read_text())
                inspected.append(payload)
                run_id = _args[0][_args[0].index("--run-id") + 1]
                run_dir = root / run_id
                run_dir.mkdir()
                (run_dir / "run-config.json").write_text(json.dumps({"packet_sha256": "hash"}))
                return SimpleNamespace(returncode=0)

            with (
                mock.patch.object(campaigns, "RUNS", root),
                mock.patch.object(campaigns, "check_packets", return_value={"A": "hash"}),
                mock.patch.object(campaigns, "check_preflight", return_value="skipped"),
                mock.patch.object(campaigns, "Housekeeping", FakeHousekeeping),
                mock.patch.object(scheduler, "ResourceSampler", FakeSampler),
                mock.patch.object(scheduler, "mem_total_default", return_value=16.0),
                mock.patch.object(campaigns.engine, "problem", return_value=row),
                mock.patch.object(scheduler, "row_projects", return_value=[]),
                mock.patch.object(campaigns.lean_session, "ensure_service", return_value="/fake/socket"),
                mock.patch.object(campaigns.lean_session, "request", return_value={"ok": True}),
                mock.patch.dict(os.environ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = campaigns._run_campaign(
                    args,
                    ["A"],
                    [campaigns.MODELS[0]],
                    specs,
                    [],
                    {"pid": 42, "prefix": "fake", "started": "2026-10-13T00:00:00+00:00", "argv": []},
                    run_fn=fake_run,
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(inspected), 1)
            self.assertIn("settings", inspected[0])
            self.assertNotIn("observed", inspected[0])
            final = json.loads((root / "fake-campaign" / "campaign.json").read_text())
            self.assertIn("observed", final)


if __name__ == "__main__":
    unittest.main()
