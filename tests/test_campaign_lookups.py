import unittest
from unittest.mock import patch

from arena import campaign


class SourceHandleTests(unittest.TestCase):
    def setUp(self):
        self.row = {"name": "Target", "source": "strata", "file_path": "Strata/Target.lean",
                    "version_info": [{"4.29.1": "abc123"}]}
        self.problem = patch("arena.campaign.problem", return_value=self.row)
        self.versions = patch("arena.campaign.versions", return_value=[("4.29.1", "abc123")])
        self.workspace = patch("arena.campaign.workspace", return_value=object())
        self.contents = patch("arena.campaign._git_source", return_value="line one\nline two\n")
        for mock in (self.problem, self.versions, self.workspace, self.contents):
            mock.start()
            self.addCleanup(mock.stop)

    def test_source_accepts_decl_handle_and_reports_canonical_file_metadata(self):
        with patch("arena.campaign._resolve_declaration_source", return_value=("Strata/Target.lean", 2)):
            result = campaign.source_range("Target", "decl:Target.helper", 1, 2)
        self.assertEqual(result["path"], "Strata/Target.lean")
        self.assertEqual(result["pin"], "abc123")
        self.assertEqual(result["file_lines"], 2)
        self.assertEqual(result["text"], "1: line one\n2: line two")

    def test_bad_source_range_reports_bounds(self):
        with self.assertRaisesRegex(ValueError, "2 lines; first=3 is out of range"):
            campaign.source_range("Target", "Strata/Target.lean", 3)


if __name__ == "__main__":
    unittest.main()
