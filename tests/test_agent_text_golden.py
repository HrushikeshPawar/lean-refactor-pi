"""The text moved by ticket 05a must render exactly as it did before the move."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import context, memory
from arena.skill import skill_prompt

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class AgentTextGoldenTests(unittest.TestCase):
    def test_skill_packet_and_memory_outputs_match_the_pre_move_bytes(self):
        cases = json.loads((FIXTURES / "agent_text_golden.json").read_text())
        for case in cases:
            with self.subTest(case=case["id"]):
                if case["id"] == "skill_prompt":
                    actual = skill_prompt()
                elif case["id"].startswith("packet_"):
                    context_data = json.loads((FIXTURES / "agent_text" / f"{case['fixture']}-context.json").read_text())
                    profile_data = json.loads((FIXTURES / "agent_text" / f"{case['fixture']}-profile.json").read_text())
                    name = case["id"].removeprefix("packet_")
                    row_name = {
                        "core": "Core.InitsUpdatesComm",
                        "ski": "Cslib.SKI.parallelReduction_diamond",
                    }[name]
                    with (
                        patch.object(context, "lean_context", return_value=context_data),
                        patch.object(context, "reference_profile", return_value=profile_data),
                        patch.object(context, "_scope_section", return_value=case["scope"]),
                        patch.object(context, "_imports", return_value=case["imports"]),
                    ):
                        actual = context.render_packet(row_name)
                else:
                    actual = memory.memory_text(case["front"], case["spent_usd"], case["cap_usd"])
                self.assertEqual(actual, case["expected"])
