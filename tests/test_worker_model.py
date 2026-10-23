"""A normal run's worker model: the OpenRouter GLM entry, the run flag and its resume check, and the packet's team line."""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import context, models
from tests.test_text import ROWS, _fixture

run_cli = importlib.import_module("arena.cli.run")
GLM = "glm-5.3-flash"
SOL = "gpt-6.1-sol"
THEOREM = "Core.InitsUpdatesComm"


class GlmEntryTests(unittest.TestCase):
    def test_glm_entry_validates_and_is_pinned_to_z_ai_on_openrouter(self):
        config = models.validate(models.parse(models.PATH.read_text()))
        self.assertEqual(config["models"][GLM]["provider"], "openrouter-pin")
        self.assertEqual(models.pi_model(GLM, config), "openrouter-pin/z-ai/glm-5.3-flash")
        registered = models.pi_providers(config)["openrouter-pin"]
        self.assertEqual(registered["apiKey"], "$OPENROUTER_API_KEY")
        compat = {row["id"]: row["compat"] for row in registered["models"]}
        self.assertEqual(compat["z-ai/glm-5.3-flash"], {"openRouterRouting": {"only": ["z-ai"]}})
        self.assertEqual(compat["deepseek/deepseek-v4.1-flash-1017"], {"openRouterRouting": {"only": ["deepseek"]}})


class WorkerFlagTests(unittest.TestCase):
    def dry_run(self, **flags) -> tuple[int, str]:
        options = run_cli.RunOptions(model=SOL, theorem=THEOREM, run_id="worker-model-dry-run-test", limit_usd=1.0,
                                     dry_run=True, plain=True, **flags)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = run_cli.run(options)
        return code, err.getvalue()

    def test_worker_model_is_accepted_on_a_normal_run(self):
        self.assertEqual(self.dry_run(worker_model=GLM)[0], 0)
        self.assertEqual(self.dry_run(worker_model="no-such-model")[0], 2)

    def test_resume_refuses_a_different_worker_model(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "run-config.json").write_text(json.dumps(
                {"theorem": THEOREM, "model": SOL, "limit_usd": 1.0, "thinking": "high", "skill": None}))
            options = run_cli.RunOptions(model=SOL, theorem=THEOREM, run_id="worker-model-resume-test", limit_usd=1.0,
                                         resume_run=True, dry_run=True, plain=True, worker_model=GLM)
            err = io.StringIO()
            with (patch.object(run_cli, "run_dir", return_value=Path(directory)),
                  contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO())):
                code = run_cli.run(options)
        self.assertEqual(code, 2)
        self.assertIn("resume worker model differs", err.getvalue())


class WorkerPacketTests(unittest.TestCase):
    def test_packet_names_the_run_worker_model(self):
        cached, measured = _fixture("ski")
        with (
            patch.object(context, "cached_context", return_value=cached),
            patch.object(context, "reference_profile", return_value=measured),
        ):
            body = dict(context.packet_sections(ROWS["ski"], cache_only=True, model=SOL, worker=GLM))["Team"]
        self.assertIn(f"worker sessions ({GLM})", body)
        self.assertNotIn("deepseek-v4.1-flash", body)


if __name__ == "__main__":
    unittest.main()
