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
