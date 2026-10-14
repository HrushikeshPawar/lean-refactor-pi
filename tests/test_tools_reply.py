import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, reply


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

    def test_compaction_reset_needs_no_request_file(self):
        from types import SimpleNamespace

        from arena.cli.protocol import run as protocol_run

        reply.deduplicate_diagnostics(self.run_id, "n1", [{"id": "n1.e1", "goal": "⊢ True", "message": "m"}])
        result = protocol_run(SimpleNamespace(action="reset_delivered", run_id=self.run_id, request_file=None))
        self.assertTrue(result["ok"])
        shown = reply.deduplicate_diagnostics(self.run_id, "n2", [{"id": "n2.e1", "goal": "⊢ True", "message": "m"}])
        self.assertEqual(shown[0]["goal"], "⊢ True")

    def test_map_lines_show_node_ids_reference_and_route_legend_but_never_none(self):
        lines = reply._map_lines(
            {
                "best": {"node": "n2", "score": 33.31, "tokens": 407, "heartbeats": 1384},
                "reference": {"node": "n1", "tokens": 407, "heartbeats": 1383},
                "archive": [{"letter": "B", "node": "n9", "status": "sketch", "score": None, "visits": 1}],
                "recent": [
                    {"node": "n4", "edge": "edited_from", "from": ["n2"], "status": "broken", "score": None},
                    {"node": "n5", "edge": "root", "from": [], "status": "broken", "score": None},
                ],
                "effort": [{"step": "s1", "at_stake": 0.49, "variants": 1, "best_dtok": None, "last_gain": None}],
                "open": [],
            }
        )
        self.assertEqual(
            lines,
            [
                "best n2 score 33.31 tokens 407 heartbeats 1384",
                "n1 original proof tokens 407 heartbeats 1383",
                "Letters: each marks the best node of one proof shape, depth band and status; visits counts the nodes "
                "sharing them.",
                "B n9 sketch score - visits 1",
                "n4 edited from n2 broken score -",
                "n5 new root broken score -",
                "s1 at stake 0.49 variants 1 best delta - last gain -",
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
        self.assertEqual(first["facts"], ["update"])
        self.assertEqual(second["facts"], [])
        self.assertEqual(first["map"], [])
        self.assertIsNone(second["map"])

    def test_an_update_names_its_source_node_only_once_the_model_has_seen_it(self):
        update = {"seq": 1, "text": "n11 salvaged from n7: 1 hole at line 3.", "source": "n7"}
        update["unseen_text"] = "n11 salvaged from an earlier broken node: 1 hole at line 3."
        with patch.object(campaign, "state", return_value={"updates": [update]}):
            unseen = reply.attach_context(self.run_id, reply.reply())
        self.assertEqual(unseen["facts"], [update["unseen_text"]])
        (campaign.run_dir(self.run_id) / reply.DELIVERY_FILE).write_text('{"delivered_seq": -1}\n')
        shown = reply.reply(items=[{"ref": "d1", "ok": True, "lines": ["n7 <- n2 draft status broken."]}])
        with patch.object(campaign, "state", return_value={"updates": [update]}):
            seen = reply.attach_context(self.run_id, shown)
        self.assertEqual(seen["facts"], [update["text"]])
