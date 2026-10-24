"""The idea log: capture, rows and status, push with cursor and cap, the ideas tool, the orchestrator digest."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import campaign, ideas, team_reply, text, tool_schema, tools
from arena.run_control import committed_operation_ids
from tests.test_tools_compile import CascadeCase


def row(n: int, **fields) -> dict:
    """An idea row as `build_rows` writes it: a closed token win by job1 on its own step hash."""
    base = {
        "id": f"i{n}", "ts": float(n), "actor": "a1", "job": "job1", "role": "tokens", "node": f"n{n}", "parent": "n1",
        "steps": ["s1"], "pstep": "s1", "change": {"old": "simp", "new": "simp only"}, "removed": ["simp"],
        "added": ["simp only"], "anchors": [f"h{n}"], "sig": f"h{n}|simp|simp only", "d_tokens": -6, "d_hb": -200,
        "step_hb": -150, "tokens": 100, "hb": 1000, "score": 70.0, "verified": True, "outcome": "closed",
        "closed": True, "move": f"use simp only {n}", "when": "the goal is a sum", "harness": False, "sources": [],
        "kind": "edited_from", "from": [], "new_best": False, "best_ts": None, "settled": True, "win": True,
        "kept": False, "dead_trigger": False, "status": "win",
    }
    return {**base, **fields}


class CaptureTests(CascadeCase):
    def test_move_and_when_reach_the_ledger_and_a_legacy_note_is_the_move(self):
        tools.compile_tool("T", "logic", {"drafts": ["by\n  simp\n  ring"], "move": "m" * 200, "when": "w1"})
        tools.compile_tool("T", "logic", {"drafts": ["by\n  simp\n  bad"], "note": "old note", "when": "w2"})
        events = campaign.events(self.directory)
        candidate = next(e for e in events if e.get("kind") == "candidate" and e.get("when") == "w1")
        probe = next(e for e in events if e.get("kind") == "probe" and e.get("when") == "w2")
        self.assertEqual(candidate["hypothesis"], "m" * text.numbers()["idea_field_chars"])
        self.assertEqual(probe["note"], "old note")

    def test_compile_schema_offers_move_and_when_instead_of_note(self):
        properties = tool_schema.catalog()["tools"]["compile"]["properties"]
        self.assertIn("move", properties)
        self.assertIn("when", properties)
        self.assertNotIn("note", properties)
        described = text.render("tools/compile.params.move") + text.render("tools/compile.params.when")
        self.assertEqual(described.count("cannot see your proof"), 2)


class RowTests(CascadeCase):
    def test_rows_carry_the_change_its_effect_outcome_and_notes(self):
        tools.compile_tool("T", "logic", {"drafts": ["by\n  simp\n  ring\n  exact foo"], "move": "base"})
        tools.compile_tool("T", "logic", {"drafts": ["by\n  simp only\n  ring\n  exact foo"], "move": "use simp only",
                                          "when": "a sum goal", "from": "n2"})
        tools.compile_tool("T", "logic", {"drafts": ["by\n  simp\n  bad\n  exact foo"], "move": "break ring", "from": "n2"})
        rows, _ = ideas.snapshot(campaign.events(self.directory), campaign._proof_reader(self.directory),
                                 committed_operation_ids(self.directory))
        first, second = rows
        self.assertEqual((first["id"], first["parent"], first["steps"], first["change"]),
                         ("i1", "n2", ["s1"], {"old": "simp", "new": "simp only"}))
        self.assertEqual((first["move"], first["when"], first["d_tokens"], first["outcome"]),
                         ("use simp only", "a sum goal", 5, "closed"))
        self.assertEqual(first["removed"] + first["added"], ["simp", "simp only"])
        self.assertEqual((second["outcome"], second["closed"], second["status"], second["d_tokens"]),
                         ("fixture error", False, "failed", None))

    def test_status_is_kept_win_failed_or_dead_and_a_dead_change_needs_failures_with_no_win(self):
        rows = [row(n, sig="same", win=False, status="", closed=False, outcome="unsolved goals", d_tokens=None,
                    d_hb=None, step_hb=None) for n in range(1, 4)]
        nodes = {f"p{n}": SimpleNamespace(id=f"n{n}", proof_id=f"p{n}", verified=False, score=None) for n in range(1, 4)}
        ideas._statuses(rows, nodes, {})
        self.assertEqual([r["status"] for r in rows], ["dead"] * 3)
        self.assertEqual([r["dead_trigger"] for r in rows], [False, False, True])
        rows[1]["win"] = True
        ideas._statuses(rows, nodes, {})
        self.assertEqual([r["status"] for r in rows], ["failed", "win", "failed"])
        winner = SimpleNamespace(id="n3", proof_id="p3", verified=True, score=80.0)
        ideas._statuses(rows, {"p3": winner, "p1": nodes["p1"]}, {"p3": ["p1"]})
        self.assertEqual([r["status"] for r in rows], ["kept", "win", "kept"])

    def test_harness_rows_get_a_harness_written_move(self):
        self.assertIn("i12 + i15", text.render("replies/ideas.harness_assembly", sources="i12 + i15"))
        self.assertIn("i7", text.render("replies/ideas.harness_salvage", source="i7"))


class PushTests(unittest.TestCase):
    def test_a_row_reaches_an_island_once_and_at_most_three_lines_come_per_turn(self):
        rows = [row(n, job="job2", role="family") for n in range(1, 6)]
        state: dict = {}
        first = ideas.push(rows, "tokens", "job1", state)
        self.assertEqual(len(first), text.numbers()["idea_push_lines"])
        self.assertTrue(first[-1].startswith("+3 more"))
        self.assertEqual(ideas.push(rows, "tokens", "job1", state), [])
        later = ideas.push([*rows, row(6, job="job2", role="family")], "tokens", "job1", state)
        self.assertEqual(len(later), 1)
        self.assertIn("use simp only 6", later[0])

    def test_technique_lines_have_no_node_ids_skip_own_rows_and_dedupe_by_signature(self):
        rows = [row(1, job="job2", move="apply on n31 and n7", sig="x"), row(2, job="job3", sig="x"),
                row(3, job="job1", sig="own"), row(4, job="job2", d_tokens=-1, step_hb=-5, sig="small"),
                row(5, job="job2", move="", change=None, sig="empty")]
        lines = ideas.push(rows, "tokens", "job1", {})
        self.assertEqual(len(lines), 1)
        self.assertNotRegex(lines[0], r"\bn\d+\b")
        self.assertIn("applies when the goal is a sum", lines[0])
        self.assertIn("-6 tok, -150 HB", lines[0])

    def test_trim_hears_only_the_newest_new_best_and_a_new_actor_is_not_told_the_old_ones(self):
        rows = [row(1, new_best=True, best_ts=10.0), row(2, new_best=True, best_ts=20.0, job="job2")]
        state: dict = {"cursor": 0, "since": 5.0}
        lines = ideas.push(rows, "trim", "job4", state)
        self.assertEqual(len(lines), 1)
        self.assertIn("New best n2", lines[0])
        self.assertEqual(state["last"]["superseded"], ["b:1"])
        self.assertEqual(ideas.push(rows, "trim", "job4", state), [])
        self.assertEqual(ideas.push(rows, "merge", "job5", {}), [])  # first sight: its packet names the best

    def test_dead_ends_reach_everyone_once_even_the_actor_that_failed(self):
        failed = [row(n, sig="dead", win=False, closed=False, status="dead", outcome="unsolved goals", job="job1",
                      dead_trigger=n == 3) for n in range(1, 4)]
        for role in ("trim", "tokens", "proof"):
            state: dict = {}
            lines = ideas.push(failed, role, "job1", state)
            self.assertEqual(len(lines), 1)
            self.assertIn("failed 3 times", lines[0])
            self.assertIn("first error: unsolved goals", lines[0])
            self.assertEqual(ideas.push(failed, role, "job1", state), [])

    def test_a_closed_row_waits_for_its_full_check_before_the_cursor_passes_it(self):
        pending = row(1, job="job2", settled=False, status="pending", win=False)
        state: dict = {}
        self.assertEqual(ideas.push([pending], "tokens", "job1", state), [])
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(len(ideas.push([{**pending, "settled": True, "win": True, "status": "win"}], "tokens", "job1", state)), 1)


class ToolTests(unittest.TestCase):
    def test_query_groups_one_step_by_change_with_counts_status_and_ids(self):
        rows = [row(1, anchors=["hx"], sig="a"), row(2, anchors=["hx"], sig="a", win=False, status="failed", d_tokens=None,
                                                    step_hb=None, d_hb=None),
                row(3, anchors=["hx"], sig="b", win=False, status="dead"), row(4, anchors=["hy"], sig="c")]
        lines = ideas.query(rows, "hx", None)
        self.assertEqual(len(lines), 2)
        self.assertIn("tried 2 times - won", lines[0])
        self.assertIn("i1 i2", lines[0])
        self.assertIn("dead end", lines[1])
        self.assertEqual(len(ideas.query(rows, None, "SIMP ONLY")), 3)
        self.assertEqual(ideas.query(rows, None, "omega"), [])

    def test_the_tool_needs_a_step_or_a_tactic_and_is_bounded(self):
        self.assertFalse(ideas.ideas_tool("logic", {})["ok"])
        self.assertFalse(ideas.ideas_tool("logic", {"node": "n1"})["ok"])
        many = [row(n, anchors=["hx"], sig=f"s{n}") for n in range(1, 20)]
        lines = ideas.query(many, "hx", None)
        self.assertEqual(len(lines), text.numbers()["idea_query_rows"] + 1)
        self.assertTrue(lines[-1].startswith("+"))

    def test_the_tool_is_registered_for_every_actor_and_the_plan_tool_is_not(self):
        catalog = tool_schema.catalog()
        for role in ("worker", "sol"):
            self.assertIn("ideas", catalog["roles"][role])
            self.assertNotIn("plan", catalog["roles"][role])
        self.assertNotIn("plan", catalog["tools"])
        with patch.object(ideas, "sync", return_value=[row(1, anchors=["hx"])]), \
                patch.object(tools, "_node", return_value=type("N", (), {"id": "n9", "steps": [
                    type("S", (), {"id": "s1", "hash": "hx"})()]})()):
            reply = ideas.ideas_tool("logic", {"node": "n9", "step": "s1"})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["text"].startswith("Tried on n9 s1:"))


class DigestTests(unittest.TestCase):
    def test_sol_reads_only_what_is_new_grouped_as_kept_dead_and_one_line_per_active_job(self):
        jobs = {"j1": {"label": "job1", "role": "tokens", "actor": "a1", "scope": "island", "objective": "tokens"}}
        kept = row(1, status="kept", kept=True)
        dead = row(2, sig="d", win=False, closed=False, status="dead", outcome="unsolved goals", dead_trigger=True)
        state: dict = {}
        lines = ideas.digest([kept, dead], jobs, state)
        self.assertTrue(lines[0].startswith("Kept i1 (n1)"))
        self.assertTrue(lines[1].startswith("Dead end at step s1 of n1"))
        self.assertTrue(lines[2].startswith("job1 (token island): best n1 100 tok"))
        self.assertEqual(ideas.digest([kept, dead], jobs, state), [])
        fresh = row(3, status="kept", kept=True, tokens=90)
        again = ideas.digest([kept, dead, fresh], jobs, state)
        self.assertEqual([line.split(" ")[0] for line in again], ["Kept", "job1"])
        self.assertIn("best n3 90 tok", again[1])

    def test_the_digest_is_bounded_and_the_notices_carry_it_first(self):
        rows = [row(n, status="kept", kept=True) for n in range(1, 9)]
        lines = ideas.digest(rows, {}, {})
        self.assertEqual(len(lines), text.numbers()["idea_digest_lines"] + 1)
        self.assertTrue(lines[-1].startswith("+4 more"))
        with patch.object(ideas, "lines_for", return_value=("sol", ["Kept i1 (n1)"])), \
                patch.object(team_reply.orchestration, "merge_ready", return_value=[]), \
                patch.object(team_reply.orchestration, "token_short", return_value=[]):
            self.assertEqual(team_reply.notices(Path("run"), {}, None), (["ideas"], ["Kept i1 (n1)"]))


class PlanRemovalTests(unittest.TestCase):
    def test_no_plan_tool_action_or_paragraph_remains_and_old_plan_rows_stay_readable(self):
        from importlib import import_module

        from arena import plans

        protocol = import_module("arena.cli.protocol")

        self.assertNotIn("plan", protocol.ACTIONS)
        self.assertNotIn("plan", protocol.NOTICE_ACTIONS)
        self.assertFalse((Path(__file__).parents[1] / "agent-text/tools/plan.yaml").exists())
        self.assertNotIn("save a plan", text.template("packet/team"))
        self.assertIn("idea log", text.template("packet/team"))
        self.assertIn("n164-600-tok-12917-HB", text.template("packet/team"))
        self.assertIn("n160-352-tok-369-HB", text.template("tools/delegate.params.task"))
        with patch.object(plans.orchestration, "_history", return_value=[{"type": "plan", "version": 1}, {"type": "card"}]):
            self.assertEqual(plans.plan_rows(Path("run")), [{"type": "plan", "version": 1}])
        json.dumps(plans.STATUSES)


if __name__ == "__main__":
    unittest.main()
