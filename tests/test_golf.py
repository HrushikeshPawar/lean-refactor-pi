"""The golf pass: variant generation, the greedy loop, the time cap, the run's closing path and the offline command."""

from __future__ import annotations

import contextlib
import importlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from arena import campaign, golf
from tests.graph_support import FakeRunCase

run_module = importlib.import_module("arena.cli.run")
golf_cli = importlib.import_module("arena.cli.golf")
STATEMENT = "theorem t : True"
PROOF = STATEMENT + " := by\n  intro h; clear h\n  simp [a, b, c]; ring <;> simp\n  extra\n  exact True.intro\n"
START = golf.body_start(PROOF, STATEMENT)


def by_kind(proof: str, kind: str) -> list[str]:
    return [variant.text for variant in golf.variants(proof, START) if variant.kind == kind]


class VariantTests(unittest.TestCase):
    def test_body_starts_after_the_statements_assignment(self):
        self.assertEqual(PROOF[START:].lstrip()[:5], "by\n  ")
        self.assertEqual(golf.body_start("theorem x : y", STATEMENT), 0)

    def test_each_list_item_is_deleted_in_turn(self):
        self.assertEqual(
            [text.splitlines()[2] for text in by_kind(PROOF, "list")],
            ["  simp [b, c]; ring <;> simp", "  simp [a, c]; ring <;> simp", "  simp [a, b]; ring <;> simp"],
        )

    def test_a_first_item_gives_its_leading_space_to_the_next(self):
        (_, second, _) = by_kind("theorem t : True := by\n  rw [ a, b, c]\n", "list")[:3]
        self.assertIn("rw [ a, c]", second)
        (first, *_) = by_kind("theorem t : True := by\n  rw [a, b]\n", "list")
        self.assertIn("rw [b]", first)

    def test_commas_inside_brackets_are_not_split(self):
        proof = "theorem t : True := by\n  simp [f (a, b), ⟨c, d⟩]\n"
        self.assertEqual(
            [text.splitlines()[1] for text in by_kind(proof, "list")], ["  simp [⟨c, d⟩]", "  simp [f (a, b)]"]
        )

    def test_a_single_item_list_has_nothing_to_delete(self):
        self.assertEqual(by_kind("theorem t : True := by\n  simp [a]\n", "list"), [])

    def test_each_body_line_is_deleted_and_the_header_is_kept(self):
        lines = by_kind(PROOF, "line")
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(text.startswith(STATEMENT + " := by\n") for text in lines))
        self.assertNotIn("  extra\n", lines[2])

    def test_each_segment_is_deleted_with_one_separator(self):
        texts = [text.splitlines()[1:3] for text in by_kind(PROOF, "segment")]
        self.assertIn(["  clear h", "  simp [a, b, c]; ring <;> simp"], texts)  # `intro h` gone
        self.assertIn(["  intro h", "  simp [a, b, c]; ring <;> simp"], texts)  # `clear h` gone
        self.assertIn(["  intro h; clear h", "  ring <;> simp"], texts)
        self.assertIn(["  intro h; clear h", "  simp [a, b, c] <;> simp"], texts)
        self.assertIn(["  intro h; clear h", "  simp [a, b, c]; ring"], texts)

    def test_separators_inside_brackets_do_not_split(self):
        self.assertEqual(by_kind("theorem t : True := by\n  exact ⟨a; b⟩\n", "segment"), [])

    def test_intro_then_clear_becomes_rintro_dash(self):
        same_line = by_kind("theorem t : True := by\n  intro h; clear h\n  simp\n", "rewrite")
        self.assertEqual(same_line, ["theorem t : True := by\n  rintro -\n  simp\n"])
        two_lines = by_kind("theorem t : True := by\n  intro h\n  clear h\n  simp\n", "rewrite")
        self.assertEqual(two_lines, ["theorem t : True := by\n  rintro -\n  simp\n"])
        self.assertEqual(by_kind("theorem t : True := by\n  intro h; clear k\n", "rewrite"), [])

    def test_adjacent_rintro_are_merged(self):
        merged = by_kind("theorem t : True := by\n  rintro -; rintro x\n  simp\n", "rewrite")
        self.assertEqual(merged, ["theorem t : True := by\n  rintro - x\n  simp\n"])

    def test_the_statement_is_never_edited_and_variants_are_distinct(self):
        proof = "theorem t (h : p; q) [a, b] : True := by\n  simp [a, b]\n"
        start = golf.body_start(proof, "theorem t (h : p; q) [a, b] : True")
        found = golf.variants(proof, start)
        self.assertTrue(all(variant.text.startswith("theorem t (h : p; q) [a, b] : True := by") for variant in found))
        self.assertEqual(len({variant.text for variant in found}), len(found))
        self.assertNotIn(proof, [variant.text for variant in found])

    def test_a_rewrite_must_cut_tokens_but_a_deletion_need_not(self):
        flat = lambda _text, _start: 10  # noqa: E731 - every variant has the same token count
        kinds = {variant.kind for variant in golf.candidates(PROOF, START, flat)}
        self.assertEqual(kinds, {"list", "line", "segment"})
        cut = lambda text, _start: len(text)  # noqa: E731 - shorter text, fewer tokens
        self.assertIn("rewrite", {variant.kind for variant in golf.candidates(PROOF, START, cut)})

    def test_candidates_come_largest_saving_first(self):
        found = golf.candidates(PROOF, START, lambda text, _start: len(text))
        sizes = [len(variant.text) for variant in found]
        self.assertEqual(sizes, sorted(sizes))


