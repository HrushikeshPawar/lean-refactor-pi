"""state.json is published by tool calls and background checks at once; an older snapshot must never win."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign


class StateWriteTests(unittest.TestCase):
    def test_an_older_snapshot_never_replaces_a_newer_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(campaign, "run_dir", return_value=directory):
                with patch.object(campaign, "state", return_value={"seq": 10, "best": {"proxy": 90.26}}):
                    campaign.write_state("r")
                with patch.object(campaign, "state", return_value={"seq": 8, "best": {"proxy": 89.89}}):
                    campaign.write_state("r")
                self.assertEqual(json.loads((directory / "state.json").read_text())["best"]["proxy"], 90.26)
                with patch.object(campaign, "state", return_value={"seq": 12, "best": {"proxy": 90.36}}):
                    campaign.write_state("r")
                self.assertEqual(json.loads((directory / "state.json").read_text())["best"]["proxy"], 90.36)
            self.assertEqual(sorted(path.name for path in directory.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
