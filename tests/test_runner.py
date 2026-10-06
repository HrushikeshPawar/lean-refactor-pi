"""Seam B: the budgeted runner end to end against the scripted offline provider."""

import unittest

from tests.pi_support import PI_AVAILABLE, FakeRun, message_text
from tools.arena_skill import SKILL_DIR, skill_hash

STOP = [{"text": "done"}]


@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SkillAndThinkingTests(unittest.TestCase):
    def tearDown(self):
        for run in getattr(self, "runs", []):
            run.cleanup()

    def start(self, *extra: str) -> FakeRun:
        run = FakeRun(STOP * 6)
        self.runs = [*getattr(self, "runs", []), run]
        return run.run(*extra)

    def test_skill_is_in_the_first_provider_payload_and_hash_is_recorded(self):
        run = self.start()
        first = run.requests[0]["messages"][0]
        self.assertIn("Scoring is mechanical", message_text(first))
        self.assertIn("arena_skill_read", message_text(first) + str(first.get("toolsAdded")))
        config = run.json("run-config.json")
        self.assertEqual(config["skill"], {"name": "arena-lean", "sha256": skill_hash()})

    def test_thinking_level_is_a_recorded_option_and_reaches_the_provider(self):
        default = self.start()
        self.assertEqual(default.json("run-config.json")["thinking"], "high")
        self.assertEqual({r["thinking"] for r in default.requests}, {"high"})
        low = self.start("--thinking", "low")
        self.assertEqual(low.json("run-config.json")["thinking"], "low")
        self.assertEqual({r["thinking"] for r in low.requests}, {"low"})

    def test_skill_can_be_switched_off_for_ab_runs(self):
        run = self.start("--no-skill")
        self.assertIsNone(run.json("run-config.json")["skill"])
        self.assertNotIn("Scoring is mechanical", message_text(run.requests[0]["messages"][0]))

    def test_skill_content_is_general(self):
        text = (SKILL_DIR / "SKILL.md").read_text()
        for phrase in ("InitsUpdatesComm", "induct", "Strata", "simp_all in", "witness"):
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
