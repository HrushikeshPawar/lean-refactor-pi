"""Post-compaction memory: built from the harness's own state, no model bookkeeping."""

import unittest

from arena.memory import memory_text

FRONT = {
    "best": {"candidate": "#4", "tokens": 120, "heartbeats": 900, "proxy": 61.5, "status": "full"},
    "routes": [{"route": "r1", "label": "no induction: updatedStatesComm", "original": True, "attempts": 0,
                "best_proxy": None, "best_candidate": None},
               {"route": "r2", "label": "induction", "original": False, "attempts": 3, "best_proxy": 61.5,
                "best_candidate": "#4"}],
    "ideas": [{"id": "i1", "title": "rewrite", "status": "parked", "attempts": 2, "best": None, "last_failure": "#3: unsolved goals"},
              {"id": "i2", "title": "induct", "status": "active", "attempts": 3,
               "best": {"candidate": "#4", "tokens": 120, "heartbeats": 900, "proxy": 61.5}}],
    "recent_failures": [{"ref": "#3", "idea_id": "i1", "error": "unsolved goals"}],
    "advisory": None, "candidates": 5, "evaluations": 7, "probes": 2,
}


class MemoryTests(unittest.TestCase):
    def test_memory_states_best_routes_ideas_failures_and_allowance(self):
        text = memory_text(FRONT, 1.25, 3)
        self.assertIn("#4 proxy 61.5 (verified)", text)
        self.assertIn("r2 \"induction\": 3 attempts, best proxy 61.5 (#4)", text)
        self.assertIn("i2 \"induct\" [active]: 3 attempts, best #4", text)
        self.assertIn("#3 (i1): unsolved goals", text)
        self.assertIn("$1.2500 of $3 spent, $1.7500 left", text)

    def test_active_ideas_come_first_and_the_list_is_capped(self):
        ideas = [{"id": f"i{n}", "title": "t", "status": "parked", "attempts": n} for n in range(12)]
        ideas.append({"id": "act", "title": "t", "status": "active", "attempts": 0})
        text = memory_text({**FRONT, "ideas": ideas})
        self.assertLess(text.index("act \"t\""), text.index("i11"))
        self.assertIn("(+5 more)", text)

    def test_depth_fields_on_route_rows_leave_the_memory_text_byte_identical(self):
        depth = {"depth": 4, "new_states": 4, "min_holes": 0, "stale_streak": 6, "stale": True, "compiled": True,
                 "explored": True, "credited": True, "skeleton": True}
        deeper = {**FRONT, "routes": [{**row, **depth} for row in FRONT["routes"]]}
        self.assertEqual(memory_text(deeper, 1.25, 3), memory_text(FRONT, 1.25, 3))

    def test_empty_run_still_renders(self):
        text = memory_text({})
        self.assertIn("none verified yet", text)
        self.assertNotIn("Allowance", text)


if __name__ == "__main__":
    unittest.main()
