import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, reply, text


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run_id = "reply-test"
        self.patch_root = patch.object(campaign, "ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        campaign.run_dir(self.run_id).mkdir(parents=True)

    def test_reply_shape_and_empty_arguments_name_the_valid_keys(self):
        result = reply.error_reply("empty_arguments", "{}", ["drafts", "check"], ["drafts[1..N]"])
        self.assertEqual(
            result,
            {
                "ok": False,
                "error": {
                    "code": "empty_arguments",
                    "input": "{}",
                    "valid": ["drafts", "check"],
                    "forms": ["drafts[1..N]"],
                },
                "facts": [],
                "items": [],
                "handles": [],
                "map": None,
                "stop": False,
            },
        )

    def test_repeated_goal_is_deduplicated_until_reset(self):
        first = {"id": "n1.e1", "goal": "x : Nat\n⊢ x = x", "message": "short"}
        second = {"id": "n2.e1", "goal": "x : Nat   ⊢ x = x", "message": "short"}
        reply.deduplicate_diagnostics(self.run_id, "n1", [first])
        repeated = reply.deduplicate_diagnostics(self.run_id, "n2", [second])[0]
        self.assertEqual(repeated["goal"], "same goal as n1.e1")
        self.assertTrue((campaign.run_dir(self.run_id) / "diagnostics" / "n2.jsonl").is_file())
        reply.reset_delivered(self.run_id)
        shown_again = reply.deduplicate_diagnostics(self.run_id, "n3", [{**second, "id": "n3.e1"}])[0]
        self.assertEqual(shown_again["goal"], second["goal"])

    def test_a_node_returned_twice_shows_its_full_error_both_times(self):
        message = "Application type mismatch: " + "the argument has the wrong type. " * 5
        error = {"id": "n66.e1", "goal": "x : Nat\n⊢ x = x", "message": message}
        first = reply.deduplicate_diagnostics(self.run_id, "n66", [dict(error)])[0]
        again = reply.deduplicate_diagnostics(self.run_id, "n66", [dict(error)])[0]
        for shown_error in (first, again):
            self.assertEqual(shown_error["goal"], error["goal"])
            self.assertEqual(shown_error["message"], message)
            self.assertNotIn("same as", str(shown_error))

    def test_two_different_nodes_with_the_same_error_still_deduplicate(self):
        message = "Application type mismatch: " + "the argument has the wrong type. " * 5
        reply.deduplicate_diagnostics(self.run_id, "n66", [{"id": "n66.e1", "goal": "⊢ True", "message": message}])
        other = reply.deduplicate_diagnostics(
            self.run_id, "n67", [{"id": "n67.e1", "goal": "⊢ True", "message": message}]
        )[0]
        self.assertEqual(other["goal"], "same goal as n66.e1")
        self.assertEqual(other["message"], f"{message} same as n66.e1")

    def test_compaction_reset_needs_no_request_file(self):
        from types import SimpleNamespace

        from arena.cli.protocol import run as protocol_run

        reply.deduplicate_diagnostics(self.run_id, "n1", [{"id": "n1.e1", "goal": "⊢ True", "message": "m"}])
        result = protocol_run(SimpleNamespace(action="reset_delivered", run_id=self.run_id, request_file=None))
        self.assertTrue(result["ok"])
        shown = reply.deduplicate_diagnostics(self.run_id, "n2", [{"id": "n2.e1", "goal": "⊢ True", "message": "m"}])
        self.assertEqual(shown[0]["goal"], "⊢ True")

    def test_map_lines_label_every_section_and_rank_steps_but_never_show_none(self):
        lines = reply._map_lines(
            {
                "best": {"node": "n2", "score": 33.31, "tokens": 407, "heartbeats": 1384},
                "reference": {"node": "n1", "tokens": 407, "heartbeats": 1383},
                "archive": [{"letter": "B", "node": "n9", "status": "sketch", "score": None, "visits": 1}],
                "recent": [
                    {"node": "n4", "edge": "edited_from", "from": ["n2"], "status": "broken", "score": None},
                    {"node": "n5", "edge": "root", "from": [], "status": "broken", "score": None},
                ],
                "effort": [
                    {"step": "s1", "at_stake": 0.49, "variants": 1, "best_dtok": None, "last_gain": None},
                    {
                        "step": "s2",
                        "at_stake": 2.5,
                        "tokens": 30,
                        "heartbeats": 90,
                        "variants": 4,
                        "best_dtok": 3,
                        "last_gain": 2,
                    },
                ],
                "open": [{"hole": "n9.h1", "line": 4, "goal": "case inl\nh : P\n⊢ Q"}],
            }
        )
        self.assertEqual(
            lines,
            [
                text.render("replies/tools.map_best_head"),
                "best n2 score 33.31 tokens 407 heartbeats 1384",
                "n1 original proof tokens 407 heartbeats 1383",
                text.render("replies/tools.map_shapes"),
                "| n9 | compiles with open holes | - | - | - | 1 |",
                text.render("replies/tools.map_recent_head"),
                "| n4 | made from n2 | does not compile | - | - | - |",
                "| n5 | new root | does not compile | - | - | - |",
                text.render("replies/tools.map_steps_head", node="n2"),
                text.render("replies/tools.map_steps_legend"),
                text.render("replies/tools.map_steps_cols"),
                # Ranked by points at stake, not by step order.
                "| s2 | 30 | 90 | 2.5 | 4 | +3 | 2 |",
                # Step heartbeats not yet profiled are pending, not missing.
                "| s1 | - | pending | 0.49 | 1 | - | - |",
                text.render("replies/tools.map_holes_head"),
                # The hole shows its case tag and target line, not the hypothesis context.
                "- n9.h1 line 4: case inl ⊢ Q",
            ],
        )
        self.assertNotIn("None", "\n".join(lines))

    def test_pending_update_and_changed_map_are_delivered_once(self):
        with (
            patch.object(campaign, "state", return_value={"updates": [{"seq": 4, "text": "update"}]}),
            patch.object(
                campaign, "map_view", return_value={"best": None, "archive": [], "recent": [], "effort": [], "open": []}
            ),
        ):
            first = reply.attach_context(self.run_id, reply.reply(), include_map=True)
            second = reply.attach_context(self.run_id, reply.reply(), include_map=True)
        self.assertEqual(first["facts"], ["## Updates", "update"])
        self.assertEqual(second["facts"], [])
        self.assertEqual(first["map"], [])
        self.assertIsNone(second["map"])

    def test_an_update_names_its_source_node_only_once_the_model_has_seen_it(self):
        update = {"seq": 1, "text": "n11: sketch from n7; line 3 is a hole to fill.", "source": ["n7"]}
        update["unseen_text"] = "n11: sketch from earlier broken nodes; line 3 is a hole to fill."
        with patch.object(campaign, "state", return_value={"updates": [update]}):
            unseen = reply.attach_context(self.run_id, reply.reply())
        self.assertEqual(unseen["facts"], ["## Updates", update["unseen_text"]])
        shown = reply.reply(items=[{"ref": "d1", "ok": True, "lines": ["n7 <- n2 draft status broken."]}])
        later = {"seq": 2, "text": update["text"], "source": ["n7"], "unseen_text": update["unseen_text"]}
        with patch.object(campaign, "state", return_value={"updates": [update, later]}):
            seen = reply.attach_context(self.run_id, shown)
        self.assertEqual(seen["facts"], ["## Updates", update["text"]])


class UntriedStepTests(unittest.TestCase):
    def test_barely_tried_steps_below_the_table_are_named(self):
        from arena.reply import _untried_steps

        hidden = [
            {"step": "s10", "variants": 0, "at_stake": 1.39},
            {"step": "s5", "variants": 67, "at_stake": 0.77},
            {"step": "s12", "variants": 1, "at_stake": 0.27},
        ]
        line = _untried_steps(hidden)
        self.assertIn("s10 (0 tries, 1.39 pts)", line)
        self.assertNotIn("s5", line)
        self.assertNotIn("s12", line)
        self.assertIsNone(_untried_steps(hidden[1:]))

    def test_first_node_without_any_tries_names_nothing(self):
        rows = [{"step": f"s{i}", "variants": 0, "at_stake": 5.0 - i * 0.1, "tokens": 9} for i in range(1, 12)]
        lines = reply._effort_lines({"effort": rows, "best": {"id": "n2"}})
        self.assertFalse(any("Barely tried" in line for line in lines))


class CompactMessageTests(unittest.TestCase):
    def test_a_turnstile_only_inside_a_line_leaves_the_message_unchanged(self):
        message = "type mismatch\n  h\nhas type\n    a ⊢ b\nbut is expected to have type\n    c"
        self.assertEqual(reply.compact_message(message), message)


class MessageGoalTests(unittest.TestCase):
    def test_note_lines_before_the_goal_are_not_the_goal(self):
        from arena.tools import message_goal

        message = (
            "Case tag `app` not found.\n\nNote: There are no cases to select.\n\n"
            "der this : Typing [] t τ\n⊢ t.Value ∨ ∃ t', t ⭢βᵛ t'"
        )
        goal = message_goal(message)
        self.assertTrue(goal.startswith("der this"), goal)
        self.assertNotIn("Note:", goal)
