"""Route fingerprints and clustering: pure functions plus ledger integration without Lean."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, routes

VOCAB = {"Core.updatedStatesComm", "Core.updatedStatesUpdate", "Core.InitStatesLength", "Core.UpdateStatesLength",
         "Core.InitStatesSomeMonotone"}
STATEMENT = "theorem Core.X (a : Nat) : a = a"
INDUCTIVE = STATEMENT + """ := by
  intro h
  have hl := InitStatesLength h
  induction a with
  | zero => simp
  | succ n ih => simp_all [InitStatesSomeMonotone]
"""
EQUATIONAL = STATEMENT + """ := by
  intro h
  have hl := InitStatesLength h
  rw [← updatedStatesComm]
  exact updatedStatesUpdate hl
"""
EQUATIONAL_GOLF = STATEMENT + """ := by
  intro h
  rw [← updatedStatesComm]
  exact updatedStatesUpdate (InitStatesLength h)
"""


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_reads_recursion_lemmas_and_skeleton(self):
        print_ = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X")
        self.assertTrue(print_["induction"])
        self.assertEqual(print_["lemmas"], ["InitStatesLength", "InitStatesSomeMonotone"])
        self.assertEqual(print_["skeleton"], ["intro", "have", "induction"])

    def test_comments_and_the_statement_are_ignored(self):
        text = "theorem Core.X : updatedStatesComm = 1 := by\n  -- induction here\n  /- induction -/\n  simp\n"
        print_ = routes.fingerprint(text, VOCAB, "Core.X")
        self.assertFalse(print_["induction"])
        self.assertEqual(print_["lemmas"], [])

    def test_a_call_to_the_theorem_itself_is_recursion(self):
        text = STATEMENT + " := by\n  exact X (a - 1)\n"
        self.assertTrue(routes.fingerprint(text, VOCAB, "Core.X")["induction"])

    def test_golf_stays_on_the_route_and_induction_leaves_it(self):
        eq = routes.fingerprint(EQUATIONAL, VOCAB, "Core.X")
        golf = routes.fingerprint(EQUATIONAL_GOLF, VOCAB, "Core.X")
        ind = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X")
        self.assertGreaterEqual(routes.similarity(eq, golf), routes.SAME_ROUTE)
        self.assertEqual(routes.similarity(eq, ind), 0.0)

    def test_without_lemmas_the_skeleton_decides(self):
        a = {"induction": False, "lemmas": [], "skeleton": ["intro", "omega"]}
        b = {"induction": False, "lemmas": [], "skeleton": ["intro", "simp", "omega"]}
        c = {"induction": False, "lemmas": [], "skeleton": ["nlinarith"]}
        self.assertGreaterEqual(routes.similarity(a, b), routes.SAME_ROUTE)
        self.assertEqual(routes.similarity(a, c), 0.0)

    def test_assignment_is_in_arrival_order(self):
        events = []
        for text in (INDUCTIVE, EQUATIONAL, EQUATIONAL_GOLF, INDUCTIVE):
            print_ = routes.fingerprint(text, VOCAB, "Core.X")
            route, _ = routes.assign(events, print_)
            events.append({"route": route, "fingerprint": print_})
        self.assertEqual([e["route"] for e in events], ["r1", "r2", "r2", "r1"])


class LedgerTests(unittest.TestCase):
    def history(self):
        def candidate(identifier, origin="model"):
            return {"kind": "candidate", "candidate_id": identifier, "origin": origin, "parents": []}

        def evaluation(identifier, proxy, mode="full"):
            return {"kind": "evaluation", "candidate_id": identifier, "mode": mode,
                    "result": {"metrics": {"proxy": proxy, "estimated_proxy": proxy}}}

        def route(identifier, name, label):
            return {"kind": "route", "proof_id": identifier, "route": name, "label": label}
        return [candidate("a", "reference"), route("a", "r1", "induction: x"),
                candidate("b"), route("b", "r1", "induction: x"), evaluation("b", 60),
                candidate("c"), route("c", "r2", "no induction: y"), evaluation("c", 80),
                candidate("d"), route("d", "r2", "no induction: y"), evaluation("d", 70, "fast"),
                candidate("e", "auto_merge"), route("e", "r2", "no induction: y")]

    def test_route_table_counts_attempts_and_best_proxy(self):
        table = {row["route"]: row for row in routes.route_table(self.history())}
        self.assertTrue(table["r1"]["original"])
        self.assertEqual((table["r1"]["attempts"], table["r1"]["best_proxy"], table["r1"]["best_candidate"]), (1, 60, "#2"))
        # The automatic merge does not count as a model attempt.
        self.assertEqual((table["r2"]["attempts"], table["r2"]["best_proxy"], table["r2"]["best_candidate"]), (2, 80, "#3"))
        self.assertTrue(table["r2"]["verified"])

    def test_routes_text_names_each_route(self):
        text = routes.routes_text(routes.route_table(self.history()))
        self.assertIn('r1 "induction: x" [the original proof\'s route]: 1 attempt, best proxy 60 (#2)', text)
        self.assertIn('r2 "no induction: y": 2 attempts, best proxy 80 (#3)', text)
        self.assertEqual(routes.routes_text([]), "none")

    def test_record_route_writes_one_event_per_proof(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            context = {"earlier": [{"name": name, "decl": "theorem"} for name in VOCAB]}
            with patch("arena.context.cached_context", return_value=context):
                first = campaign._record_route(directory, "Core.X", "p1", INDUCTIVE)
                again = campaign._record_route(directory, "Core.X", "p1", INDUCTIVE)
                second = campaign._record_route(directory, "Core.X", "p2", EQUATIONAL)
            self.assertEqual((first["route"], second["route"], again), ("r1", "r2", None))
            rows = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
            self.assertEqual([row["kind"] for row in rows], ["route", "route"])
            self.assertTrue(rows[1]["new"])
            self.assertTrue(rows[1]["label"].startswith("no induction"))


if __name__ == "__main__":
    unittest.main()
