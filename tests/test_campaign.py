"""Offline tests for the campaign driver and comparison report: no Pi, Lean or network."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import run_campaign as rc


def fixture_summary(proxy, spent=0.05, stop="model_stopped", errors=0, ideas=0, cache=80.0, overhead=10.0):
    best = {"candidate": "#2", "tokens": 50, "heartbeats": 100, "proxy": proxy} if proxy is not None else None
    return {"stop_reason": stop,
            "cost": {"spent_usd": spent, "unresolved_usd": 0.01, "bookkeeping_and_rejected_pct": overhead,
                     "requests": 5, "retries": 1},
            "progress": {"best_verified_candidate": best},
            "ideas_without_attempts": list(range(ideas)),
            "tools": {"error_total": errors, "errors": {"arena_probe": errors} if errors else {}},
            "cache": {"reuse_pct": cache}}


def write_run(root: Path, run_id: str, proxy_helper: bool):
    directory = root / run_id
    (directory / "proofs").mkdir(parents=True)
    events = [{"kind": "candidate", "candidate_id": "c1", "origin": "original"},
              {"kind": "candidate", "candidate_id": "c2", "origin": "model"}]
    (directory / "ledger.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (directory / "proofs" / "c2.lean").write_text(
        ("lemma helper : True := trivial\n" if proxy_helper else "") + "theorem t : True := by trivial\n")
    return directory


class PlanTests(unittest.TestCase):
    def test_dry_run_prints_plan_and_worst_case_without_spending(self):
        out = io.StringIO()
        with mock.patch("subprocess.run") as run, contextlib.redirect_stdout(out):
            code = rc.main(["--prefix", "p", "--rows", "A.b,C.d", "--models", "gpt-6-luna,deepseek-v4.1-flash",
                            "--cap", "0.10", "--dry-run"])
        self.assertEqual(code, 0)
        run.assert_not_called()
        text = out.getvalue()
        self.assertIn("12 runs", text)
        self.assertIn("worst case $1.20", text)
        self.assertIn("--hard-cap-usd 0.1", text)

    def test_replicates_are_sequential_and_ids_distinct(self):
        specs = rc.plan("p", ["A", "B"], ["gpt-6-luna", "qwen3.8-flash"], 2)
        self.assertEqual([s["replicate"] for s in specs], [1] * 4 + [2] * 4)
        self.assertEqual(len({s["run_id"] for s in specs}), 8)
        self.assertEqual(rc.worst_case_usd(specs, 0.1), 0.8)
        with self.assertRaises(ValueError):
            rc.plan("p", ["A"], ["not-a-model"], 1)

    def test_apostrophe_row_name_gives_valid_run_id(self):
        spec = rc.plan("p", ["fundamental_theorem'"], ["gpt-6-luna"], 1)[0]
        self.assertRegex(spec["run_id"], r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


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
            rc.check_preflight(["m"], False, block_fn=lambda m: "no receipt", receipt_fn=lambda: "/nope",
                               run_fn=lambda m: 1)
        self.assertEqual(rc.check_preflight(["m"], True), "skipped")

    def test_fresh_receipt_accepted_stale_reruns(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "r.json"
            receipt.write_text("{}")
            calls = []
            got = rc.check_preflight(["m"], False, block_fn=lambda m: None, receipt_fn=lambda: receipt,
                                     run_fn=lambda m: calls.append(m) or 0)
            self.assertEqual((got, calls), ("fresh receipt", []))
            got = rc.check_preflight(["m"], False, block_fn=lambda m: None, receipt_fn=lambda: receipt,
                                     run_fn=lambda m: calls.append(m) or 0, now_fn=lambda: 10**10)
            self.assertEqual((got, len(calls)), ("ran preflight", 1))

    def test_main_aborts_without_creating_runs_when_gate_fails(self):
        err = io.StringIO()
        with mock.patch.object(rc, "check_packets", side_effect=rc.CampaignAbort("boom")), \
                mock.patch.object(rc, "execute") as execute, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = rc.main(["--prefix", "zz-offline-test", "--rows", "A", "--models", "gpt-6-luna", "--replicates", "1"])
        self.assertEqual(code, 1)
        execute.assert_not_called()
        self.assertIn("aborted before any paid run", err.getvalue())


class ExecuteAndReportTests(unittest.TestCase):
    def test_execute_runs_one_subprocess_with_cap_and_reads_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = rc.plan("p", ["A"], ["gpt-6-luna"], 1)[0]
            directory = write_run(root, spec["run_id"], True)
            (directory / "run-config.json").write_text(json.dumps({"packet_sha256": "h"}))
            seen = []
            fake = lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0)  # noqa: E731
            with mock.patch.object(rc, "RUNS", root):
                row = rc.execute(spec, 0.1, "high", ["--no-mcp"], root, "h", run_fn=fake,
                                 summary_fn=lambda d: fixture_summary(70.0))
            self.assertEqual(len(seen), 1)
            self.assertIn("--hard-cap-usd", seen[0])
            self.assertIn("0.1", seen[0])
            self.assertIn("--no-mcp", seen[0])
            self.assertTrue(row["packet_matches"])
            self.assertTrue(row["helpers"]["best_uses_helper"])

    def test_sequential_execution_order(self):
        order = []
        specs = rc.plan("p", ["A", "B"], ["gpt-6-luna"], 2)
        fake = lambda cmd, **kw: order.append(cmd[cmd.index("--run-id") + 1]) or SimpleNamespace(returncode=0)  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            for spec in specs:
                rc.execute(spec, 0.1, "high", [], Path(tmp), "h", run_fn=fake, summary_fn=lambda d: None)
        self.assertEqual(order, [s["run_id"] for s in specs])

    def test_aggregation_over_replicates(self):
        specs = rc.plan("p", ["A"], ["gpt-6-luna"], 3)
        proxies = [60.0, 80.0, None]
        runs = [rc.run_row(s, fixture_summary(p, spent=0.05 * (i + 1), stop="finished" if i else "cap",
                                              errors=i, ideas=i), 0, "h", "h")
                for i, (s, p) in enumerate(zip(specs, proxies))]
        report = rc.aggregate(runs, {"A": "h"})
        group = report["groups"][0]
        self.assertEqual(group["best_proxy"], {"min": 60.0, "median": 70.0, "max": 80.0})
        self.assertEqual((group["replicates"], group["verified_runs"]), (3, 2))
        self.assertEqual((group["tool_errors"], group["ideas_never_attempted"]), (3, 3))
        self.assertEqual(group["stop_reasons"], {"cap": 1, "finished": 2})
        self.assertAlmostEqual(group["all_call_cost_usd"]["total"], 0.05 * 6 + 0.03)
        self.assertTrue(report["identical_packets"])
        self.assertEqual(group["single_route_runs"], 3)
        text = rc.render(report)
        self.assertIn("routes tried per run", text)
        self.assertIn("min/median/max: 60/70/80", text)
        self.assertIn("stop reasons", text)
        bad = rc.aggregate([rc.run_row(specs[0], fixture_summary(1.0), 0, "x", "h")], {"A": "h"})
        self.assertFalse(bad["identical_packets"])

    def test_helper_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with_helper = write_run(Path(tmp), "a", True)
            plain = write_run(Path(tmp), "b", False)
            self.assertEqual(rc.helper_discovery(with_helper, "#2"), {"candidates_with_helpers": 1, "best_uses_helper": True})
            self.assertEqual(rc.helper_discovery(plain, "#2"), {"candidates_with_helpers": 0, "best_uses_helper": False})


if __name__ == "__main__":
    unittest.main()