def needs_exact(text: str) -> float | None:
    """A fake Lean: the proof passes while it still has `exact True.intro`; shorter proofs score higher."""
    return 100 - len(text) / 10 if "exact True.intro" in text else None


class GreedyTests(unittest.TestCase):
    def test_it_keeps_deleting_until_nothing_else_passes(self):
        seen = []
        outcome = golf.greedy(PROOF, START, lambda text: seen.append(text) or needs_exact(text), 60)
        self.assertEqual(outcome.proof, STATEMENT + " := by\n  exact True.intro\n")
        self.assertGreaterEqual(len(outcome.accepted), 2)
        self.assertEqual(outcome.tried, len(seen) - 1)  # the starting proof is scored but not counted as tried
        self.assertGreater(outcome.score, outcome.start_score)
        self.assertFalse(outcome.timed_out)

    def test_each_accepted_variant_beats_the_one_before(self):
        outcome = golf.greedy(PROOF, START, needs_exact, 60)
        scores = [outcome.start_score, *(value for _, value, _ in outcome.accepted)]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(len(set(scores)), len(scores))

    def test_a_variant_that_ties_is_not_taken(self):
        outcome = golf.greedy(PROOF, START, lambda text: 50.0 if "exact True.intro" in text else None, 60)
        self.assertEqual((outcome.proof, outcome.accepted), (PROOF, []))

    def test_the_accept_callback_sees_each_step_in_order(self):
        steps = []
        outcome = golf.greedy(PROOF, START, needs_exact, 60, accept=lambda text, value, _variant: steps.append(text))
        self.assertEqual(steps, [text for text, _, _ in outcome.accepted])

    def test_a_proof_that_does_not_pass_is_not_golfed(self):
        outcome = golf.greedy("theorem t : True := by\n  sorry_free\n", 0, needs_exact, 60)
        self.assertEqual((outcome.tried, outcome.accepted), (0, []))
        self.assertIn("does not pass", outcome.reason)
        self.assertIn("skipped", golf.summary_line(outcome))

    def test_the_time_cap_ends_the_pass(self):
        ticks = iter(range(1000))
        checks = []
        outcome = golf.greedy(
            PROOF, START, lambda text: checks.append(text) or needs_exact(text), 3, clock=lambda: float(next(ticks))
        )
        self.assertTrue(outcome.timed_out)
        self.assertLessEqual(outcome.tried, 3)
        self.assertIn("time cap", golf.summary_line(outcome))

    def test_a_silent_lean_ends_the_pass(self):
        outcome = golf.greedy(PROOF, START, needs_exact, 60, stop=lambda: "Lean gave no answer")
        self.assertEqual((outcome.tried, outcome.reason), (0, "Lean gave no answer"))

    def test_the_closing_drain_keeps_its_cap(self):
        self.assertEqual(run_module.DRAIN_S, 180)


def judged(proof: str) -> bool:
    return "exact True.intro" in proof


