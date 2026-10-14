import json
import tempfile
import unittest
from pathlib import Path

from arena import summary


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def assistant(calls: list[tuple[str, str]], read: int, write_tokens: int, stop: str = "toolUse") -> dict:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "stopReason": stop,
            "usage": {
                "totalTokens": 100 + read + write_tokens,
                "input": 100,
                "cacheRead": read,
                "cacheWrite": write_tokens,
            },
            "content": [{"type": "toolCall", "id": cid, "name": name} for cid, name in calls],
        },
    }


def result(call_id: str, name: str, text: dict, error: bool = False) -> dict:
    return {
        "type": "tool_execution_end",
        "toolCallId": call_id,
        "toolName": name,
        "isError": error,
        "result": {"content": [{"type": "text", "text": json.dumps(text)}]},
    }


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "run-1"
        (self.dir / "proofs").mkdir(parents=True)
        for name, text in (("ref", "a\nb\nc\nd\ne\n"), ("local", "a\nb\nX\nd\ne\n"), ("struct", "p\nq\nr\ns\nt\nu\n")):
            (self.dir / "proofs" / f"{name}.lean").write_text(text)
        write(
            self.dir / "run-config.json" if False else self.dir / "ledger.jsonl",
            [
                {"kind": "init", "ts": 100.0, "theorem": "T"},
                {"kind": "candidate", "candidate_id": "ref", "origin": "reference", "parents": []},
                {"kind": "candidate", "candidate_id": "local", "origin": "model", "parents": ["ref"]},
                {"kind": "candidate", "candidate_id": "struct", "origin": "model", "parents": ["ref"]},
                {
                    "kind": "evaluation",
                    "ts": 110.0,
                    "candidate_id": "local",
                    "mode": "fast",
                    "result": {"tokens": 90, "heartbeat": 400, "metrics": {"compiled": True, "estimated_proxy": 55.0}},
                },
                {
                    "kind": "evaluation",
                    "ts": 130.0,
                    "candidate_id": "struct",
                    "mode": "full",
                    "result": {
                        "tokens": 70,
                        "heartbeat": 800,
                        "metrics": {"compiled": True, "proxy": 60.5, "axes": {"compat": {"passed": 1, "total": 1}}},
                    },
                },
                {
                    "kind": "evaluation",
                    "ts": 140.0,
                    "candidate_id": "struct",
                    "mode": "fast",
                    "result": {"tokens": None, "heartbeat": None, "metrics": {"compiled": False}},
                },
            ],
        )
        (self.dir / "run-config.json").write_text(
            json.dumps(
                {"theorem": "T", "model": "m", "hard_cap_usd": 0.1, "thinking": "high", "skill": {"sha256": "abc"}}
            )
        )
        write(
            self.dir / "cost-ledger.jsonl",
            [
                {"kind": "settle", "id": "1", "usd": 0.01, "usage_known": True},
                {"kind": "settle", "id": "2", "usd": 0.02, "usage_known": True},
                {"kind": "settle", "id": "3", "usd": 0.03, "usage_known": True},
                {"kind": "settle", "id": "4", "usd": 0, "usage_known": False},
                {"kind": "settle", "id": "5", "usd": 0.04, "usage_known": True},
                {"kind": "cache_alarm", "id": "5"},
                {"kind": "control", "continuations": 1, "stop": "plateau"},
            ],
        )
        write(
            self.dir / "events.jsonl",
            [
                assistant([("a", "finish")], 0, 3000),
                result("a", "finish", {"ok": True}),
                assistant([("b", "compile")], 3000, 100),
                result("b", "compile", {"ok": True}),
                assistant([("c", "read")], 3100, 50),
                result("c", "read", {"ok": False, "error": "bad range"}),
                assistant([], 3150, 20, "stop"),
            ],
        )

    def test_turns_are_classified_and_costed_from_the_journal(self):
        data = summary.build_summary(self.dir)
        kinds = data["cost"]["by_turn_type"]
        self.assertEqual(
            {k: v["requests"] for k, v in kinds.items()},
            {"bookkeeping": 1, "compile": 1, "rejected": 1, "reasoning": 1},
        )
        self.assertAlmostEqual(kinds["bookkeeping"]["usd"], 0.01)
        self.assertAlmostEqual(kinds["rejected"]["usd"], 0.03)
        self.assertAlmostEqual(data["cost"]["spent_usd"], 0.10)
        self.assertEqual(data["cost"]["overshoot_usd"], 0.0)
        self.assertEqual(data["cost"]["usd_per_evaluation"], round(0.10 / 3, 6))
        self.assertEqual(data["cost"]["bookkeeping_and_rejected_pct"], 40.0)
        self.assertEqual(data["stop_reason"], "plateau")
        self.assertEqual((data["thinking"], data["skill"]), ("high", "abc"))

    def test_best_verified_requires_every_listed_version(self):
        cases = [
            ("one-version", "full", {"passed": 1, "total": 1}, True),
            ("partial-full", "full", {"passed": 1, "total": 3}, False),
            ("fast", "fast", {"passed": 1, "total": 3}, False),
        ]
        for name, mode, compat, verified in cases:
            with self.subTest(name=name):
                write(
                    self.dir / "ledger.jsonl",
                    [
                        {"kind": "init", "ts": 100.0, "theorem": "T"},
                        {"kind": "candidate", "candidate_id": "candidate", "origin": "model", "parents": []},
                        {
                            "kind": "evaluation",
                            "ts": 110.0,
                            "candidate_id": "candidate",
                            "mode": mode,
                            "result": {
                                "tokens": 90,
                                "heartbeat": 400,
                                "metrics": {"compiled": True, "proxy": 55.0, "axes": {"compat": compat}},
                            },
                        },
                    ],
                )
                result = summary.build_summary(self.dir)["progress"]["best_verified_candidate"]
                self.assertEqual(result is not None, verified)

    def test_rejection_classification_survives_appended_status_text(self):
        rows = [
            assistant([("x", "compile")], 0, 20),
            {
                **result("x", "compile", {"ok": False, "error": "invalid"}),
                "result": {
                    "content": [{"type": "text", "text": '{"ok":false,"error":"invalid"}\n[arena] best verified: #1'}]
                },
            },
        ]
        turns = summary._turns(rows, [{"usd": 0.01}])
        self.assertEqual(turns[0]["kind"], "rejected")

    def test_cache_kpis_alarms_and_tool_errors(self):
        data = summary.build_summary(self.dir)
        self.assertEqual(data["cache"]["alarms"], 1)
        self.assertEqual(
            data["cache"]["per_request"], [[0, 3000, 100], [3000, 100, 100], [3100, 50, 100], [3150, 20, 100]]
        )
        # Hit rate = cache_read / (input + cache_read + cache_write), not read / (read + write).
        self.assertEqual(data["cache"]["reuse_pct"], round(100 * 9250 / (9250 + 3170 + 400), 1))
        self.assertEqual(data["cache"]["input_tokens"], 400)
        self.assertIsNone(data["cache"]["savings_pct"])  # these settles carry no component costs
        self.assertEqual(data["tools"]["errors"], {"read": 1})

    def test_deepseek_hit_rate_and_cache_cost_savings(self):
        # DeepSeek never writes cache: read/(read+write) would be 100%; the real hit rate is 79%.
        self.assertEqual(summary.hit_rate_pct(7900, 0, 2100), 79.0)
        self.assertIsNone(summary.hit_rate_pct(0, 0, 0))
        events = [assistant([("a", "finish")], 7900, 0)]
        events[0]["message"]["usage"]["input"] = 2100
        settle = {
            "usd": 0.0004,
            "usage_known": True,
            "tokens": {"input": 2100, "cache_read": 7900, "cache_write": 0},
            "ledger_components_usd": {"input": 2100 * 0.15e-6, "cacheRead": 7900 * 0.003e-6, "cacheWrite": 0.0},
        }
        turns = summary._turns(events, [settle])
        saved = summary.cache_savings_pct(turns)
        self.assertAlmostEqual(saved, 100 * (1 - (2100 * 0.15 + 7900 * 0.003) / (10000 * 0.15)), places=1)
        self.assertIsNone(summary.cache_savings_pct([]))

    def test_progress_best_per_axis_and_timeline(self):
        data = summary.build_summary(self.dir)
        best = data["progress"]["best"]
        self.assertEqual(best["tokens"], {"value": 70, "candidate": "#3"})
        self.assertEqual(best["heartbeats"], {"value": 400, "candidate": "#2"})
        self.assertEqual(best["proxy"], {"value": 60.5, "candidate": "#3"})
        self.assertEqual(best["estimated_proxy"], {"value": 55.0, "candidate": "#2"})
        self.assertEqual([row["t"] for row in data["progress"]["timeline"]], [10.0, 30.0, 40.0])
        self.assertEqual(
            data["progress"]["best_verified_candidate"],
            {"candidate": "#3", "tokens": 70, "heartbeats": 800, "proxy": 60.5},
        )
        self.assertIn("best verified candidate: #3 proxy 60.5 (70 tok, 800 HB)", summary.render_text(data))

    def test_routes_are_summarised_from_the_ledger(self):
        with (self.dir / "ledger.jsonl").open("a") as handle:
            for proof_id, route in (("ref", "r1"), ("local", "r1"), ("struct", "r2")):
                handle.write(
                    json.dumps(
                        {
                            "kind": "route",
                            "proof_id": proof_id,
                            "route": route,
                            "label": "label " + route,
                            "fingerprint": {},
                        }
                    )
                    + "\n"
                )
        data = summary.build_summary(self.dir)
        rows = {row["route"]: row for row in data["routes"]}
        self.assertEqual((rows["r1"]["attempts"], rows["r1"]["original"]), (1, True))
        self.assertEqual(
            (rows["r2"]["attempts"], rows["r2"]["best_proxy"], rows["r2"]["best_candidate"]), (1, 60.5, "#3")
        )
        self.assertIn('routes tried: r1 "label r1" [the original proof\'s route]: 1 attempt', summary.render_text(data))
        self.assertEqual(
            data["route_progress"]["credited_routes"], 0
        )  # these events predate credit and carry no kernel source
        self.assertIn("route depth: 0 credited routes, ", summary.render_text(data))

    def test_coherent_best_metrics_use_cold_submission_heartbeats(self):
        (self.dir / "submission.json").write_text(
            json.dumps({"candidate": "#3", "tokens": 70, "heartbeats": 801, "proxy": 60.5, "session_heartbeats": 800})
        )
        best = summary.build_summary(self.dir)["progress"]["best_verified_candidate"]
        self.assertEqual(best, {"candidate": "#3", "tokens": 70, "heartbeats": 801, "proxy": 60.5})

    def test_state_and_finish_requests_are_bookkeeping(self):
        data = summary._turns(
            [
                assistant([("s", "goal")], 0, 20),
                result("s", "goal", {"ok": True}),
                assistant([("f", "finish")], 20, 20),
                result("f", "finish", {"ok": True}),
            ],
            [{"usd": 0.01}, {"usd": 0.01}],
        )
        self.assertEqual([turn["kind"] for turn in data], ["bookkeeping", "bookkeeping"])

    def test_old_ledger_idea_and_tool_call_load_as_an_other_call(self):
        with (self.dir / "ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "idea", "id": "old", "title": "Historical", "status": "active"}) + "\n")
        old_tool = "arena_" + "idea"
        write(
            self.dir / "events.jsonl",
            [assistant([("old", old_tool)], 0, 1), result("old", old_tool, {"ok": True})],
        )
        data = summary.build_summary(self.dir)
        self.assertNotIn("ideas", data)
        self.assertEqual(data["tools"]["calls"][old_tool], 1)
        self.assertEqual(data["cost"]["by_turn_type"]["context"]["requests"], 1)

    def test_trace_accounting_reports_retries_results_and_post_best_spend(self):
        with (self.dir / "cost-ledger.jsonl").open("a") as handle:
            handle.write(
                json.dumps({"kind": "settle", "id": "post-best", "usd": 0.005, "usage_known": True, "ts": 131000})
                + "\n"
            )
        write(
            self.dir / "trace-journal.jsonl",
            [
                {"kind": "request", "id": "r1", "retry_of": None, "ts": 131000},
                {"kind": "request", "id": "r2", "retry_of": "r1", "ts": 132000},
            ],
        )
        data = summary.build_summary(self.dir)
        self.assertEqual(
            (
                data["cost"]["requests"],
                data["cost"]["priced_responses"],
                data["cost"]["retries"],
                data["tools"]["results"],
            ),
            (2, 4, 1, 3),
        )
        self.assertEqual(data["cost"]["requests_after_best"], 2)
        self.assertAlmostEqual(data["cost"]["spent_after_best_usd"], 0.005)

    def test_edits_split_into_local_and_structural(self):
        edits = summary.build_summary(self.dir)["edits"]
        self.assertEqual((edits["local"], edits["structural"]), (1, 1))

    def test_cost_report_is_rebuilt_when_pi_never_wrote_one(self):
        report = summary.cost_report_from_ledger(self.dir)
        self.assertAlmostEqual(report["spent_usd"], 0.10)
        self.assertEqual(report["written_by"], "runner_ledger_reconstruction")

    def test_overshoot_is_reported(self):
        write(
            self.dir / "cost-ledger.jsonl",
            [
                {"kind": "settle", "id": "1", "usd": 0.108, "usage_known": True},
            ],
        )
        data = summary.write_summary(self.dir)
        self.assertAlmostEqual(data["cost"]["overshoot_usd"], 0.008)
        self.assertIn("overshoot $0.0080", (self.dir / "summary.txt").read_text())

    LEDGER = (
        {"kind": "settle", "id": "a", "usd": 0.0100, "usage_known": True},
        {"kind": "settle", "id": "b", "usd": 0.0090, "usage_known": True},
        {"kind": "settle", "id": "slow", "usd": 0, "usage_known": False},
    )

    def session_with_compaction(self, usd: float) -> None:
        (self.dir / "session").mkdir()
        write(
            self.dir / "session" / "s.jsonl",
            [
                {"type": "message", "message": {"role": "assistant", "usage": {"cost": {"total": 0.0100}}}},
                {"type": "compaction", "usage": {"cost": {"total": usd}}},
                {"type": "message", "message": {"role": "assistant", "usage": {"cost": {"total": 0.0090}}}},
            ],
        )

    def test_spend_is_the_sum_of_settle_rows_and_never_below_the_session_total(self):
        spend = summary.ledger_spend(list(self.LEDGER), 0.0258)
        self.assertEqual(spend["ledger_settled_usd"], 0.019)
        self.assertAlmostEqual(spend["gap_usd"], 0.0068)
        self.assertAlmostEqual(spend["spent_usd"], 0.0258)
        self.assertEqual(summary.ledger_spend(list(self.LEDGER))["spent_usd"], 0.019)

    def test_a_compaction_settle_is_counted_and_closes_the_gap(self):
        ledger = [
            *self.LEDGER,
            {"kind": "settle", "id": "summary", "usd": 0.0068, "usage_known": True, "source": "compaction"},
        ]
        spend = summary.ledger_spend(ledger, 0.0258)
        self.assertEqual(spend["gap_usd"], 0)
        self.assertEqual((spend["compaction_settles"], spend["compaction_settled_usd"]), (1, 0.0068))

    def test_summary_spend_and_turns_include_compaction_that_the_ledger_never_settled(self):
        write(self.dir / "cost-ledger.jsonl", list(self.LEDGER))
        (self.dir / "cost.json").unlink(missing_ok=True)
        self.session_with_compaction(0.0068)
        cost = summary.build_summary(self.dir)["cost"]
        self.assertAlmostEqual(cost["spent_usd"], 0.0258)
        self.assertEqual(cost["by_turn_type"]["compaction"], {"requests": 1, "usd": 0.0068})
        self.assertEqual(cost["reconciliation"]["gap_usd"], 0.0068)
        summary.write_summary(self.dir)
        self.assertIn("SPEND GAP", (self.dir / "summary.txt").read_text())

    def test_compaction_settles_do_not_shift_the_per_turn_pairing(self):
        settles = [
            {"kind": "settle", "id": "s", "usd": 0.5, "usage_known": True, "source": "compaction"},
            {"kind": "settle", "id": "a", "usd": 0.01, "usage_known": True},
        ]
        turns = summary._turns([assistant([("c1", "goal")], 0, 0)], settles)
        self.assertEqual([t["usd"] for t in turns], [0.01])


class StopReasonTests(unittest.TestCase):
    def test_one_stop_reason_for_summary_and_campaign(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            write(directory / "ledger.jsonl", [{"kind": "init", "ts": 1.0, "theorem": "T"}])
            self.assertEqual(summary.build_summary(directory)["stop_reason"], "model_stopped")
            written = summary.write_summary(directory, "interrupted")
            self.assertEqual(written["stop_reason"], "interrupted")
            # a later rebuild (the campaign report) agrees with summary.txt
            self.assertEqual(summary.build_summary(directory)["stop_reason"], "interrupted")
            self.assertIn("stop interrupted", (directory / "summary.txt").read_text())
            summary.write_summary(directory)  # a resumed run that ends normally clears the note
            self.assertEqual(summary.build_summary(directory)["stop_reason"], "model_stopped")

    def test_the_cap_is_read_from_the_new_or_the_old_run_config_key(self):
        self.assertEqual(summary.configured_cap({"limit_usd": 0.5, "soft_cap_usd": 0.4}), 0.5)
        self.assertEqual(summary.configured_cap({"soft_cap_usd": 0.5}), 0.5)
        self.assertEqual(summary.configured_cap({"hard_cap_usd": 0.4}), 0.4)
        self.assertEqual(summary.configured_cap({"soft_cap_usd": 0.5, "hard_cap_usd": 3}), 0.5)

    def test_route_depth_text_shows_credited_routes_before_any_attempt(self):
        text = summary.route_depth_text({"credited_routes": 0, "explored_routes": 1, "new_state_share": None})
        self.assertIn("0 credited routes, 1 explored", text)


class LeanStatsTests(unittest.TestCase):
    @staticmethod
    def entry(seconds, path="session", error=None, warm_kept=False):
        return {
            "passed": error is None,
            "lean": {"path": path, "seconds": seconds, "warm_kept": warm_kept},
            **({"error": error} if error else {}),
        }

    def test_percentiles_timeout_rate_warm_and_cold_counts(self):
        ledger = [
            {"kind": "probe", "result": {"compat": {"v": self.entry(1.0, warm_kept=True)}}},
            {"kind": "probe", "result": {"compat": {"v": self.entry(3.0)}}},
            {"kind": "evaluation", "trigger": "model", "result": {"compat": {"v": self.entry(9.0, path="cold")}}},
            {
                "kind": "evaluation",
                "trigger": "auto",
                "result": {"compat": {"v": self.entry(500.0, error="Lean timed out after 180 seconds")}},
            },
        ]
        lean = summary.lean_stats(ledger)
        self.assertEqual((lean["checks"], lean["p50_seconds"], lean["p95_seconds"]), (3, 3.0, 9.0))
        self.assertEqual((lean["timeouts"], lean["warm_kept"], lean["cold_path"], lean["alarm"]), (0, 1, 1, False))
        self.assertIn("3 model-lane checks", summary.lean_text(lean))
        self.assertNotIn("ALARM", summary.lean_text(lean))

    def test_alarm_on_timeout_rate_or_unhealthy_stop(self):
        slow = [
            {"kind": "probe", "result": {"compat": {"v": self.entry(180.0, error="Lean timed out after 180 seconds")}}}
        ] * 2 + [{"kind": "probe", "result": {"compat": {"v": self.entry(1.0)}}}] * 3
        lean = summary.lean_stats(slow)
        self.assertEqual((lean["timeout_rate"], lean["alarm"]), (0.4, True))
        self.assertIn("ALARM", summary.lean_text(lean))
        self.assertTrue(summary.lean_stats([], None, "lean_unhealthy")["alarm"])
        self.assertFalse(summary.lean_stats([])["alarm"])

    def test_summary_json_and_text_carry_the_lean_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "r"
            directory.mkdir()
            write(
                directory / "ledger.jsonl",
                [
                    {"kind": "init", "ts": 1.0, "theorem": "T"},
                    {"kind": "probe", "proof_id": "p", "result": {"compat": {"v": self.entry(2.0)}}},
                ],
            )
            (directory / "run-config.json").write_text(json.dumps({"theorem": "T", "model": "m", "hard_cap_usd": 0.1}))
            data = summary.write_summary(directory, "lean_unhealthy")
            self.assertTrue(data["lean"]["alarm"])
            self.assertEqual(json.loads((directory / "summary.json").read_text())["lean"]["checks"], 1)
            self.assertIn("lean: 1 model-lane checks", (directory / "summary.txt").read_text())
            self.assertIn("ALARM", (directory / "summary.txt").read_text())

    def test_v7_compile_counters_and_new_bookkeeping_views(self):
        def call(turn, name, arguments):
            return {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "usage": {"totalTokens": 1, "input": 1, "cacheRead": 0, "cacheWrite": 0},
                    "content": [{"type": "toolCall", "id": turn, "name": name, "arguments": arguments}],
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write(
                directory / "events.jsonl",
                [
                    call("a", "read", {"node": "n1", "view": "source"}),
                    call("b", "goal", {"node": "n1", "hole": "h1"}),
                    call("c", "read", {"view": "map"}),
                    call("d", "compile", {"drafts": ["by trivial"]}),
                    call("e", "compile", {"splice": {"steps": "s1", "text": "trivial"}}),
                ],
            )
            data = summary.build_summary(directory)
        self.assertEqual(data["tools"]["compile_calls"], 2)
        self.assertEqual(data["tools"]["compile_calls_with_operation"], 1)
        self.assertEqual(data["tools"]["calls_before_first_compile"], 3)
        turns = summary._turns([call("f", "read", {"view": "source"}), call("g", "read", {"view": "map"})], [])
        self.assertEqual([turn["kind"] for turn in turns], ["context", "bookkeeping"])


if __name__ == "__main__":
    unittest.main()
