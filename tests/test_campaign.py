"""Offline tests for the campaign driver and comparison report: no Pi, Lean or network."""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

rc = importlib.import_module("arena.cli.campaigns")


def fixture_summary(proxy, spent=0.05, stop="model_stopped", errors=0, ideas=0, cache=80.0, overhead=10.0):
    best = {"candidate": "#2", "tokens": 50, "heartbeats": 100, "proxy": proxy} if proxy is not None else None
    return {
        "stop_reason": stop,
        "cost": {
            "spent_usd": spent,
            "bookkeeping_and_rejected_pct": overhead,
            "requests": 5,
            "retries": 1,
        },
        "progress": {"best_verified_candidate": best},
        "ideas_without_attempts": list(range(ideas)),
        "tools": {"error_total": errors, "errors": {"arena_probe": errors} if errors else {}},
        "cache": {"reuse_pct": cache},
    }


def write_run(root: Path, run_id: str, proxy_helper: bool):
    directory = root / run_id
    (directory / "proofs").mkdir(parents=True)
    events = [
        {"kind": "candidate", "candidate_id": "c1", "origin": "original"},
        {"kind": "candidate", "candidate_id": "c2", "origin": "model"},
    ]
    (directory / "ledger.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (directory / "proofs" / "c2.lean").write_text(
        ("lemma helper : True := trivial\n" if proxy_helper else "") + "theorem t : True := by trivial\n"
    )
    return directory


class PlanTests(unittest.TestCase):
    def test_dry_run_prints_plan_and_planned_spend_without_spending(self):
        out = io.StringIO()
        with (
            mock.patch("subprocess.run") as run,
            mock.patch.object(rc.engine, "problem", side_effect=lambda name: {"source": name, "version_info": []}),
            contextlib.redirect_stdout(out),
        ):
            code = rc.cli_execute(
                rc.CampaignOptions(
                    prefix="p",
                    rows="A.b,C.d",
                    models="deepseek-v4.1-flash",
                    limit_usd=0.10,
                    dry_run=True,
                )
            )
        self.assertEqual(code, 0)
        run.assert_not_called()
        text = out.getvalue()
        self.assertIn("6 runs", text)
        self.assertIn("planned spend $0.60", text)
        self.assertIn("--limit-usd 0.1", text)

    def test_replicates_are_sequential_and_ids_distinct(self):
        specs = rc.plan("p", ["A", "B"], ["deepseek-v4.1-flash"], 2)
        self.assertEqual([s["replicate"] for s in specs], [1, 2, 1, 2])
        self.assertEqual(len({s["run_id"] for s in specs}), 4)
        self.assertEqual(rc.worst_case_usd(specs, 0.1), 0.4)
        with self.assertRaises(ValueError):
            rc.plan("p", ["A"], ["not-a-model"], 1)

    def test_apostrophe_row_name_gives_valid_run_id(self):
        spec = rc.plan("p", ["fundamental_theorem'"], ["deepseek-v4.1-flash"], 1)[0]
        self.assertRegex(spec["run_id"], r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


class ColdVerificationTests(unittest.TestCase):
    def test_cold_verification_compiles_every_version_and_rejects_one_failure(self):
        from arena import campaign

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "proofs").mkdir()
            (directory / "proofs" / "c1.lean").write_text("theorem t : True := by trivial\n")
            history = [{"theorem": "T", "versions": ["v1", "v2"]}]
            calls = []

            def compile_version(_row, _proof, version, _commit, **_kwargs):
                calls.append(version)
                return {"passed": version == "v1", "heartbeats": 10, "lean": {"path": "cold"}}

            with (
                mock.patch.object(campaign, "run_dir", return_value=directory),
                mock.patch.object(campaign, "events", return_value=history),
                mock.patch.object(campaign.lean_health, "tripped", return_value=None),
                mock.patch.object(campaign, "lean_lock", return_value=contextlib.nullcontext()),
                mock.patch.object(campaign, "force_cold", return_value=contextlib.nullcontext()),
                mock.patch("arena.engine.problem", return_value={"name": "T", "proof_length": 1}),
                mock.patch("arena.engine.versions", return_value=[("v1", "c1"), ("v2", "c2")]),
                mock.patch("arena.engine.measure_version", return_value=("v1", "c1")),
                mock.patch("arena.engine.validate_proof", return_value=1),
                mock.patch("arena.engine.candidate_file", return_value={"start_line": 1}),
                mock.patch("arena.engine.compile_version", side_effect=compile_version),
                mock.patch("arena.scoring.metrics", return_value={}),
                mock.patch("arena.scoring.local_proxy", return_value=0.0),
                mock.patch.object(campaign, "_append"),
            ):
                result = campaign.cold_verify("run", {"id": "c1", "heartbeats": 10})

            self.assertEqual(calls, ["v1", "v2"])
            self.assertFalse(result["confirmed"])
            self.assertEqual(result["passed"], {"v1": True, "v2": False})


