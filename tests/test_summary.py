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

    def test_unsettled_transport_attempt_remains_in_the_allowance(self):
        (self.dir / "run-config.json").write_text(json.dumps({"hard_cap_usd": 0.1}))
        write(self.dir / "cost-ledger.jsonl", [
            {"kind": "reserve", "id": "uncertain", "usd": 0.03},
            {"kind": "unknown", "id": "uncertain", "usage_known": False},
        ])
        cost = summary.build_summary(self.dir)["cost"]
        self.assertEqual(cost["unresolved_usd"], 0.03)
        self.assertEqual(cost["remaining_usd"], 0.07)


if __name__ == "__main__":
    unittest.main()
