import shutil
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from arena import campaign, polish
from tests.test_protocol import FIXTURE, LEAN, cli

PROOF = """theorem t : A := by
  intro h
  have h2 := foo h
  cases h with
  | a =>
    simp_all
    exact bar
  | b =>
    omega
  skip
"""


class VariantTests(unittest.TestCase):
    def test_statement_and_blocks_with_children_are_never_deleted(self):
        edits = [v["edit"] for v in polish.line_variants(PROOF)]
        deletions = [e for e in edits if e.startswith("delete")]
        self.assertTrue(all("theorem t" not in e for e in deletions))
        self.assertFalse(any("cases h with" in e for e in deletions))
        self.assertFalse(any("| a =>" in e for e in deletions))
        self.assertTrue(any("delete line 10: skip" in e for e in deletions))
        for variant in polish.line_variants(PROOF):
            self.assertTrue(variant["proof"].startswith("theorem t : A := by\n"))

    def test_closing_tactics_are_substituted_only_on_closing_lines(self):
        subs = [v for v in polish.line_variants(PROOF) if "→" in v["edit"]]
        self.assertTrue(subs)
        self.assertTrue(all(v["edit"].startswith(("line 6:", "line 9:")) for v in subs))
        self.assertTrue(any("simp_all → grind" in v["edit"] for v in subs))
        self.assertEqual(len(polish.line_variants(PROOF, max_deletions=2, max_substitutions=3)),
                         2 + 3)

    def test_simp_suggestions_are_read_from_try_this(self):
        self.assertEqual(polish.suggestion("Try this: simp only [foo,\n    bar]"), "simp only [foo, bar]")
        self.assertEqual(polish.suggestion("Try this:\n  [apply] simp only [foo, bar]\nother.lean:1:0: warning: x"),
                         "simp only [foo, bar]")
        self.assertIsNone(polish.suggestion("Try this: exact foo"))
        self.assertIsNone(polish.suggestion("nothing"))
        self.assertEqual(polish.simp_lines(PROOF), [5])


class LockTests(unittest.TestCase):
    def test_lean_jobs_for_one_run_never_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            active, peak, lock = [0], [0], threading.Lock()

            def job():
                with campaign.lean_lock(directory):
                    with lock:
                        active[0] += 1
                        peak[0] = max(peak[0], active[0])
                    time.sleep(0.05)
                    with lock:
                        active[0] -= 1
            threads = [threading.Thread(target=job) for _ in range(4)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(peak[0], 1)


@LEAN
class PolishCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = f"test-{uuid.uuid4().hex[:10]}"
        cls.work = Path(tempfile.mkdtemp())
        assert "packet" in cli(cls.run_id, "init")
        path = cls.work / "redundant.lean"
        path.write_text(FIXTURE.read_text() + "\n  skip")
        cls.evaluated = cli(cls.run_id, "evaluate", "--proof-file", str(path))
        cls.redundant = cls.evaluated["candidate"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(campaign.run_dir(cls.run_id), ignore_errors=True)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_polish_finds_the_redundant_line_stores_it_as_a_probe_and_records_no_candidate(self):
        self.assertTrue(self.evaluated["ok"], self.evaluated)
        before = campaign.frontier(self.run_id)["candidates"]
        result = cli(self.run_id, "polish", "--candidate", self.redundant, "--max-deletions", "3", "--max-substitutions", "0", "--max-simp", "0")
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["improving"], 1)
        best = result["variants"][0]
        self.assertTrue(best["edit"].startswith("delete line"))
        self.assertEqual(best["delta"]["tokens"], -1)
        self.assertTrue(best["probe"].startswith("p"))
        self.assertNotIn("proof", best)
        self.assertEqual(campaign.frontier(self.run_id)["candidates"], before)
        promoted = cli(self.run_id, "evaluate", "--from-probe", best["probe"])
        self.assertTrue(promoted["ok"], promoted)
        self.assertEqual(promoted["tokens"], result["base"]["tokens"] - 1)
        self.assertEqual(campaign.frontier(self.run_id)["candidates"], before + 1)

    def test_a_non_compiling_candidate_is_refused_with_one_line(self):
        path = self.work / "broken.lean"
        path.write_text(FIXTURE.read_text().replace("exact updatedStateUpdate (InitStatesSomeMonotone Hold Hinits)", "exact rfl"))
        broken = cli(self.run_id, "evaluate", "--proof-file", str(path))
        result = cli(self.run_id, "polish", "--candidate", broken["candidate"])
        self.assertFalse(result["ok"])
        self.assertIn("does not compile", result["error"])


if __name__ == "__main__":
    unittest.main()
