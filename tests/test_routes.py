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


SKELETON = dict(recursion=["rec:UpdateStates"], lemmas=["Core.A"])


def partial(holes=2, synthetic=0, **parts):
    return features(**parts) | {"holes": holes, "synthetic": synthetic, "read": True, "ok": False}


class SkeletonTests(unittest.TestCase):
    """A skeleton lacks the lemmas that later fill its holes; it is compared on what it has, as containment."""

    def route_of(self, earlier, current):
        return routes.assign(earlier, current)[0]

    def test_a_completed_proof_of_the_same_induction_stays_on_the_skeleton_route(self):
        skeleton = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", partial(**SKELETON))
        done = kernel_print(**INDUCTION)
        self.assertTrue(routes.incomplete(skeleton))
        self.assertEqual(self.route_of([{"route": "r1", "fingerprint": skeleton}], done), "r1")
        self.assertGreaterEqual(routes.similarity(skeleton, done), routes.SAME_ROUTE)
        # Without renormalizing, the completed proof's extra lemmas, claims and logic would make it a stranger.
        plain = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", features(**SKELETON))
        self.assertLess(routes.similarity(plain, done), routes.SAME_ROUTE)

    def test_a_different_recursion_is_a_new_route(self):
        skeleton = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", partial(**SKELETON))
        other = kernel_print(recursion=["rec:Core.InitStates"], lemmas=["Core.E", "Core.F"], claims=["Eq#3"])
        equational = kernel_print(**EQUATIONAL_KERNEL)
        for done in (other, equational):
            self.assertEqual(self.route_of([{"route": "r1", "fingerprint": skeleton}], done), "r2")

    def test_a_skeleton_arriving_after_a_complete_proof_joins_its_route_or_opens_its_own(self):
        done = {"route": "r1", "fingerprint": kernel_print(**INDUCTION)}
        same = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", partial(**SKELETON))
        different = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", partial(recursion=["rec:Core.InitStates"]))
        self.assertEqual(self.route_of([done], same), "r1")
        self.assertEqual(self.route_of([done], different), "r2")

    def test_error_recovery_sorries_make_a_proof_incomplete_too(self):
        errored = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X", partial(holes=0, synthetic=2, **SKELETON))
        self.assertTrue(routes.incomplete(errored))
        self.assertFalse(routes.incomplete(kernel_print(**INDUCTION)))

    def test_the_kernel_part_carries_holes_and_synthetic_counts(self):
        kernel = routes.kernel(partial(holes=3, synthetic=1, **SKELETON))
        self.assertEqual((kernel["holes"], kernel["synthetic"]), (3, 1))
        self.assertTrue(routes.fingerprint("x", features=partial())["source"] == "kernel")


