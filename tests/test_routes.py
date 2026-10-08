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


def features(recursion=(), lemmas=(), claims=(), logic=()):
    """A successful extractor record, as the Lean metaprogram reports it."""
    return {"ok": True, "recursion": list(recursion), "lemmas": list(lemmas), "claims": list(claims), "logic": list(logic)}


def kernel_print(**parts):
    return routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", features(**parts))


INDUCTION = dict(recursion=["rec:UpdateStates"], lemmas=["Core.A", "Core.B", "Core.C", "Core.D"],
                 claims=["Eq#1", "Eq#2"], logic=["Exists.intro@Core.f", "contra"])
EQUATIONAL_KERNEL = dict(recursion=[], lemmas=["Core.E", "Core.F", "Core.G", "Core.D"],
                         claims=["Eq#3"], logic=["Exists.intro@Core.f"])


class KernelTests(unittest.TestCase):
    def test_kernel_part_drops_plumbing_and_merges_lemma_variants(self):
        part = routes.kernel(features(lemmas=["Eq.mpr", "congrArg", "Nat.add_comm'", "Int.add_comm", "foo_left", "foo_right",
                                              "Finset.card_bij'", "Finset.card_bij", "Core.X"],
                                      logic=["Exists.intro@_private.Mod.0.Core.W"]))
        self.assertEqual(part["lemmas"], ["Core.X", "Finset.card_bij", "NatInt.add_comm", "foo"])
        self.assertEqual(part["logic"], ["Exists.intro@Core.W"])

    def test_features_make_a_kernel_fingerprint_and_failure_falls_back_to_text(self):
        self.assertEqual(kernel_print(**INDUCTION)["source"], "kernel")
        failed = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", {"ok": False, "error": "timeout"})
        self.assertEqual((failed["source"], "kernel" in failed), ("text", False))
        self.assertTrue(failed["induction"])

    def test_identical_features_are_one_route_whatever_the_text(self):
        same = routes.similarity(routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", features(**INDUCTION)),
                                 routes.fingerprint(EQUATIONAL, VOCAB, "Core.X", features(**INDUCTION)))
        self.assertEqual(same, 1.0)

    def test_recursion_is_a_part_of_the_score_and_never_a_veto(self):
        left, right = kernel_print(**INDUCTION), kernel_print(**{**INDUCTION, "recursion": []})
        score = routes.similarity(left, right)
        self.assertAlmostEqual(score, 1 - routes.WEIGHTS["recursion"])
        # two proofs without any recursion agree on that part
        self.assertAlmostEqual(routes.similarity(right, right), 1.0)

    def test_rare_lemmas_weigh_more_than_common_ones(self):
        prints = [kernel_print(lemmas=["Core.common", "Core.rare"]), kernel_print(lemmas=["Core.common"]),
                  kernel_print(lemmas=["Core.common"]), kernel_print(lemmas=["Core.common"])]
        weights = routes.idf(prints)["lemmas"]
        self.assertGreater(weights["Core.rare"], weights["Core.common"])
        shared_rare = routes.similarity(kernel_print(lemmas=["Core.common", "Core.rare"]),
                                        kernel_print(lemmas=["Core.rare", "Core.other"]), routes.idf(prints))
        shared_common = routes.similarity(kernel_print(lemmas=["Core.common", "Core.x"]),
                                          kernel_print(lemmas=["Core.common", "Core.y"]), routes.idf(prints))
        self.assertGreater(shared_rare, shared_common)

    def test_induction_and_equational_routes_separate(self):
        a, b = kernel_print(**INDUCTION), kernel_print(**EQUATIONAL_KERNEL)
        self.assertLess(routes.similarity(a, b), routes.SAME_ROUTE)

    def test_a_route_is_compared_by_its_first_proof_so_it_cannot_drift(self):
        base = dict(recursion=[], logic=["contra"], claims=["Eq#1"])
        first = kernel_print(lemmas=["L1", "L2", "L3", "L4"], **base)
        second = kernel_print(lemmas=["L1", "L2", "L3", "L5"], **base)
        third = kernel_print(lemmas=["L1", "L5", "L6", "L7"], **{**base, "claims": ["Eq#9"]})
        events = []
        for print_ in (first, second, third):
            route, _ = routes.assign(events, print_)
            events.append({"route": route, "fingerprint": print_})
        # the third resembles the second but not the first, so it starts its own route
        self.assertEqual([e["route"] for e in events], ["r1", "r1", "r2"])

    def test_label_names_the_recursion_change_and_the_lemma_difference(self):
        reference = kernel_print(**INDUCTION)
        other = kernel_print(recursion=["rec:List"], lemmas=["Core.A", "Core.Z"], claims=[], logic=[])
        text = routes.label(other, reference)
        self.assertTrue(text.startswith("recursion: List.rec instead of UpdateStates.rec; "))
        self.assertIn("+Core.Z", text)
        self.assertIn("\u2212Core.B", text)
        self.assertEqual(routes.label(reference, None), "recursion: UpdateStates.rec; Core.A, Core.B, Core.C")

    def test_mixed_sources_compare_by_text(self):
        text = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X")
        self.assertEqual(routes.similarity(text, kernel_print(**INDUCTION)), routes.text_similarity(text, kernel_print(**INDUCTION)))


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
            with patch("arena.context.cached_context", return_value=context), \
                    patch("arena.route_features.extract", side_effect=lambda name, proofs: {
                        tag: features(**(INDUCTION if proof == INDUCTIVE else EQUATIONAL_KERNEL)) | {"tag": tag}
                        for tag, proof in proofs.items()}):
                first = campaign._record_route(directory, "Core.X", "p1", INDUCTIVE)
                again = campaign._record_route(directory, "Core.X", "p1", INDUCTIVE)
                second = campaign._record_route(directory, "Core.X", "p2", EQUATIONAL)
            self.assertEqual((first["route"], second["route"], again), ("r1", "r2", None))
            rows = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
            self.assertEqual([row["kind"] for row in rows], ["route", "route"])
            self.assertTrue(rows[1]["new"])
            self.assertEqual((rows[0]["source"], rows[1]["source"]), ("kernel", "kernel"))
            self.assertTrue(rows[1]["label"].startswith("recursion: none instead of UpdateStates.rec"))

    def test_record_route_falls_back_to_text_when_extraction_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with patch("arena.context.cached_context", return_value={}), \
                    patch("arena.route_features.extract", side_effect=RuntimeError("no Lean")):
                event = campaign._record_route(directory, "Core.X", "p1", INDUCTIVE)
            self.assertEqual(event["source"], "text")
            self.assertEqual(event["label"], "induction")


if __name__ == "__main__":
    unittest.main()
