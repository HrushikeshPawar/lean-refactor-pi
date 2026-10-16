import importlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from arena.cli.provision import ProvisionOptions
from arena.engine import ROOT

provision_module = importlib.import_module("arena.cli.provision")


class IndexProvisionTests(unittest.TestCase):
    def test_index_failure_sets_nonzero_after_provision_and_keeps_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            worktree = Path(temporary) / "provisioned"
            step = {
                "version": "v4.29.1",
                "commit": "fixture-commit",
                "worktree": ROOT / "workspaces" / "fixture-v4.29.1",
                "repo": ROOT / "workspaces" / "fixture-repo",
                "module": "Fixture.Target",
                "url": "fixture",
            }
            output = io.StringIO()

            def provision(_step, _log, _timeout, _minimal, _fallback):
                worktree.mkdir()

            with (
                patch(
                    "arena.cli.provision.row_for",
                    return_value={
                        "name": "Fixture.Target",
                        "source": "fixture",
                        "version_info": [{"v4.29.1": "fixture-commit"}],
                    },
                ),
                patch("arena.cli.provision.plan", return_value=[step]),
                patch("arena.cli.provision.provision", side_effect=provision),
                patch("arena.cli.provision.LOGS", Path(temporary) / "logs"),
                patch("arena.index.build_index", side_effect=RuntimeError("fixture index failure")),
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                result = provision_module._execute(ProvisionOptions(row="Fixture.Target"))

            self.assertEqual(result, 1)
            self.assertTrue(worktree.is_dir())
            self.assertIn("index FAILED: fixture index failure", output.getvalue())
