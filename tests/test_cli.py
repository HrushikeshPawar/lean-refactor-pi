import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
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


class CommandTreeTests(unittest.TestCase):
    def test_required_eval_arguments_are_enforced(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit) as result:
            app(["eval"])
        self.assertNotEqual(result.exception.code, 0)

    def test_every_public_command_has_help(self):
        commands = [
            [name, "--help"]
            for name in (
                "run",
                "campaign",
                "certify",
                "check",
                "eval",
                "merge",
                "package",
                "preflight",
                "serve",
                "provision",
                "experiment",
                "doctor",
                "smoke",
            )
        ] + [["graph", "export", "--help"]]
        commands.extend([["lean", name, "--help"] for name in ("serve", "health", "load-test")])
        commands.extend([["index", name, "--help"] for name in ("build", "status")])
        commands.append(["protocol", "--help"])
        for command in commands:
            with self.subTest(command=command), patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
                self.assertIn(app(command), (0, None))

    def test_campaign_dry_run_uses_module_command_without_creating_runs(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = app(
                [
                    "campaign",
                    "--prefix",
                    "t",
                    "--rows",
                    "Core.InitsUpdatesComm",
                    "--models",
                    "deepseek-v4.1-flash",
                    "--dry-run",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("arena run --model", output.getvalue())
        self.assertFalse(any(Path("runs/pi-budget").glob("t-Core.InitsUpdatesComm-*")))

    def test_campaign_dynamic_model_error_names_the_model(self):
        output = io.StringIO()
        with redirect_stdout(output), patch("sys.stderr", output):
            status = app(
                [
                    "campaign",
                    "--prefix",
                    "t",
                    "--rows",
                    "Core.InitsUpdatesComm",
                    "--models",
                    "no-such-model",
                    "--dry-run",
                ]
            )
        self.assertEqual(status, 2)
        self.assertIn("no-such-model", output.getvalue())

    def test_provision_progress_json_reports_each_environment(self):
        from unittest.mock import patch

        output = io.StringIO()
        with redirect_stdout(output), patch("arena.cli.provision.status", return_value=(0.5, "building", False, False)):
            status = app(["provision", "--progress", "--json", "--only", "cslib-v4.32.0"])
        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "items": [
                    {
                        "name": "cslib-v4.32.0",
                        "fraction": 0.5,
                        "detail": "building",
                        "finished": False,
                        "failed": False,
                    }
                ],
                "finished": False,
            },
        )

    def test_provision_watch_refreshes_until_every_environment_finishes(self):
        from unittest.mock import patch

        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch(
                "arena.cli.provision.status",
                side_effect=[(0.5, "building", False, False), (1.0, "done", True, False)],
            ),
            patch("arena.cli.provision.time.sleep"),
        ):
            status = app(["provision", "--progress", "--watch", "--only", "cslib-v4.32.0"])
        self.assertEqual(status, 0)
        self.assertGreaterEqual(output.getvalue().count("Workspace provisioning"), 2)
