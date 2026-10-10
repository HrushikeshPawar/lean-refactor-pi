import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.cli import app, load_env


class LoadEnvTests(unittest.TestCase):
    def test_exports_new_keys_and_never_overrides_the_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("# comment\n\nARENA_T_NEW='quoted value'\nexport ARENA_T_SET=from-file\nnot a line\n")
            with patch.dict(os.environ, {"ARENA_T_SET": "from-shell"}):
                exported = load_env(path)
                self.assertEqual(exported, ["ARENA_T_NEW"])
                self.assertEqual(os.environ["ARENA_T_NEW"], "quoted value")
                self.assertEqual(os.environ["ARENA_T_SET"], "from-shell")

    def test_a_missing_file_exports_nothing(self):
        self.assertEqual(load_env(Path("/nonexistent/.env")), [])


class PassThroughTests(unittest.TestCase):
    def test_tool_usage_errors_become_a_nonzero_exit_code(self):
        with patch("sys.stderr"):
            self.assertNotEqual(app(["eval"]), 0)  # arena_eval requires a name and a proof file

    def test_tool_help_exits_zero(self):
        with patch("sys.stdout"):
            self.assertEqual(app(["eval", "--help"]), 0)
