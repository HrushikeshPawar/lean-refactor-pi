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


class StallTests(unittest.TestCase):
    def streak(self, count: int, first: int = 1, **fields) -> list[dict]:
        return [row(n, win=False, status="failed", d_tokens=None, step_hb=None, d_hb=None, **{"from": ["p1"], **fields})
                for n in range(first, first + count)]

    @staticmethod
    def costs(proof_id: str) -> list[dict]:
        return [{"step": "s1", "tokens": 90, "heartbeats": 900}, {"step": "s7", "tokens": 40, "heartbeats": 300},
                {"step": "s9", "tokens": 30, "heartbeats": None}, {"step": "s2", "tokens": 5, "heartbeats": 1}]

    def test_five_attempts_on_one_step_push_one_line_naming_the_next_costliest_steps_once_per_streak(self):
        limit = text.numbers()["stall_same_step"]
        state: dict = {}
        self.assertEqual(ideas.push(self.streak(limit - 1), "heartbeats", "job1", state, self.costs), [])
        rows = self.streak(limit)
        lines = ideas.push(rows, "heartbeats", "job1", state, self.costs)
        self.assertEqual(len(lines), 1)
        self.assertIn("Stalled: 5 attempts on step s1 of n1 without a gain, 0 of them dead ends", lines[0])
        self.assertIn("costliest other steps of n1 are s7 (40 tok, 300 HB), s9 (30 tok, - HB)", lines[0])
        self.assertNotIn("s2", lines[0])
        self.assertEqual(ideas.push(self.streak(limit + 1), "heartbeats", "job1", state, self.costs), [])
        won = [*self.streak(limit + 1), row(limit + 2)]  # a win ends the streak; a new one is a new line
        self.assertEqual(ideas.push(won, "heartbeats", "job1", state, self.costs), [])
        again = [*won, *self.streak(limit, first=20, pstep="s3")]
        self.assertEqual(len(ideas.push(again, "heartbeats", "job1", state, self.costs)), 1)

    def test_another_step_or_a_win_or_other_jobs_rows_do_not_count_and_the_cap_still_holds(self):
        limit = text.numbers()["stall_same_step"]
        mixed = self.streak(limit)
        mixed[2]["pstep"] = "s4"
        self.assertEqual(ideas.push(mixed, "tokens", "job1", {}, self.costs), [])
        self.assertEqual(ideas.push(self.streak(limit), "tokens", "job2", {}, self.costs), [])
        busy = [*self.streak(limit), *(row(40 + n, job="job2", new_best=True, best_ts=float(n), sig=None) for n in range(3)),
                *(row(50 + n, job="job3", sig=f"w{n}", step_hb=-300, d_hb=-300) for n in range(4))]
        lines = ideas.push(busy, "tokens", "job1", {"cursor": 0, "since": 0.0}, self.costs)
        self.assertLessEqual(len(lines), text.numbers()["idea_push_lines"])
        self.assertTrue(lines[0].startswith("Stalled"))

    def test_sol_reads_one_action_line_per_stalled_job_once(self):
        jobs = {"j1": {"label": "job1", "role": "heartbeats", "actor": "a1", "scope": "island", "objective": "heartbeats"}}
        rows = self.streak(text.numbers()["stall_same_step"])
        state: dict = {}
        lines = ideas.digest(rows, jobs, state, self.costs)
        self.assertIn("job1: 5 attempts on s1 of n1 without a gain; next costliest s7 (40 tok, 300 HB), s9 (30 tok, - HB)",
                      lines)
        self.assertNotIn("job1: 5 attempts", " ".join(ideas.digest(rows, jobs, state, self.costs)))


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
        with patch.object(ideas, "board_tool", return_value={"ok": True, "text": "board"}):
            self.assertEqual(ideas.ideas_tool("logic", {})["text"], "board")
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


HYP = {"id": "H1", "ts": 0.0, "operation_id": "op1", "task": "bilinear ext", "expect": "s1 -100 HB"}


def hyp_jobs(*hyps: dict) -> dict:
    return {"j1": {"label": "job1", "role": "tokens", "actor": "a1", "scope": "island", "objective": "tokens",
                   "hyps": list(hyps or [HYP])}}


