import copy
import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from arena import models
from arena.cli.run import pi_settings, seed_agent_dir


class PiSettingsTests(unittest.TestCase):
    def args(self):
        return Namespace(model="deepseek-v4.1-flash", compact_at_tokens=850000, compact_keep_tokens=40000)

    def test_retry_and_idle_settings_follow_models_yaml(self):
        config = copy.deepcopy(models.load())
        settings = pi_settings(self.args(), config)
        self.assertEqual(settings["httpIdleTimeoutMs"], 120000)
        self.assertEqual(
            settings["retry"],
            {
                "enabled": True,
                "maxRetries": 3,
                "baseDelayMs": 2000,
                "maxAgentDelayMs": 60000,
                "provider": {"timeoutMs": 120000, "maxRetries": 0},
            },
        )
        config["retry"]["max_retries"] = 5
        config["retry"]["base_delay_ms"] = 3500
        changed = pi_settings(self.args(), config)
        self.assertEqual((changed["retry"]["maxRetries"], changed["retry"]["baseDelayMs"]), (5, 3500))
        self.assertEqual(changed["compaction"], settings["compaction"])

    def test_retry_base_environment_override_is_for_test_runs(self):
        with patch.dict(os.environ, {"ARENA_RETRY_BASE_MS": "10"}):
            self.assertEqual(pi_settings(self.args(), models.load())["retry"]["baseDelayMs"], 10)


class AgentDirTests(unittest.TestCase):
    """The run's Pi agent directory must keep the operator's login and plugins; only models.json differs."""

    def test_run_agent_dir_keeps_auth_and_plugins_and_adds_the_max_tokens_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "agent", Path(tmp) / "run" / "pi-agent"
            (source / "npm").mkdir(parents=True)
            (source / "auth.json").write_text('{"opencode-go": {}}')
            user_models = {"providers": {"opencode-go": {"modelOverrides": {"other": {"maxTokens": 7}}}, "local": {}}}
            (source / "models.json").write_text(json.dumps(user_models))
            seed_agent_dir(target, source, "opencode-go", "deepseek-v4.1-flash", 64000)
            seed_agent_dir(target, source, "opencode-go", "deepseek-v4.1-flash", 64000)  # a resumed run
            self.assertEqual((target / "auth.json").read_text(), '{"opencode-go": {}}')
            self.assertTrue((target / "npm").is_dir())
            self.assertFalse((target / "models.json").is_symlink())
            written = json.loads((target / "models.json").read_text())
            self.assertEqual(
                written["providers"]["opencode-go"]["modelOverrides"],
                {"other": {"maxTokens": 7}, "deepseek-v4.1-flash": {"maxTokens": 64000}},
            )
            self.assertIn("local", written["providers"])
            self.assertEqual(json.loads((source / "models.json").read_text()), user_models)

    def test_missing_operator_models_file_still_gets_the_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = seed_agent_dir(Path(tmp) / "run", Path(tmp) / "none", "primalabs", "m", 32000)
            self.assertEqual(
                json.loads((target / "models.json").read_text()),
                {"providers": {"primalabs": {"modelOverrides": {"m": {"maxTokens": 32000}}}}},
            )
