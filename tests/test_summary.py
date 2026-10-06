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

    def test_edits_split_into_local_and_structural(self):
        edits = summary.build_summary(self.dir)["edits"]
        self.assertEqual((edits["local"], edits["structural"]), (1, 1))

    def test_ideas_attempts_are_counted(self):
        self.assertEqual(summary.build_summary(self.dir)["ideas"],
                         [{"id": "i1", "title": "Idea", "status": "active", "attempts": 2}])

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


if __name__ == "__main__":
    unittest.main()
