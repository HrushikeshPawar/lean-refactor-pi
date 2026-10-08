import json
import tempfile
import unittest
from pathlib import Path

from arena import summary


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def assistant(calls: list[tuple[str, str]], read: int, write_tokens: int, stop: str = "toolUse") -> dict:
    return {"type": "message_end", "message": {"role": "assistant", "stopReason": stop,
            "usage": {"totalTokens": 100 + read + write_tokens, "cacheRead": read, "cacheWrite": write_tokens},
            "content": [{"type": "toolCall", "id": cid, "name": name} for cid, name in calls]}}


def result(call_id: str, name: str, text: dict, error: bool = False) -> dict:
    return {"type": "tool_execution_end", "toolCallId": call_id, "toolName": name, "isError": error,
            "result": {"content": [{"type": "text", "text": json.dumps(text)}]}}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "run-1"
        (self.dir / "proofs").mkdir(parents=True)
        for name, text in (("ref", "a\nb\nc\nd\ne\n"), ("local", "a\nb\nX\nd\ne\n"), ("struct", "p\nq\nr\ns\nt\nu\n")):
            (self.dir / "proofs" / f"{name}.lean").write_text(text)
        write(self.dir / "run-config.json" if False else self.dir / "ledger.jsonl", [
            {"kind": "init", "ts": 100.0, "theorem": "T"},
            {"kind": "candidate", "candidate_id": "ref", "origin": "reference", "parents": []},
            {"kind": "idea", "id": "i1", "title": "Idea", "status": "active"},
            {"kind": "candidate", "candidate_id": "local", "origin": "model", "parents": ["ref"], "idea_id": "i1"},
            {"kind": "candidate", "candidate_id": "struct", "origin": "model", "parents": ["ref"], "idea_id": "i1"},
            {"kind": "evaluation", "ts": 110.0, "candidate_id": "local", "mode": "fast", "result": {
                "tokens": 90, "heartbeat": 400, "metrics": {"compiled": True, "estimated_proxy": 55.0}}},
            {"kind": "evaluation", "ts": 130.0, "candidate_id": "struct", "mode": "full", "result": {
                "tokens": 70, "heartbeat": 800, "metrics": {"compiled": True, "proxy": 60.5}}},
            {"kind": "evaluation", "ts": 140.0, "candidate_id": "struct", "mode": "fast", "result": {
                "tokens": None, "heartbeat": None, "metrics": {"compiled": False}}},
        ])
        (self.dir / "run-config.json").write_text(json.dumps(
            {"theorem": "T", "model": "m", "hard_cap_usd": 0.1, "thinking": "high", "skill": {"sha256": "abc"}}))
        write(self.dir / "cost-ledger.jsonl", [
            {"kind": "reserve", "id": "1", "usd": 1}, {"kind": "settle", "id": "1", "usd": 0.01, "usage_known": True},
            {"kind": "reserve", "id": "2", "usd": 1}, {"kind": "settle", "id": "2", "usd": 0.02, "usage_known": True},
            {"kind": "reserve", "id": "3", "usd": 1}, {"kind": "settle", "id": "3", "usd": 0.03, "usage_known": True},
            {"kind": "reserve", "id": "4", "usd": 1}, {"kind": "release", "id": "4", "usage_known": False},
            {"kind": "reserve", "id": "5", "usd": 1}, {"kind": "settle", "id": "5", "usd": 0.04, "usage_known": True},
            {"kind": "cache_alarm", "id": "5"},
            {"kind": "control", "continuations": 1, "stop": "plateau"},
        ])
        write(self.dir / "events.jsonl", [
            assistant([("a", "arena_idea")], 0, 3000),
            result("a", "arena_idea", {"ok": True}),
            assistant([("b", "arena_evaluate")], 3000, 100),
            result("b", "arena_evaluate", {"ok": True}),
            assistant([("c", "arena_source")], 3100, 50),
            result("c", "arena_source", {"ok": False, "error": "bad range"}),
            assistant([], 3150, 20, "stop"),
        ])

    def test_turns_are_classified_and_costed_from_the_journal(self):
        data = summary.build_summary(self.dir)
        kinds = data["cost"]["by_turn_type"]
        self.assertEqual({k: v["requests"] for k, v in kinds.items()},
                         {"bookkeeping": 1, "compile": 1, "rejected": 1, "reasoning": 1})
        self.assertAlmostEqual(kinds["bookkeeping"]["usd"], 0.01)
        self.assertAlmostEqual(kinds["rejected"]["usd"], 0.03)
        self.assertAlmostEqual(data["cost"]["spent_usd"], 0.10)
        self.assertEqual(data["cost"]["overshoot_usd"], 0.0)
        self.assertEqual(data["cost"]["usd_per_evaluation"], round(0.10 / 3, 6))
        self.assertEqual(data["cost"]["bookkeeping_and_rejected_pct"], 40.0)
        self.assertEqual(data["stop_reason"], "plateau")
        self.assertEqual((data["thinking"], data["skill"]), ("high", "abc"))

    def test_rejection_classification_survives_appended_status_text(self):
        rows = [assistant([("x", "arena_evaluate")], 0, 20),
                {**result("x", "arena_evaluate", {"ok": False, "error": "invalid"}),
                 "result": {"content": [{"type": "text", "text": '{"ok":false,"error":"invalid"}\n[arena] best verified: #1'}]}}]
        turns = summary._turns(rows, [{"usd": 0.01}])
        self.assertEqual(turns[0]["kind"], "rejected")

    def test_cache_kpis_alarms_and_tool_errors(self):
        data = summary.build_summary(self.dir)
        self.assertEqual(data["cache"]["alarms"], 1)
        self.assertEqual(data["cache"]["per_request"], [[0, 3000], [3000, 100], [3100, 50], [3150, 20]])
        self.assertEqual(data["cache"]["reuse_pct"], round(100 * 9250 / (9250 + 3170), 1))
        self.assertEqual(data["tools"]["errors"], {"arena_source": 1})

    def test_progress_best_per_axis_and_timeline(self):
        data = summary.build_summary(self.dir)
        best = data["progress"]["best"]
        self.assertEqual(best["tokens"], {"value": 70, "candidate": "#3"})
        self.assertEqual(best["heartbeats"], {"value": 400, "candidate": "#2"})
        self.assertEqual(best["proxy"], {"value": 60.5, "candidate": "#3"})
        self.assertEqual(best["estimated_proxy"], {"value": 55.0, "candidate": "#2"})
        self.assertEqual([row["t"] for row in data["progress"]["timeline"]], [10.0, 30.0, 40.0])
        self.assertEqual(data["progress"]["best_verified_candidate"],
                         {"candidate": "#3", "tokens": 70, "heartbeats": 800, "proxy": 60.5})
        self.assertIn("best verified candidate: #3 proxy 60.5 (70 tok, 800 HB)", summary.render_text(data))

    def test_probe_is_a_linked_idea_attempt(self):
        with (self.dir / "ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "probe", "proof_id": "draft-1", "idea_id": "i1",
                                     "result": {"ok": False, "error": "failed skeleton"}}) + "\n")
        ideas = summary.build_summary(self.dir)["ideas"]
        self.assertEqual(ideas[0]["attempts"], 3)
        self.assertEqual(ideas[0]["probes"], 1)

    def test_coherent_best_metrics_use_cold_submission_heartbeats(self):
        (self.dir / "submission.json").write_text(json.dumps(
            {"candidate": "#3", "tokens": 70, "heartbeats": 801, "proxy": 60.5,
             "session_heartbeats": 800}))
        best = summary.build_summary(self.dir)["progress"]["best_verified_candidate"]
        self.assertEqual(best, {"candidate": "#3", "tokens": 70, "heartbeats": 801, "proxy": 60.5})

    def test_state_and_finish_requests_are_bookkeeping(self):
        data = summary._turns([
            assistant([("s", "arena_state")], 0, 20), result("s", "arena_state", {"ok": True}),
            assistant([("f", "arena_finish")], 20, 20), result("f", "arena_finish", {"ok": True}),
        ], [{"usd": 0.01}, {"usd": 0.01}])
        self.assertEqual([turn["kind"] for turn in data], ["bookkeeping", "bookkeeping"])

    def test_trace_accounting_reports_retries_results_idle_ideas_and_post_best_spend(self):
        with (self.dir / "ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "idea", "id": "unused", "title": "Untried",
                                     "status": "active"}) + "\n")
        with (self.dir / "cost-ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "settle", "id": "post-best", "usd": 0.005,
                                     "usage_known": True, "ts": 131000}) + "\n")
        write(self.dir / "trace-journal.jsonl", [
            {"kind": "request", "id": "r1", "retry_of": None, "ts": 131000},
            {"kind": "request", "id": "r2", "retry_of": "r1", "ts": 132000},
        ])
        data = summary.build_summary(self.dir)
        self.assertEqual((data["cost"]["requests"], data["cost"]["priced_responses"],
                          data["cost"]["retries"], data["tools"]["results"]), (2, 4, 1, 3))
        self.assertEqual(data["ideas_without_attempts"], ["unused"])
        self.assertEqual(data["cost"]["requests_after_best"], 2)
        self.assertAlmostEqual(data["cost"]["spent_after_best_usd"], 0.005)

    def test_edits_split_into_local_and_structural(self):
        edits = summary.build_summary(self.dir)["edits"]
        self.assertEqual((edits["local"], edits["structural"]), (1, 1))

    def test_ideas_attempts_are_counted(self):
        self.assertEqual(summary.build_summary(self.dir)["ideas"],
                         [{"id": "i1", "title": "Idea", "status": "active", "attempts": 2, "probes": 0}])

    def test_cost_report_is_rebuilt_when_pi_never_wrote_one(self):
        report = summary.cost_report_from_ledger(self.dir)
        self.assertAlmostEqual(report["spent_usd"], 0.10)
        self.assertEqual(report["unresolved_usd"], 0)
        self.assertEqual(report["written_by"], "runner_ledger_reconstruction")

    def test_overshoot_is_reported(self):
        write(self.dir / "cost-ledger.jsonl", [
            {"kind": "reserve", "id": "1", "usd": 1}, {"kind": "settle", "id": "1", "usd": 0.108, "usage_known": True}])
        data = summary.write_summary(self.dir)
        self.assertAlmostEqual(data["cost"]["overshoot_usd"], 0.008)
        self.assertIn("overshoot $0.0080", (self.dir / "summary.txt").read_text())

    def test_unsettled_transport_attempt_is_reported_but_not_charged_to_the_soft_cap(self):
        (self.dir / "run-config.json").write_text(json.dumps({"hard_cap_usd": 0.1}))
        write(self.dir / "cost-ledger.jsonl", [
            {"kind": "reserve", "id": "uncertain", "usd": 0.03},
            {"kind": "unknown", "id": "uncertain", "usage_known": False},
        ])
        cost = summary.build_summary(self.dir)["cost"]
        self.assertEqual(cost["unresolved_usd"], 0.03)
        self.assertEqual(cost["remaining_usd"], 0.1)  # soft cap: actual spend only


    LENGTH_STOP_LEDGER = [
        {"kind": "reserve", "id": "a", "usd": 0.045}, {"kind": "settle", "id": "a", "usd": 0.0100, "usage_known": True},
        # Pi compacted after the length stop: a paid summary request that no message_end ever settled.
        {"kind": "reserve", "id": "summary", "usd": 0.0157},
        {"kind": "reserve", "id": "b", "usd": 0.04}, {"kind": "settle", "id": "b", "usd": 0.0090, "usage_known": True},
        {"kind": "reserve", "id": "slow", "usd": 0.04}, {"kind": "unknown", "id": "slow", "usage_known": False},
    ]

    def session_with_compaction(self, usd: float) -> None:
        (self.dir / "session").mkdir()
        write(self.dir / "session" / "s.jsonl", [
            {"type": "message", "message": {"role": "assistant", "usage": {"cost": {"total": 0.0100}}}},
            {"type": "compaction", "usage": {"cost": {"total": usd}}},
            {"type": "message", "message": {"role": "assistant", "usage": {"cost": {"total": 0.0090}}}},
        ])

    def test_a_reserve_left_open_after_a_length_stop_is_reconciled_against_the_session(self):
        recon = summary.reconcile_spend(self.LENGTH_STOP_LEDGER, 0.0258)
        self.assertEqual(recon["ledger_settled_usd"], 0.019)
        self.assertAlmostEqual(recon["gap_usd"], 0.0068)
        self.assertAlmostEqual(recon["spent_usd"], 0.0258)
        self.assertEqual([r["id"] for r in recon["open_reserves"]], ["summary"])
        self.assertEqual([r["id"] for r in recon["unknown_requests"]], ["slow"])
        # The open reserve is covered by the gap; only the timed-out request stays unresolved.
        self.assertAlmostEqual(recon["unresolved_usd"], 0.04)
        self.assertFalse(recon["balanced"])

    def test_without_a_session_total_an_open_reserve_stays_unresolved(self):
        recon = summary.reconcile_spend(self.LENGTH_STOP_LEDGER[:3])
        self.assertAlmostEqual(recon["unresolved_usd"], 0.0157)
        self.assertEqual(recon["spent_usd"], 0.01)

    def test_an_orphan_settle_closes_the_request_and_balances(self):
        ledger = [e for e in self.LENGTH_STOP_LEDGER if e["id"] != "summary"] + [
            {"kind": "reserve", "id": "summary", "usd": 0.0157},
            {"kind": "settle", "id": "summary", "usd": 0.0068, "usage_known": True, "source": "orphan_stream"}]
        recon = summary.reconcile_spend(ledger, 0.0258)
        self.assertEqual(recon["gap_usd"], 0)
        self.assertEqual(recon["open_reserves"], [])
        self.assertEqual((recon["orphan_settles"], recon["orphan_settled_usd"]), (1, 0.0068))

    def test_summary_spend_and_turns_include_compaction_that_the_ledger_never_settled(self):
        write(self.dir / "cost-ledger.jsonl", self.LENGTH_STOP_LEDGER)
        (self.dir / "cost.json").unlink(missing_ok=True)
        self.session_with_compaction(0.0068)
        cost = summary.build_summary(self.dir)["cost"]
        self.assertAlmostEqual(cost["spent_usd"], 0.0258)
        self.assertEqual(cost["by_turn_type"]["compaction"], {"requests": 1, "usd": 0.0068})
        self.assertEqual(cost["reconciliation"]["gap_usd"], 0.0068)
        self.assertEqual(cost["reconciliation"]["open_reserves"], [{"id": "summary", "usd": 0.0157}])
        self.assertAlmostEqual(cost["unresolved_usd"], 0.04)
        summary.write_summary(self.dir)
        self.assertIn("SPEND RECONCILIATION", (self.dir / "summary.txt").read_text())

    def test_orphan_settles_do_not_shift_the_per_turn_pairing(self):
        settles = [{"kind": "settle", "id": "s", "usd": 0.5, "usage_known": True, "source": "orphan_stream"},
                   {"kind": "settle", "id": "a", "usd": 0.01, "usage_known": True}]
        turns = summary._turns([assistant([("c1", "arena_state")], 0, 0)], settles)
        self.assertEqual([t["usd"] for t in turns], [0.01])


if __name__ == "__main__":
    unittest.main()