class RunPassTests(FakeRunCase):
    """The pass over a run: candidates and evaluation rows in the ledger, found again by the submission."""

    def setUp(self):
        super().setUp()
        for item in (
            patch.object(campaign, "problem", return_value={"name": "T", "statement": STATEMENT}),
            patch.object(campaign.lean_health, "tripped", return_value=False),
            patch.object(campaign, "evaluate", side_effect=self.judging_eval),
        ):
            item.start()
            self.addCleanup(item.stop)

    def judging_eval(self, name, proof, mode, known=None, lane="model"):
        result = self.fake_eval(name, proof, mode, known)
        if not judged(proof):
            result["compat"]["v1"] = {"passed": False, "diagnostics": []}
        return result

    def start_from(self, proof: str) -> dict:
        return campaign.record_evaluation("T", "logic", proof, "full", materialize_live=False)

    def test_accepted_variants_are_golf_candidates_with_evaluations_and_the_submission_takes_the_best(self):
        start = self.start_from(PROOF)
        outcome = golf.golf_run("T", "logic", 60)
        history = campaign.events(self.directory)
        rows = campaign._summaries(history)
        golfed = [row for row in rows if row["origin"] == "golf"]
        self.assertEqual(len(golfed), len(outcome.accepted))
        self.assertGreaterEqual(len(golfed), 2)
        self.assertTrue(all(any(e["mode"] == "fast" for e in row["evaluations"]) for row in golfed))
        self.assertEqual(golfed[0]["parents"], [start["candidate_id"]])
        self.assertTrue(golfed[-1]["verified"])  # the newest one was full-checked
        (row,) = [e for e in history if e.get("kind") == "golf"]
        self.assertEqual((row["tried"], row["accepted"]), (outcome.tried, len(outcome.accepted)))
        self.assertEqual(row["verified"], golfed[-1]["id"])
        answer = campaign.submission("logic")
        self.assertEqual(answer["candidate_id"], golfed[-1]["id"])
        self.assertGreater(answer["proxy"], start["metrics"]["proxy"])
        self.assertEqual((self.directory / "submission.lean").read_text(), STATEMENT + " := by\n  exact True.intro\n")

    def test_nothing_is_sent_to_the_model(self):
        self.start_from(PROOF)
        before = campaign.state("logic")["updates"]
        golf.golf_run("T", "logic", 60)
        self.assertEqual(campaign.state("logic")["updates"], before)

    def test_a_tip_that_fails_the_full_check_falls_back_to_the_one_before(self):
        self.start_from(PROOF)

        def reject_the_shortest(name, proof, mode, known=None, lane="model"):
            result = self.judging_eval(name, proof, mode, known, lane)
            if mode == "full" and proof == STATEMENT + " := by\n  exact True.intro\n":
                result["compat"]["v2"]["passed"] = False
            return result

        with patch.object(campaign, "evaluate", side_effect=reject_the_shortest):
            golf.golf_run("T", "logic", 60)
        answer = campaign.submission("logic")
        self.assertNotEqual(
            (self.directory / "submission.lean").read_text(), STATEMENT + " := by\n  exact True.intro\n"
        )
        self.assertEqual(answer["candidate"] is not None, True)

    def test_the_time_cap_bounds_the_pass(self):
        self.start_from(PROOF)
        ticks = iter(range(1000))
        outcome = golf.golf_run("T", "logic", 2, clock=lambda: float(next(ticks)))
        self.assertTrue(outcome.timed_out)
        self.assertLessEqual(outcome.tried, 2)

    def test_it_skips_when_lean_is_unhealthy(self):
        self.start_from(PROOF)
        with patch.object(campaign.lean_health, "tripped", return_value={"source": "breaker"}):
            outcome = golf.golf_run("T", "logic", 60)
        self.assertEqual((outcome.reason, outcome.tried), ("Lean unhealthy", 0))
        self.assertEqual([e for e in campaign.events(self.directory) if e.get("kind") == "golf"], [])

    def test_it_skips_without_a_verified_best(self):
        outcome = golf.golf_run("T", "logic", 60)  # only the reference node exists
        self.assertEqual((outcome.reason, outcome.tried), ("no verified best", 0))
        self.assertEqual([r for r in campaign._summaries(campaign.events(self.directory)) if r["origin"] == "golf"], [])


