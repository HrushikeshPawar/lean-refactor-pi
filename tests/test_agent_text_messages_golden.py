"""Golden checks for model-facing text captured before ticket 05b moves it."""

import json
import unittest
from pathlib import Path

from tests.pi_support import PI_AVAILABLE, FakeRun
from tests.slow import slow

ROOT = Path(__file__).resolve().parents[1]


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class ToolDefinitionsGoldenTests(unittest.TestCase):
    def test_registered_tool_definitions_match_the_pre_move_bytes(self):
        run = FakeRun(
            [
                {"tool_calls": [{"name": "arena_state", "arguments": {}}], "usage": {"output": 150_000}},
                {"text": "done"},
            ]
        ).run()
        try:
            self.assertEqual(run.result.returncode, 0, run.result.stderr + run.result.stdout[-2_000:])
            cases = json.loads((ROOT / "tests/fixtures/agent_text_tool_definitions_golden.json").read_text())
            self.assertEqual(run.requests[-1]["tool_definitions"], [case["expected"] for case in cases])
        finally:
            run.cleanup()