class DigestTests(unittest.TestCase):
    def test_sol_reads_only_what_is_new_grouped_as_hypotheses_dead_and_one_line_per_active_job(self):
        jobs = hyp_jobs()
        kept = row(1, status="kept", kept=True, hyp="H1")
        dead = row(2, sig="d", win=False, closed=False, status="dead", outcome="unsolved goals", dead_trigger=True)
        state: dict = {}
        lines = ideas.digest([kept, dead], jobs, state)
        self.assertEqual(lines[0], "H1 job1 (bilinear ext, expect s1 -100 HB): 1 try, best -6 tok, -150 HB on s1, "
                                   "in best: yes - confirmed")
        self.assertTrue(lines[1].startswith("Dead end at step s1 of n1"))
        self.assertTrue(lines[2].startswith("job1 (token island): best n1 100 tok"))
        self.assertEqual(ideas.digest([kept, dead], jobs, state), [])
        fresh = row(3, status="kept", kept=True, tokens=90, hyp="H1", d_tokens=-300)
        again = ideas.digest([kept, dead, fresh], jobs, state)
        self.assertEqual([line.split(" ")[0] for line in again], ["H1", "job1"])
        self.assertIn("2 tries, best -300 tok", again[0])
        self.assertIn("best n3 90 tok", again[1])

    def test_the_digest_is_bounded_and_the_notices_carry_it_first(self):
        hyps = [{**HYP, "id": f"H{n}"} for n in range(1, 9)]
        rows = [row(n, status="kept", kept=True, hyp=f"H{n}") for n in range(1, 9)]
        lines = ideas.digest(rows, hyp_jobs(*hyps), {})
        self.assertEqual(len(lines), text.numbers()["hyp_digest_lines"] + 2)  # the "+N more" line and the job line
        self.assertTrue(lines[text.numbers()["hyp_digest_lines"]].startswith("+5 more"))
        with patch.object(ideas, "lines_for", return_value=("sol", ["H1 job1 (x)"])), \
                patch.object(team_reply.orchestration, "merge_ready", return_value=[]), \
                patch.object(team_reply.orchestration, "token_short", return_value=[]):
            self.assertEqual(team_reply.notices(Path("run"), {}, None), (["ideas"], ["H1 job1 (x)"]))