class ClosingPathTests(unittest.TestCase):
    def finish(self, tripped=False, no_golf=False):
        calls = []
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            directory = Path(tmp)
            with (
                mock.patch.object(run_module, "cost_report_from_ledger", return_value={"spent_usd": 0}),
                mock.patch.object(
                    run_module, "autocheck", side_effect=lambda *a, **k: calls.append("drain") or {"checked": []}
                ),
                mock.patch.object(golf, "golf_run", side_effect=AssertionError("post-run golf ran")) as golf_run,
                mock.patch.object(
                    run_module, "submission", side_effect=lambda _run: calls.append("submission") or {"reason": "none"}
                ),
                mock.patch.object(run_module, "write_state"),
                mock.patch.object(run_module, "write_summary", return_value={}),
                mock.patch.object(run_module, "render_text", return_value="summary\n"),
            ):
                run_module.finish(
                    mock.Mock(theorem="T", run_id="run", no_golf=no_golf),
                    directory,
                    directory / "events.jsonl",
                    0,
                    0,
                    None,
                    tripped=tripped,
                )
        return calls, out.getvalue(), golf_run

    def test_post_run_golf_is_disabled_after_the_verification_drain(self):
        calls, out, golf_run = self.finish()
        self.assertEqual(calls, ["drain", "submission"])
        golf_run.assert_not_called()
        self.assertNotIn("Golf pass", out)

    def test_legacy_no_golf_flag_remains_accepted(self):
        calls, out, golf_run = self.finish(no_golf=True)
        self.assertEqual(calls, ["drain", "submission"])
        golf_run.assert_not_called()
        self.assertNotIn("Golf pass", out)

    def test_an_unhealthy_lean_skips_it(self):
        calls, _, golf_run = self.finish(tripped=True)
        self.assertEqual(calls, ["submission"])
        golf_run.assert_not_called()


class OfflineTests(unittest.TestCase):
    def full(self, ok):
        return {"ok": True, "compat": {"v": {"passed": ok}}, "metrics": {"proxy": 80.0}}

    def run_file(self, full_ok):
        def evaluate(_name, text, mode, **_k):
            if not judged(text):
                return {"ok": True, "compat": {"v": {"passed": False}}}
            return (
                self.full(full_ok(text))
                if mode == "full"
                else {
                    "ok": True,
                    "compat": {"v": {"passed": True}},
                    "metrics": {"estimated_proxy": 100 - len(text) / 10},
                }
            )

        with (
            patch.object(golf.engine, "problem", return_value={"statement": STATEMENT}),
            patch.object(golf.engine, "evaluate", side_effect=evaluate),
        ):
            return golf.golf_file("T", PROOF, 60)

    def test_the_best_proof_that_passes_the_final_cold_check_is_returned(self):
        outcome, best = self.run_file(lambda _text: True)
        self.assertEqual(best, STATEMENT + " := by\n  exact True.intro\n")
        self.assertEqual(outcome.score, 80.0)

    def test_a_tip_failing_the_final_check_gives_way_to_an_earlier_step(self):
        _, best = self.run_file(lambda text: text != STATEMENT + " := by\n  exact True.intro\n")
        self.assertNotEqual(best, PROOF)
        self.assertIn("exact True.intro", best)
        self.assertNotEqual(best, STATEMENT + " := by\n  exact True.intro\n")

    def test_when_nothing_passes_the_final_check_the_start_is_kept(self):
        _, best = self.run_file(lambda _text: False)
        self.assertEqual(best, PROOF)

    def test_the_command_writes_the_result_and_refuses_a_foreign_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "in.lean", Path(tmp) / "out.lean"
            source.write_text(PROOF)
            kept = golf.Outcome(PROOF, 50.0, 60.0, tried=4)
            with (
                patch.object(golf_cli, "problem", return_value={"statement": STATEMENT}),
                patch.object(golf_cli, "validate_proof"),
                patch.object(golf.engine, "problem", return_value={"statement": STATEMENT}),
                patch.object(golf_cli.golf, "golf_file", return_value=(kept, "better\n")),
                contextlib.redirect_stdout(io.StringIO()) as out,
            ):
                self.assertEqual(golf_cli.execute("T", source, target, 5), 0)
            self.assertEqual(target.read_text(), "better\n")
            self.assertIn("Golf pass: tried 4", out.getvalue())
            with (
                patch.object(golf_cli, "problem", return_value={"statement": STATEMENT}),
                patch.object(golf_cli, "validate_proof", side_effect=ValueError("statement modified")),
                contextlib.redirect_stderr(io.StringIO()) as error,
            ):
                self.assertEqual(golf_cli.execute("T", source, Path(tmp) / "none.lean", 5), 2)
            self.assertIn("statement modified", error.getvalue())
            self.assertFalse((Path(tmp) / "none.lean").exists())


if __name__ == "__main__":
    unittest.main()