class GateTests(unittest.TestCase):
    def test_packet_failure_aborts_before_any_run(self):
        def packet(row):
            if row == "bad":
                raise ValueError("required sections absent: Goal")
            return "packet " + row

        with self.assertRaisesRegex(rc.CampaignAbort, "bad.*required sections absent"):
            rc.check_packets(["ok", "bad"], packet)
        self.assertEqual(set(rc.check_packets(["ok"], packet)), {"ok"})

    def test_preflight_failure_aborts_and_skip_is_explicit(self):
        with self.assertRaisesRegex(rc.CampaignAbort, "no receipt"):
            rc.check_preflight(
                ["m"], False, block_fn=lambda m: "no receipt", receipt_fn=lambda: "/nope", run_fn=lambda m: 1
            )
        self.assertEqual(rc.check_preflight(["m"], True), "skipped")

    def test_fresh_receipt_accepted_stale_reruns(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "r.json"
            receipt.write_text("{}")
            calls = []
            got = rc.check_preflight(
                ["m"], False, block_fn=lambda m: None, receipt_fn=lambda: receipt, run_fn=lambda m: calls.append(m) or 0
            )
            self.assertEqual((got, calls), ("fresh receipt", []))
            got = rc.check_preflight(
                ["m"],
                False,
                block_fn=lambda m: None,
                receipt_fn=lambda: receipt,
                run_fn=lambda m: calls.append(m) or 0,
                now_fn=lambda: 10**10,
            )
            self.assertEqual((got, len(calls)), ("ran preflight", 1))

    def test_main_aborts_without_creating_runs_when_gate_fails(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            with (
                mock.patch.object(rc, "RUNS", runs),
                mock.patch.object(rc.scheduler, "LOCK_PATH", runs / "campaign.lock"),
                mock.patch.object(rc, "check_packets", side_effect=rc.CampaignAbort("boom")),
                mock.patch.object(rc.engine, "problem", return_value={"source": "A", "version_info": []}),
                mock.patch.object(rc, "execute") as execute,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(err),
            ):
                code = rc.cli_execute(
                    rc.CampaignOptions(prefix="zz-offline-test", rows="A", models="deepseek-v4.1-flash", replicates=1)
                )
            self.assertFalse((runs / "zz-offline-test-campaign").exists())
            execute.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("aborted before any paid run", err.getvalue())


class ExecuteAndReportTests(unittest.TestCase):
    def test_execute_runs_one_subprocess_with_limit_and_reads_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = rc.plan("p", ["A"], ["deepseek-v4.1-flash"], 1)[0]
            directory = write_run(root, spec["run_id"], True)
            (directory / "run-config.json").write_text(json.dumps({"packet_sha256": "h"}))
            seen = []
            fake = lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0)  # noqa: E731
            with mock.patch.object(rc, "RUNS", root):
                row = rc.execute(
                    spec, 0.1, "high", ["--no-mcp"], root, "h", run_fn=fake, summary_fn=lambda d: fixture_summary(70.0)
                )
            self.assertEqual(len(seen), 1)
            self.assertIn("--limit-usd", seen[0])
            self.assertIn("0.1", seen[0])
            self.assertIn("--no-mcp", seen[0])
            self.assertTrue(row["packet_matches"])
            self.assertTrue(row["helpers"]["best_uses_helper"])

    def test_sequential_execution_order(self):
        order = []
        specs = rc.plan("p", ["A", "B"], ["deepseek-v4.1-flash"], 2)
        fake = lambda cmd, **kw: order.append(cmd[cmd.index("--run-id") + 1]) or SimpleNamespace(returncode=0)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            for spec in specs:
                rc.execute(spec, 0.1, "high", [], Path(tmp), "h", run_fn=fake, summary_fn=lambda d: None)
        self.assertEqual(order, [s["run_id"] for s in specs])

    def test_aggregation_over_replicates(self):
        specs = rc.plan("p", ["A"], ["deepseek-v4.1-flash"], 3)
        proxies = [60.0, 80.0, None]
        runs = [
            rc.run_row(
                s,
                fixture_summary(p, spent=0.05 * (i + 1), stop="finished" if i else "cap", errors=i, ideas=i),
                0,
                "h",
                "h",
            )
            for i, (s, p) in enumerate(zip(specs, proxies, strict=False))
        ]
        report = rc.aggregate(runs, {"A": "h"})
        group = report["groups"][0]
        self.assertEqual(group["best_proxy"], {"min": 60.0, "median": 70.0, "max": 80.0})
        self.assertEqual((group["replicates"], group["verified_runs"]), (3, 2))
        self.assertEqual((group["tool_errors"], group["ideas_never_attempted"]), (3, 3))
        self.assertEqual(group["stop_reasons"], {"cap": 1, "finished": 2})
        self.assertAlmostEqual(group["spent_usd"]["total"], 0.05 * 6)
        self.assertTrue(report["identical_packets"])
        self.assertEqual(group["single_route_runs"], 3)
        text = rc.render(report)
        self.assertIn("routes tried per run", text)
        self.assertIn("min/median/max: 60/70/80", text)
        self.assertIn("stop reasons", text)
        self.assertIn("route depth credited/explored", text)
        bad = rc.aggregate([rc.run_row(specs[0], fixture_summary(1.0), 0, "x", "h")], {"A": "h"})
        self.assertFalse(bad["identical_packets"])

    def test_route_depth_reaches_the_campaign_table(self):
        spec = rc.plan("p", ["A"], ["deepseek-v4.1-flash"], 1)[0]
        summary = fixture_summary(60.0) | {
            "route_progress": {"credited_routes": 2, "explored_routes": 1, "new_state_share": 0.5}
        }
        group = rc.aggregate([rc.run_row(spec, summary, 0, "h", "h")], {"A": "h"})["groups"][0]
        self.assertEqual((group["credited_routes"]["max"], group["new_state_share"]["max"]), (2, 0.5))

    def test_helper_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with_helper = write_run(Path(tmp), "a", True)
            plain = write_run(Path(tmp), "b", False)
            self.assertEqual(
                rc.helper_discovery(with_helper, "#2"), {"candidates_with_helpers": 1, "best_uses_helper": True}
            )
            self.assertEqual(
                rc.helper_discovery(plain, "#2"), {"candidates_with_helpers": 0, "best_uses_helper": False}
            )


if __name__ == "__main__":
    unittest.main()


class StdlibSourceTest(unittest.TestCase):
    def test_reads_lean_library_alias_from_toolchain(self):
        from arena import campaign as c

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".elan/toolchains/leanprover--lean4---v4.29.1/src/lean/Init/Data/X.lean"
            target.parent.mkdir(parents=True)
            target.write_text("theorem x : True := trivial\n")
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                self.assertIn("theorem x", c._stdlib_source("v4.29.1", ".lean-stdlib/lean/Init/Data/X.lean"))
                with self.assertRaises(ValueError):
                    c._stdlib_source("v4.29.1", ".lean-stdlib/lean/../secret.lean")
                with self.assertRaises(ValueError):
                    c._stdlib_source("v4.29.1", ".lean-stdlib/lean/Init/Missing.lean")


class LeanUnhealthyTests(unittest.TestCase):
    def test_campaign_continues_after_a_lean_unhealthy_row_and_reports_it(self):
        specs = rc.plan("p", ["A", "B"], ["deepseek-v4.1-flash"], 1)
        codes = {specs[0]["run_id"]: 75, specs[1]["run_id"]: 0}
        ran = []

        def fake(cmd, **kw):
            run_id = cmd[cmd.index("--run-id") + 1]
            ran.append(run_id)
            return SimpleNamespace(returncode=codes[run_id])

        def summary(directory):
            return (
                fixture_summary(None, spent=0.0, stop="lean_unhealthy") | {"lean": {"alarm": True}}
                if directory.name == specs[0]["run_id"]
                else fixture_summary(70.0)
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for spec in specs:
                write_run(root, spec["run_id"], False)
            out = io.StringIO()
            with mock.patch.object(rc, "RUNS", root), contextlib.redirect_stdout(out):
                runs = [rc.execute(spec, 0.1, "high", [], root, "h", run_fn=fake, summary_fn=summary) for spec in specs]
        self.assertEqual(ran, [s["run_id"] for s in specs])
        self.assertIn("skipped", out.getvalue())
        self.assertEqual([r["exit_code"] for r in runs], [75, 0])
        self.assertEqual([r["run_id"] for r in rc.lean_unhealthy_rows(runs)], [specs[0]["run_id"]])
        text = rc.render(rc.aggregate(runs, {"A": "h", "B": "h"}))
        self.assertIn("LEAN UNHEALTHY: 1 run(s)", text)
        self.assertIn(specs[0]["run_id"], text)

    def test_execute_cleans_up_around_each_run(self):
        spec = rc.plan("p", ["A"], ["deepseek-v4.1-flash"], 1)[0]
        calls = []
        hk = mock.Mock()
        hk.before_run.side_effect = lambda run_id: calls.append(("before", run_id))
        hk.after_run.side_effect = lambda run_id, directory: calls.append(("after", run_id))
        fake = lambda cmd, **kw: calls.append(("run",)) or SimpleNamespace(returncode=1)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rc, "RUNS", Path(tmp)):
            rc.execute(spec, 0.1, "high", [], Path(tmp), "h", run_fn=fake, summary_fn=lambda d: None, housekeeping=hk)
        self.assertEqual(calls, [("before", spec["run_id"]), ("run",), ("after", spec["run_id"])])

    def test_provider_unreachable_runs_are_listed_for_rerun(self):
        spec = rc.plan("p", ["A"], ["deepseek-v4.1-flash"], 1)[0]
        row = rc.run_row(spec, fixture_summary(None, spent=0.03, stop="provider_unreachable"), 1, "h", "h")
        self.assertEqual(rc.provider_unreachable_rows([row]), [row])
        text = rc.render(rc.aggregate([row], {"A": "h"}))
        self.assertIn(f"PROVIDER UNREACHABLE (rerun): 1 run(s): {row['run_id']} ($0.0300)", text)
