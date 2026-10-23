"""Golf mode: the run flags, the run-config team settings, and the polishing packet. No Lean, no provider."""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import context, orchestration
from arena.pi_rpc import WORKER_MODEL
from tests.test_text import ROWS, _fixture

run_cli = importlib.import_module("arena.cli.run")  # `arena.cli.run` the attribute is the command function
RunOptions = run_cli.RunOptions
SOL = "gpt-6.1-sol"
THEOREM = "Core.InitsUpdatesComm"


def _dry_run(seed: Path | None, **flags) -> tuple[int, str]:
    options = RunOptions(model=SOL, theorem=THEOREM, run_id="golf-mode-dry-run-test", limit_usd=1.0,
                         seed_proof=seed, dry_run=True, plain=True, **flags)
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = run_cli.run(options)
    return code, err.getvalue()


class GolfFlagTests(unittest.TestCase):
    def setUp(self):
        rows = [json.loads(line) for line in (run_cli.ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines()]
        proof = next(row for row in rows if row["name"] == THEOREM)["src"]
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.seed = Path(self.directory.name) / "best.lean"
        self.seed.write_text(proof + "\n")

    def test_golf_needs_a_seed_proof(self):
        code, err = _dry_run(None, golf=True)
        self.assertEqual(code, 2)
        self.assertIn("--seed-proof", err)

    def test_team_flags_need_golf(self):
        for flags in ({"workers": 2}, {"worker_model": SOL}):
            code, err = _dry_run(self.seed, **flags)
            self.assertEqual((code, "need --golf" in err), (2, True), flags)

    def test_workers_are_one_to_three_and_the_model_is_known(self):
        for flags in ({"workers": 0}, {"workers": 4}, {"worker_model": "no-such-model"}):
            self.assertEqual(_dry_run(self.seed, golf=True, **flags)[0], 2, flags)

    def test_valid_golf_options_pass_a_dry_run(self):
        self.assertEqual(_dry_run(self.seed, golf=True)[0], 0)
        self.assertEqual(_dry_run(self.seed, golf=True, workers=3, worker_model=SOL)[0], 0)

    def test_team_defaults(self):
        self.assertEqual(run_cli._golf_team(None, None), {"worker_model": WORKER_MODEL, "workers": 2})
        self.assertEqual(run_cli._golf_team(SOL, 3), {"worker_model": SOL, "workers": 3})


class RunConfigTeamTests(unittest.TestCase):
    def config(self, **values) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        (Path(directory.name) / "run-config.json").write_text(json.dumps({"theorem": THEOREM, **values}))
        return Path(directory.name)

    def test_a_normal_run_keeps_the_module_defaults(self):
        directory = self.config()
        self.assertEqual(orchestration.worker_model(directory), WORKER_MODEL)
        self.assertEqual(orchestration.slot_limit(directory), orchestration._MODEL_SLOTS)
        self.assertFalse(orchestration.is_golf(directory))
        self.assertEqual(orchestration.slot_limit(Path(tempfile.gettempdir()) / "no-such-run"), orchestration._MODEL_SLOTS)

    def test_a_golf_run_takes_model_and_slots_from_its_config(self):
        directory = self.config(golf=True, worker_model=SOL, workers=3)
        self.assertEqual(orchestration.worker_model(directory), SOL)
        self.assertEqual(orchestration.slot_limit(directory), 3)
        self.assertTrue(orchestration.is_golf(directory))

    def test_the_slot_limit_still_follows_the_patched_default(self):
        with patch.object(orchestration, "_MODEL_SLOTS", 2):
            self.assertEqual(orchestration.slot_limit(self.config()), 2)


class GolfPacketTests(unittest.TestCase):
    def team(self, **golf):
        cached, measured = _fixture("ski")
        with (
            patch.object(context, "cached_context", return_value=cached),
            patch.object(context, "reference_profile", return_value=measured),
        ):
            return dict(context.packet_sections(ROWS["ski"], cache_only=True, model=SOL, golf=golf or None))["Team"]

    def test_golf_packet_names_the_team_roles_and_the_composite(self):
        body = self.team(workers=3, worker_model=SOL)
        self.assertIn(f"{3} worker sessions ({SOL})", body)
        for role in ("Trim", "Heartbeat", "Structure"):
            self.assertIn(role, body)
        self.assertIn("composite score", body)
        self.assertIn("No best is final", body)
        self.assertNotIn("less than yours", body)  # same model: no price ratio

    def test_normal_packet_is_unchanged(self):
        body = self.team()
        self.assertIn("worker sessions (deepseek-v4.1-flash)", body)
        self.assertNotIn("composite score", body)

    def test_golf_start_section_shows_the_best_proof(self):
        section = context.golf_start_section("abc123", 91.5, "theorem t : True := by\n  trivial\n")
        self.assertIn("abc123", section)
        self.assertIn("91.5", section)
        self.assertIn("  trivial", section)

    def test_golf_packet_fits_the_packet_word_budget(self):
        from arena import text

        keys = ("packet/task", "packet/scoring", "packet/price-table", "packet/price-table.legend", "packet/search",
                "packet/golf-team", "packet/team-cost", "packet/sections.titles.goals", "packet/sections.titles.library")
        self.assertLessEqual(sum(len(text.template(key).split()) for key in keys), text.numbers()["budget.packet_words"])


if __name__ == "__main__":
    unittest.main()