class RecordingTests(unittest.TestCase):
    """Credit: only a kernel fingerprint that matches no exemplar opens a credited route."""

    CONTEXT = {"earlier": [{"name": name, "decl": "theorem"} for name in VOCAB]}

    def record(self, directory, proof_id, proof, record=None, kind="candidate", origin="model", error=None):
        if kind == "candidate":
            campaign._append(directory, {"kind": "candidate", "candidate_id": proof_id, "parents": [], "origin": origin})
            campaign._append(directory, {"kind": "evaluation", "candidate_id": proof_id, "mode": "fast", "result": {}})
        else:
            campaign._append(directory, {"kind": "probe", "proof_id": proof_id, "result": {}})

        def extract(name, proofs):
            if error:
                raise RuntimeError(error)
            return {tag: record | {"tag": tag} for tag in proofs}
        with patch("arena.context.cached_context", return_value=self.CONTEXT), patch("arena.route_features.extract", side_effect=extract):
            return campaign._record_route(directory, "Core.X", proof_id, proof)

    def test_the_original_is_never_credited_and_a_skeleton_stays_on_its_route(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            original = self.record(directory, "ref", INDUCTIVE, features(**INDUCTION), origin="reference")
            skeleton = self.record(directory, "s1", INDUCTIVE, partial(**SKELETON), kind="probe")
            self.assertEqual((original["route"], original["credited"], original["new"]), ("r1", False, True))
            self.assertEqual((skeleton["route"], skeleton["credited"], skeleton["new"]), ("r1", False, False))
            self.assertEqual((skeleton["attempt_kind"], skeleton["skeleton"], skeleton["holes"], skeleton["assigned_by"]),
                             ("probe", True, 2, "kernel"))

    def test_a_kernel_skeleton_opens_a_credited_route_and_an_errored_draft_needs_a_clean_attempt_for_credit(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self.record(directory, "ref", INDUCTIVE, features(**INDUCTION), origin="reference")
            opened = self.record(directory, "s2", EQUATIONAL, partial(holes=1, recursion=[], lemmas=["Core.E", "Core.F"]), kind="probe")
            errored = self.record(directory, "s3", EQUATIONAL, partial(holes=0, synthetic=1, recursion=["rec:Core.InitStates"],
                                                                      lemmas=["Core.G"]) | {"errored": True}, kind="probe")
            self.assertEqual((opened["route"], opened["credited"], opened["skeleton"]), ("r2", True, True))
            self.assertEqual((errored["route"], errored["credited"], errored["skeleton"], errored["errored"]), ("r3", False, False, True))
            history = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
            self.assertFalse(next(row for row in routes.route_table(history) if row["route"] == "r3")["credited"])
            self.record(directory, "s4", EQUATIONAL, partial(holes=1, recursion=["rec:Core.InitStates"], lemmas=["Core.G"]), kind="probe")
            history = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
            self.assertTrue(next(row for row in routes.route_table(history) if row["route"] == "r3")["credited"])

    def test_text_fallback_never_opens_a_credited_route_and_joins_the_best_text_match(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = self.record(directory, "t0", INDUCTIVE, None, error="no Lean")
            later = self.record(directory, "t1", EQUATIONAL, None, kind="probe", error="no Lean")
            self.assertEqual((first["route"], first["new"], first["credited"]), ("r1", True, False))
            # Nothing it resembles, yet it joins the only route instead of opening one.
            self.assertEqual((later["route"], later["new"], later["credited"], later["assigned_by"]), ("r1", False, False, "text"))
            self.assertNotIn("holes", later)

    def test_a_model_attempt_with_no_content_in_its_skeleton_cannot_open_a_route(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self.record(directory, "ref", INDUCTIVE, features(**INDUCTION), origin="reference")
            empty = self.record(directory, "e1", STATEMENT + " := by\n  intro h\n  sorry\n", partial(holes=1), kind="probe")
            self.assertEqual((empty["route"], empty["credited"], empty["assigned_by"]), ("r1", False, "text"))

    def test_auto_merges_do_not_credit_routes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self.record(directory, "ref", INDUCTIVE, features(**INDUCTION), origin="reference")
            merged = self.record(directory, "m1", EQUATIONAL, features(**EQUATIONAL_KERNEL), origin="auto_merge")
            self.assertEqual((merged["route"], merged["new"], merged["credited"]), ("r2", True, False))


class DepthTests(unittest.TestCase):
    """Depth: distinct goal states per route; stale streak; explored; credited."""

    def ledger(self, attempts):
        """attempts: (id, route, goal text or None for a compiled proof, holes). The first is the reference."""
        rows, opened = [], set()
        for index, (identifier, route, goal, holes) in enumerate(attempts):
            origin = "reference" if index == 0 else "model"
            rows.append({"kind": "candidate", "candidate_id": identifier, "origin": origin, "parents": []})
            passed = goal is None
            diagnostics = [] if passed else [{"severity": "error", "message": "unsolved goals\n" + goal}]
            result = {"compat": {"v": {"passed": passed, "diagnostics": diagnostics, "goals": []}}, "contains_sorry": False}
            rows.append({"kind": "evaluation", "candidate_id": identifier, "mode": "fast", "result": result})
            rows.append({"kind": "route", "proof_id": identifier, "route": route, "new": route not in opened,
                         "source": "kernel", "label": route, "holes": holes, "synthetic": 0, "skeleton": holes > 0})
            opened.add(route)
        return rows

    def goal(self, target):
        return f"P : Prop\n⊢ {target}"

    def test_attempts_that_leave_the_same_goals_are_stale_and_new_goals_are_depth(self):
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 2), ("c", "r2", self.goal("A"), 2),
                            ("d", "r2", self.goal("A  "), 2), ("e", "r2", self.goal("B"), 1), ("f", "r2", self.goal("B"), 1)])
        row = {item["route"]: item for item in routes.route_table(rows)}["r2"]
        self.assertEqual((row["attempts"], row["depth"], row["new_states"], row["stale_streak"], row["min_holes"]), (5, 2, 2, 1, 1))
        self.assertFalse(row["explored"])
        self.assertTrue(row["credited"] and row["skeleton"])

    def test_a_route_is_explored_at_three_goal_states_or_with_a_compiled_proof(self):
        deep = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 1), ("c", "r2", self.goal("B"), 1), ("d", "r2", self.goal("C"), 1)])
        self.assertTrue({r["route"]: r for r in routes.route_table(deep)}["r2"]["explored"])
        done = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 1), ("c", "r2", None, 0)])
        row = {r["route"]: r for r in routes.route_table(done)}["r2"]
        self.assertEqual((row["compiled"], row["explored"], row["depth"], row["min_holes"]), (True, True, 2, 0))

    def test_the_reference_seeds_closed_so_a_cosmetic_compiled_variant_of_it_is_not_new(self):
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r1", None, 0)])
        row = routes.route_table(rows)[0]
        self.assertEqual((row["original"], row["credited"], row["attempts"], row["depth"], row["stale_streak"]), (True, False, 1, 0, 1))

    def test_stale_flag_at_the_streak_limit_and_it_breaks_on_a_new_state(self):
        same = [(f"x{n}", "r2", self.goal("A"), 1) for n in range(routes.STALE_STREAK + 1)]
        rows = self.ledger([("ref", "r1", None, 0), *same])
        row = {r["route"]: r for r in routes.route_table(rows)}["r2"]
        self.assertEqual((row["depth"], row["stale_streak"], row["stale"]), (1, routes.STALE_STREAK, True))
        rows = self.ledger([("ref", "r1", None, 0), *same, ("y", "r2", self.goal("Z"), 1)])
        row = {r["route"]: r for r in routes.route_table(rows)}["r2"]
        self.assertEqual((row["stale_streak"], row["stale"]), (0, False))

    def test_progress_counts_credited_explored_and_the_share_of_new_state_attempts(self):
        rows = self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 1), ("c", "r2", self.goal("A"), 1), ("d", "r2", self.goal("B"), 1)])
        table = routes.route_table(rows)
        self.assertEqual(routes.progress(table), {"credited_routes": 1, "explored_routes": 0, "new_state_attempts": 2,
                                                  "new_state_share": round(2 / 3, 3)})
        self.assertIsNone(routes.progress([])["new_state_share"])

    def test_detail_text_extends_the_route_line_and_the_memory_line_is_unchanged(self):
        table = routes.route_table(self.ledger([("ref", "r1", None, 0), ("b", "r2", self.goal("A"), 2)]))
        detail = routes.routes_detail_text(table)
        self.assertIn('r2 "r2": 1 attempt, 1 goal state, min holes 2, opened, credited (opened by a skeleton), no scored proof', detail)
        self.assertIn('r2 "r2": 1 attempt, no scored proof', routes.routes_text(table))


