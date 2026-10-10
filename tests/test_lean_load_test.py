"""Pure parts of tools/lean_load_test.py: workload generation, statistics, criteria, report."""

import random
import unittest

from tools import lean_load_test as llt

ROW = {"statement": "theorem t\n(x : Nat)\n: x = x", "src": "theorem t\n(x : Nat)\n: x = x := by\n  rfl"}


def rec(kind="sorry", lane="model", seconds=1.0, **extra):
    return {
        "kind": kind,
        "lane": lane,
        "version": "v1",
        "seconds": seconds,
        "ok": True,
        "timed_out": False,
        "post_warm": True,
        **extra,
    }


class Stats(unittest.TestCase):
    def test_percentile(self):
        self.assertIsNone(llt.percentile([], 50))
        self.assertEqual(llt.percentile([4], 95), 4.0)
        self.assertEqual(llt.percentile([1, 2, 3, 4, 5], 50), 3.0)
        self.assertAlmostEqual(llt.percentile([0, 10], 95), 9.5)
        self.assertEqual(llt.percentile([5, 1, 3], 100), 5.0)

    def test_summarise_groups(self):
        rows = llt.summarise([rec(seconds=1), rec(seconds=3), rec("slow", seconds=9, timed_out=True, ok=True)])
        self.assertEqual([(r["kind"], r["n"], r["timeouts"]) for r in rows], [("slow", 1, 1), ("sorry", 2, 0)])
        self.assertEqual(rows[1]["max"], 3)


class Workload(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(llt.make_proof("reference", ROW, 1, 10), ROW["src"])
        self.assertTrue(llt.make_proof("sorry", ROW, 1, 10).endswith(":= by\n  sorry"))
        self.assertIn("foo_does_not_exist_7", llt.make_proof("error", ROW, 7, 10))
        self.assertTrue(llt.make_proof("edit", ROW, 2, 10).startswith(ROW["src"]))
        self.assertNotEqual(llt.make_proof("edit", ROW, 2, 10), llt.make_proof("edit", ROW, 3, 10))
        slow = llt.make_proof("slow", ROW, 1, 100)
        self.assertIn("IO.sleep", slow)
        self.assertGreater(int(slow.split("IO.sleep ")[1].split("\n")[0]), 100_000)
        with self.assertRaises(ValueError):
            llt.make_proof("nope", ROW, 1, 1)

    def test_every_proof_starts_with_statement(self):
        for kind in llt.KINDS:
            self.assertTrue(llt.make_proof(kind, ROW, 1, 5).startswith(ROW["statement"]))

    def test_seeded_choice_is_reproducible(self):
        weights = llt.parse_weights(None)
        a = [llt.pick_kind(random.Random(3), weights) for _ in range(5)]
        rng1, rng2 = random.Random(9), random.Random(9)
        self.assertEqual(
            [llt.pick_kind(rng1, weights) for _ in range(50)], [llt.pick_kind(rng2, weights) for _ in range(50)]
        )
        self.assertEqual(len(a), 5)

    def test_weights(self):
        self.assertEqual(llt.parse_weights("slow=1"), {"slow": 1.0})
        rng = random.Random(0)
        self.assertEqual({llt.pick_kind(rng, {"slow": 1.0}) for _ in range(20)}, {"slow"})
        with self.assertRaises(ValueError):
            llt.parse_weights("bogus=1")

    def test_background_plan(self):
        rng = random.Random(1)
        plans = {llt.background_plan(["a", "b", "c"], "a", rng) for _ in range(100)}
        self.assertIn(("route", "a"), plans)
        self.assertTrue({("compat", "b"), ("compat", "c")} <= plans)
        self.assertEqual({llt.background_plan(["a"], "a", rng) for _ in range(10)}, {("route", "a")})

    def test_split_proof_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            llt.split_proof({"statement": "x", "src": "y"})


class Criteria(unittest.TestCase):
    samples = [{"mem_available_gb": 10.0}, {"mem_available_gb": 8.0}]

    def verdicts(self, records, runs=({"crashes": 0},), samples=None, orphans=()):
        return [r["ok"] for r in llt.evaluate(records, list(runs), samples or self.samples, list(orphans))]

    def healthy(self):
        return [
            rec(seconds=0.5),
            rec("slow", seconds=180, timed_out=True),
            rec("probe", seconds=0.6, after_timeout=True),
        ]

    def test_pass(self):
        self.assertEqual(self.verdicts(self.healthy()), [True] * 6)

    def test_timeout_outside_slow_fails_1_2_3(self):
        records = [*self.healthy(), rec("probe", seconds=180, timed_out=True, after_timeout=True)]
        verdicts = self.verdicts(records)
        self.assertEqual(verdicts[:3], [False, False, False])

    def test_failed_request_fails_1(self):
        self.assertFalse(self.verdicts([*self.healthy(), rec(ok=False, reason="x")])[0])

    def test_slow_background_ignored_for_3(self):
        records = [*self.healthy(), rec("compat", "background", seconds=120)]
        self.assertTrue(self.verdicts(records)[2])

    def test_fresh_open_fails_4_unless_crash(self):
        records = [*self.healthy(), rec(new_worker=True)]
        self.assertFalse(self.verdicts(records)[3])
        self.assertTrue(self.verdicts(records, runs=({"crashes": 1},))[3])

    def test_fresh_open_before_warm_is_fine(self):
        self.assertTrue(self.verdicts([*self.healthy(), rec(new_worker=True, post_warm=False)])[3])

    def test_orphans_and_memory(self):
        self.assertFalse(self.verdicts(self.healthy(), orphans=[123])[4])
        self.assertFalse(self.verdicts(self.healthy(), samples=[{"mem_available_gb": 2.5}])[5])

    def test_no_data_fails(self):
        self.assertFalse(all(self.verdicts([])))


class Report(unittest.TestCase):
    def test_render(self):
        records = [
            rec(seconds=0.5),
            rec("slow", seconds=180, timed_out=True),
            rec("probe", seconds=0.6, after_timeout=True),
        ]
        runs = [{"run": 0, "warm_mode": "warm", "warm_seconds": 12.3, "warm_ok": True, "crashes": 0}]
        samples = [{"mem_available_gb": 9.0, "lean_processes": 4, "ntfs_cpu_percent": 55.0}]
        results = llt.evaluate(records, runs, samples, [])
        text = llt.render_report({"runs": 1}, results, records, runs, samples, [])
        self.assertTrue(text.startswith("# Lean load test: PASS"))
        for needle in ("| probe | model | v1 |", "post-timeout probes: n=1", "12.3", "orphans: none"):
            self.assertIn(needle, text)
        failing = llt.evaluate(records, runs, samples, [9])
        self.assertTrue(
            llt.render_report({}, failing, records, runs, samples, [9]).startswith("# Lean load test: FAIL")
        )


if __name__ == "__main__":
    unittest.main()
