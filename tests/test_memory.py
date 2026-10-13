"""Post-compaction memory: built from the harness's own state, no model bookkeeping."""

import unittest
from typing import cast

from arena.memory import memory_text

FRONT = {
    "best": {"candidate": "#4", "tokens": 120, "heartbeats": 900, "proxy": 61.5, "status": "full"},
    "routes": [
        {
            "route": "r1",
            "label": "no induction: updatedStatesComm",
            "original": True,
            "attempts": 0,
            "best_proxy": None,
            "best_candidate": None,
        },
        {
            "route": "r2",
            "label": "induction",
            "original": False,
            "attempts": 3,
            "best_proxy": 61.5,
            "best_candidate": "#4",
        },
    ],
    "ideas": [
        {
            "id": "i1",
            "title": "rewrite",
            "status": "parked",
            "attempts": 2,
            "best": None,
            "last_failure": "#3: unsolved goals",
        },
        {
            "id": "i2",
            "title": "induct",
            "status": "active",
            "attempts": 3,
            "best": {"candidate": "#4", "tokens": 120, "heartbeats": 900, "proxy": 61.5},
        },
    ],
    "recent_failures": [{"ref": "#3", "idea_id": "i1", "error": "unsolved goals"}],
    "advisory": None,
    "candidates": 5,
    "evaluations": 7,
    "probes": 2,
}


class MemoryTests(unittest.TestCase):
    def test_memory_keeps_best_node_failure_and_allowance_without_ideas_or_routes(self):
        text = memory_text(FRONT, 1.25, 3)
        self.assertIn("#4 proxy 61.5 (verified)", text)
        self.assertNotIn("r2", text)
        self.assertNotIn("induct", text)
        self.assertNotIn("i1", text)
        self.assertIn("#3: unsolved goals", text)
        self.assertIn("$1.2500 of $3 spent, $1.7500 left", text)

    def test_internal_idea_state_is_not_injected_after_compaction(self):
        ideas = [{"id": f"i{n}", "title": "t", "status": "parked", "attempts": n} for n in range(12)]
        ideas.append({"id": "act", "title": "t", "status": "active", "attempts": 0})
        text = memory_text({**FRONT, "ideas": ideas})
        self.assertNotIn('act "t"', text)
        self.assertNotIn("i11", text)

    def test_depth_fields_on_route_rows_add_only_neutral_facts(self):
        depth = {
            "depth": 4,
            "new_states": 4,
            "min_holes": 0,
            "stale_streak": 6,
            "stale": True,
            "compiled": True,
            "explored": True,
            "credited": True,
            "skeleton": True,
        }
        routes = cast(list[dict], FRONT["routes"])
        deeper = {**FRONT, "routes": [{**row, **depth} for row in routes]}
        text = memory_text(deeper, 1.25, 3)
        self.assertNotIn("r2", text)
        self.assertIn("Work so far", text)

    def test_empty_run_still_renders(self):
        text = memory_text({})
        self.assertIn("none verified yet", text)
        self.assertNotIn("Allowance", text)


if __name__ == "__main__":
    unittest.main()
