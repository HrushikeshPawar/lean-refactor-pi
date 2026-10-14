"""Compaction memory is a projection of stored harness state."""

import unittest

from arena.memory import memory_text


class MemoryTests(unittest.TestCase):
    def test_memory_preserves_best_map_used_declarations_reads_and_holes(self):
        state = {
            "best": {
                "id": "n2",
                "price": "tokens 12, heartbeats 34, versions 2/2, score 70.00",
                "proof": "exact Lib.used",
            },
            "map": ["best n2 score 70.0 tokens 12 heartbeats 34"],
            "library": [
                {"name": "Lib.used", "handle": "decl:Lib.used", "module": "Lib", "signature": "Lib.used : X"},
                {"name": "Lib.unused", "handle": "decl:Lib.unused", "module": "Lib", "signature": "Lib.unused : Y"},
            ],
            "reads": [
                {"kind": "read", "handle": "decl:Lib.used", "first": 10, "last": 20},
                {"kind": "read", "handle": "decl:Lib.used", "first": 15, "last": 30},
                {"kind": "read", "handle": "decl:Other", "first": 2, "last": 3},
            ],
            "holes": [{"hole": "n2.h1", "goal": "X"}],
        }
        compacted = memory_text(state)
        seed = memory_text(state, seed=True)
        self.assertIn("exact Lib.used", compacted)
        self.assertIn(state["map"][0], compacted)
        self.assertIn("decl:Lib.used · Lib · Lib.used : X", compacted)
        self.assertNotIn("Lib.unused", compacted)
        self.assertIn("decl:Lib.used lines 10-30", compacted)
        self.assertIn("n2.h1: X", compacted)
        for old_item in ("Allowance:", "idea", "route"):
            self.assertNotIn(old_item, compacted)
        self.assertEqual(compacted.splitlines()[1:], seed.splitlines()[1:])
        self.assertNotEqual(compacted.splitlines()[0], seed.splitlines()[0])

    def test_empty_state_has_explicit_sections(self):
        result = memory_text({})
        self.assertIn("Best node:", result)
        self.assertIn("Map:", result)
        self.assertIn("Read so far:", result)


if __name__ == "__main__":
    unittest.main()