class HypothesisTests(CascadeCase):
    def test_each_delegation_and_message_is_numbered_and_the_harness_started_job_has_none(self):
        history = [
            {"type": "delegation", "job_id": "a", "scope": "proof", "task": "first", "expect": "s2 -1000 HB", "ts": 1.0,
             "operation_id": "o1"},
            {"type": "delegation", "job_id": "m", "scope": "merge", "creator": "harness", "task": "auto", "ts": 2.0},
            {"type": "job_message", "job_id": "a", "text": "again", "disposition": "sent", "ts": 3.0, "operation_id": "o2"},
            {"type": "job_message", "job_id": "a", "text": "unsent", "disposition": "queued", "ts": 4.0},
            {"type": "delegation", "job_id": "b", "scope": "island", "task": "second", "ts": 5.0, "operation_id": "o3"},
            {"type": "job_message", "job_id": "m", "text": "tell merge", "disposition": "sent", "ts": 6.0},
        ]
        jobs = ideas.job_table(history)
        self.assertEqual([(h["id"], h["task"], h["expect"]) for h in jobs["a"]["hyps"]],
                         [("H1", "first", "s2 -1000 HB"), ("H2", "again", "")])
        self.assertEqual([h["id"] for h in jobs["b"]["hyps"]], ["H3"])
        self.assertEqual([h["id"] for h in jobs["m"]["hyps"]], ["H4"])
        self.assertEqual(ideas.hypothesis_id(history, "o3"), "H3")
        self.assertIsNone(ideas.hypothesis_id(history, "nope"))

    def test_expected_gain_reads_figures_with_units_only(self):
        self.assertEqual(ideas.expected("s2 -1000 HB"), {"heartbeats": 1000})
        self.assertEqual(ideas.expected("n160-352-tok-369-HB"), {"tokens": 352, "heartbeats": 369})
        self.assertEqual(ideas.expected("s2 shorter"), {})

    def test_verdicts_are_computed_from_the_measurements(self):
        limit = text.numbers()["hyp_refuted_tries"]
        fail = {"win": False, "closed": False, "status": "failed", "d_tokens": None, "d_hb": None, "step_hb": None}
        jobs = hyp_jobs(HYP, {**HYP, "id": "H2", "expect": ""}, {**HYP, "id": "H3"}, {**HYP, "id": "H4"},
                        {**HYP, "id": "H5", "expect": "s1 -9000 HB"})
        rows = [row(1, hyp="H1"),                                     # met -100 HB
                *(row(10 + n, hyp="H2", **fail) for n in range(limit)),  # no gain, enough tries
                row(20, hyp="H3", **fail),                            # one failed try
                row(30, hyp="H5", status="kept", kept=True)]          # a gain short of -9000 HB
        verdicts = {item["id"]: item["verdict"] for item in ideas.outcomes(rows, jobs)}
        self.assertEqual(verdicts, {"H1": "confirmed", "H2": "refuted", "H3": "open", "H5": "partly"})
        self.assertNotIn("H4", verdicts)  # no attempt yet: nothing to say

    def test_rows_link_to_the_hypothesis_their_job_held_when_they_were_saved(self):
        with patch.dict("os.environ", {"ARENA_JOB_ID": "jx"}):
            tools.compile_tool("T", "logic", {"drafts": ["by\n  simp\n  ring\n  exact foo"], "move": "base"})
            tools.compile_tool("T", "logic", {"drafts": ["by\n  simp only\n  ring\n  exact foo"], "from": "n2"})
        history = campaign.events(self.directory)
        stamp = next(e["ts"] for e in history if e.get("kind") == "edge")

        def linked(*times: float) -> list:
            hyps = [{**HYP, "id": f"H{n}", "ts": ts} for n, ts in enumerate(times, 1)]
            jobs = {"jx": {"label": "job1", "role": "tokens", "objective": "tokens", "actor": "a", "hyps": hyps}}
            rows = ideas.build_rows(history, campaign._proof_reader(self.directory), committed_operation_ids(self.directory), jobs)
            return [r["hyp"] for r in rows]

        self.assertEqual(linked(stamp - 5, stamp + 5), ["H1"])  # the second was sent after the attempt
        self.assertEqual(linked(stamp - 5, stamp - 1), ["H2"])
        self.assertEqual(linked(stamp + 5), [None])

    def test_the_board_ranks_steps_by_cost_and_marks_the_untried(self):
        node = SimpleNamespace(id="n9", steps=[SimpleNamespace(id="s1", hash="hx"), SimpleNamespace(id="s2", hash="hy")])
        priced = [{"step": "s2", "tokens": 90, "heartbeats": 1466, "points": 3.0},
                  {"step": "s1", "tokens": 30, "heartbeats": None, "points": 1.0}]
        fail = {"win": False, "closed": False, "status": "failed", "d_tokens": None, "d_hb": None, "step_hb": None}
        rows = [row(1, anchors=["hx"], hyp="H1", sig="a"), row(2, anchors=["hx"], hyp="H1", sig="b", **fail)]
        entries = ideas.board(rows, hyp_jobs(), node, priced)
        self.assertEqual([(e["step"], e["tries"], e["open"]) for e in entries], [("s2", 0, []), ("s1", 2, [])])
        lines = ideas.board_lines(entries, node)
        self.assertEqual(lines[1], "s2 90 tok 1466 HB - untried")
        self.assertEqual(lines[2], "s1 30 tok - HB - 2 tries, best -6 tok, -150 HB on s1")
        state: dict = {}
        self.assertEqual(ideas.untried_line(entries, node, state), ["Untried in n9: s2 1466 HB"])
        self.assertEqual(ideas.untried_line(entries, node, state), [])  # said once while the set is the same

    def test_the_digest_adds_the_untried_line_when_the_log_changed(self):
        node = SimpleNamespace(id="n9", proof_id="p9", steps=[SimpleNamespace(id="s2", hash="hy")])
        costs = lambda proof: [{"step": "s2", "tokens": 90, "heartbeats": 1466, "points": 3.0}]  # noqa: E731
        state: dict = {}
        first = ideas.digest([row(1)], {}, state, costs, lambda: node)
        self.assertEqual(first, ["Untried in n9: s2 1466 HB"])
        self.assertEqual(ideas.digest([row(1)], {}, state, costs, lambda: node), [])


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