if __name__ == "__main__":
    unittest.main()


class RouteQueueTests(unittest.TestCase):
    def test_one_worker_drains_the_queue_once_and_skips_filed_attempts(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            for proof_id in ("a1", "b2", "a1"):
                campaign._snapshot(directory, proof_id, f"theorem t : True := trivial -- {proof_id}")
            (directory / "route-queue.jsonl").write_text("".join(
                json.dumps({"proof_id": proof_id, "name": "Core.X"}) + "\n" for proof_id in ("a1", "b2", "a1", "c3")))
            campaign._append(directory, {"kind": "route", "proof_id": "b2", "route": "r1"})
            seen = []
            def record(directory_, name, proof_id, proof):
                seen.append(proof_id)
                campaign._append(directory_, {"kind": "route", "proof_id": proof_id, "route": "r1"})
            with patch.object(campaign, "_record_route", record), patch.object(campaign, "_room_for_extraction", lambda wait: True):
                self.assertEqual([entry["proof_id"] for entry in campaign._route_queue(directory)], ["a1", "c3"])
                campaign._route_worker(directory)
            self.assertEqual(seen, ["a1"])  # c3 has no snapshot, so it is skipped rather than retried forever
            self.assertFalse(campaign._worker_running(directory))


class ReferenceRouteTests(unittest.TestCase):
    """The reference proof is every route's yardstick: kernel print or nothing, filed first, original even if late."""

    CONTEXT = {"earlier": [{"name": name, "decl": "theorem"} for name in VOCAB]}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        campaign._append(self.directory, {"kind": "candidate", "candidate_id": "ref", "parents": [], "origin": "reference"})
        campaign._append(self.directory, {"kind": "candidate", "candidate_id": "c1", "parents": [], "origin": "model"})

    def record(self, proof_id, proof, extract):
        with patch("arena.context.cached_context", return_value=self.CONTEXT), \
                patch("arena.route_features.extract", side_effect=extract), \
                patch.object(campaign, "REFERENCE_RETRY_SECONDS", 0), patch.object(campaign, "_yield_to_lean_session"), \
                patch.object(campaign, "_room_for_extraction", lambda wait=0: True), \
                patch.dict("os.environ", {"ARENA_ROUTES_INLINE": "0"}):
            return campaign._record_route(self.directory, "Core.X", proof_id, proof)

    def routes_filed(self):
        return [r for r in campaign.events(self.directory) if r["kind"] == "route"]

    def test_a_reference_without_a_kernel_print_is_not_filed_from_text(self):
        def extract(name, proofs):
            return {tag: {"tag": tag, "ok": False, "error": "timeout"} for tag in proofs}
        self.assertIsNone(self.record("ref", INDUCTIVE, extract))
        self.assertEqual(self.routes_filed(), [])
        # an ordinary attempt still falls back to text
        self.assertEqual(self.record("c1", INDUCTIVE, extract)["source"], "text")

    def test_a_reference_is_retried_until_the_kernel_answers(self):
        calls = []
        def extract(name, proofs):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("memory")
            return {tag: features(**INDUCTION) | {"tag": tag} for tag in proofs}
        event = self.record("ref", INDUCTIVE, extract)
        self.assertEqual((len(calls), event["source"], event["credited"]), (3, "kernel", False))

    def test_the_worker_files_the_reference_first_and_tries_it_again(self):
        (self.directory / "route-queue.jsonl").write_text("".join(
            json.dumps({"proof_id": p, "name": "Core.X"}) + "\n" for p in ("c1", "ref")))
        self.assertEqual([e["proof_id"] for e in campaign._route_queue(self.directory)], ["ref", "c1"])
        for p in ("c1", "ref"):
            campaign._snapshot(self.directory, p, INDUCTIVE)
        seen = []
        def record(directory, name, proof_id, proof):
            seen.append(proof_id)
            return None  # extraction keeps failing
        with patch.object(campaign, "_record_route", record), patch.object(campaign, "_room_for_extraction", lambda wait: True), \
                patch.object(campaign, "_yield_to_lean_session"):
            campaign._route_worker(self.directory)
        self.assertEqual(seen, ["ref"] * campaign.REFERENCE_ROUNDS + ["c1"])

    def test_a_late_reference_marks_the_route_it_joins_as_original_and_not_credited(self):
        history = [
            {"kind": "candidate", "candidate_id": "ref", "origin": "reference", "parents": []},
            {"kind": "candidate", "candidate_id": "c1", "origin": "model", "parents": []},
            {"kind": "route", "proof_id": "c1", "route": "r1", "new": True, "source": "kernel", "credited": True, "label": "x"},
            {"kind": "route", "proof_id": "ref", "route": "r1", "new": False, "source": "kernel", "credited": False, "label": "x"}]
        row = routes.route_table(history)[0]
        self.assertTrue(row["original"])
        self.assertFalse(row["credited"])
        self.assertEqual(row["attempts"], 1)

    def test_a_text_exemplar_does_not_absorb_a_dissimilar_kernel_attempt(self):
        text = routes.fingerprint(INDUCTIVE, VOCAB, "Core.X")  # no kernel features
        earlier = [{"route": "r1", "fingerprint": text}]
        weak = kernel_print(recursion=["rec:UpdateStates"], lemmas=["Core.A"])
        weak["lemmas"] = ["InitStatesLength", "Other"]  # text overlap 1/3, above SAME_ROUTE=0.5? no: below TEXT_EXEMPLAR_MIN
        self.assertEqual(routes.assign(earlier, weak)[0], "r2")
        same = dict(weak, lemmas=text["lemmas"])
        self.assertEqual(routes.assign(earlier, same)[0], "r1")
