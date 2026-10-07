"""Seam A: the campaign JSON CLI, with real Lean on the Strata fixture plus mock-backed logic."""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena.engine import ROOT

NAME = "Core.InitsUpdatesComm"
FIXTURE = ROOT / "runs/baseline/Core_InitsUpdatesComm/arena-candidate-126.txt"
LEAN = unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir() and FIXTURE.exists(),
                           "Strata fixture environment is not provisioned")


def cli(run_id: str, action: str, *args: str, theorem: str = NAME) -> dict:
    proc = subprocess.run([sys.executable, "-m", "tools.arena_campaign", action, "--theorem", theorem,
                           "--run-id", run_id, *args], cwd=ROOT, text=True, capture_output=True)
    assert "Traceback" not in proc.stderr + proc.stdout, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@LEAN
class CampaignCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = f"test-{uuid.uuid4().hex[:10]}"
        cls.good = FIXTURE.read_text()
        cls.work = Path(tempfile.mkdtemp())
        cls.init = cli(cls.run_id, "init")
        assert "packet" in cls.init, cls.init

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(campaign.run_dir(cls.run_id), ignore_errors=True)
        shutil.rmtree(cls.work, ignore_errors=True)

    def proof(self, text: str) -> str:
        path = self.work / f"{uuid.uuid4().hex}.lean"
        path.write_text(text)
        return str(path)

    def test_01_untagged_evaluation_without_parent_is_accepted(self):
        result = cli(self.run_id, "evaluate", "--proof-file", self.proof(self.good))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["candidate"], "#2")
        self.assertEqual(result["tokens"], 126)
        self.assertTrue(result["metrics"]["assumes_full_compat"])
        self.assertEqual(result["metrics"]["deltas"]["vs_reference"]["tokens"], -98)
        self.assertTrue(result["full_check"].startswith("queued"), result)
        self.assertNotIn("proof", result)
        self.assertNotIn("exchange_rates", result)

    def test_02_arbitrary_idea_and_unknown_parent_never_reject(self):
        variant = self.good + "\n  -- annotated"
        result = cli(self.run_id, "evaluate", "--proof-file", self.proof(variant),
                     "--idea-id", "whatever", "--parent", "#99")
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("parent #99 ignored" in note for note in result["notes"]))
        self.assertTrue(any("idea_id whatever" in note for note in result["notes"]))

    def test_04_probe_with_sorry_reports_goals_and_cannot_be_promoted(self):
        statement = campaign.problem(NAME)["statement"]
        before = len(campaign.frontier(self.run_id)["top"]), campaign.frontier(self.run_id)["candidates"]
        probe = cli(self.run_id, "probe", "--proof-file",
                    self.proof(statement + " := by\n  intros Hup Hinit\n  sorry"))
        self.assertEqual(probe["probe"], "p1")
        self.assertEqual(len(probe["goals"]), 1)
        self.assertIn("Hup", probe["goals"][0]["goals"])
        self.assertEqual(probe["goals"][0]["proof_line"], 11)
        self.assertEqual(probe["goals"][0]["file_line"], 960)
        self.assertIs(probe["scored"], False)
        promoted = cli(self.run_id, "evaluate", "--from-probe", "p1")
        self.assertFalse(promoted["ok"])
        self.assertIn("FORBIDDEN: sorry", promoted["error"])
        after = campaign.frontier(self.run_id)
        self.assertEqual((len(after["top"]), after["candidates"]), before)

    def test_05_complete_probe_becomes_a_candidate_and_sorry_probes_restore(self):
        draft = self.good + "\n  -- promoted"
        result = cli(self.run_id, "probe", "--proof-file", self.proof(draft), "--idea-id", "i1")
        self.assertTrue(result["candidate"].startswith("#"), result)
        self.assertEqual(result["idea_id"], "i1")
        self.assertIsNotNone(result["heartbeat"])
        self.assertTrue(any("recorded as candidate" in note for note in result["notes"]))
        self.assertTrue(result["full_check"].startswith("queued"))
        restored = cli(self.run_id, "candidate", "--candidate", "p1")
        self.assertIn("sorry", restored["proof"])
        self.assertEqual(Path(restored["candidate_path"]).read_text().count("sorry"), 1)

    def test_06_failed_evaluation_reports_aligned_lines(self):
        broken = self.good.replace("exact updatedStateUpdate (InitStatesSomeMonotone Hold Hinits)", "exact rfl")
        result = cli(self.run_id, "evaluate", "--proof-file", self.proof(broken))
        self.assertTrue(result["ok"])
        info = result["compat"]["v4.29.1"]
        self.assertFalse(info["passed"])
        shadow = Path(result["candidate_path"]).read_text().splitlines()
        for diagnostic in info["diagnostics"]:
            self.assertEqual(shadow[diagnostic["file_line"] - 1], diagnostic["source_line_text"])
        self.assertTrue((campaign.run_dir(self.run_id) / info["full_diagnostics_ref"]).exists())
        self.assertEqual(result["metrics"], {"compiled": False})

    def test_09_background_check_state_and_submission(self):
        fresh = cli(self.run_id, "evaluate", "--proof-file", self.proof(self.good + "\n  -- checked later"))
        self.assertIn(fresh["candidate"], cli(self.run_id, "state")["checking"])
        drained = cli(self.run_id, "autocheck")
        self.assertIn(fresh["candidate"], drained["checked"])
        self.assertEqual(drained["remaining"], [])
        published = json.loads((campaign.run_dir(self.run_id) / "state.json").read_text())
        self.assertTrue(any(item["text"].startswith(f"{fresh['candidate']} passes all 3 versions")
                            for item in published["updates"]), published)
        self.assertEqual(published["checking"], [])
        self.assertIsNotNone(published["best"]["proxy"])
        answer = cli(self.run_id, "submission")
        self.assertEqual(answer["candidate"], published["best"]["candidate"])
        self.assertEqual((campaign.run_dir(self.run_id) / "submission.lean").read_text().split(":=")[0],
                         self.good.split(":=")[0])

    def test_10_blank_proof_next_to_a_candidate_is_ignored(self):
        empty = self.proof(" ")
        profiled = cli(self.run_id, "profile", "--candidate", "#2", "--proof-file", empty)
        self.assertTrue(profiled.get("ok", True), profiled)
        self.assertEqual(profiled["target"], "#2")
        evaluated = cli(self.run_id, "evaluate", "--candidate", "#2", "--proof-file", empty, "--mode", "full")
        self.assertTrue(evaluated["ok"], evaluated)
        self.assertEqual(evaluated["candidate"], "#2")
        self.assertEqual(evaluated["metrics"]["proxy"], 76.72)
        self.assertEqual(evaluated["full_check"], "#2 passes all 3 versions: proxy 76.72")

    def test_probe_accepts_body_only_and_assignment_bodies_with_exact_statement(self):
        statement = campaign.problem(NAME)["statement"]
        self.assertEqual(campaign.normalize_draft(NAME, "by\n  trivial"), statement + " := by\n  trivial")
        self.assertEqual(campaign.normalize_draft(NAME, ":= by\n  trivial"), statement + " := by\n  trivial")
        complete = statement + " := by\n  trivial"
        self.assertEqual(campaign.normalize_draft(NAME, complete), complete)
        self.assertEqual(campaign.normalize_draft(NAME, "\n" + complete), complete)

    def test_probe_batch_keeps_the_initial_parent_for_every_draft(self):
        candidate_id = "a" * 64
        seen = []

        def fake_probe(name, run_id, proof, idea_id, parent):
            seen.append((proof, parent))
            return {"ok": True, "candidate": f"#{len(seen) + 1}"}

        with patch("arena.campaign.events", return_value=[{"kind": "candidate", "candidate_id": candidate_id},
                                                            {"kind": "current", "candidate_id": candidate_id}]), \
             patch("arena.campaign.run_dir", return_value=Path("unused")), \
             patch("arena.campaign._compile_probes", return_value={}), \
             patch("arena.campaign.probe", side_effect=fake_probe):
            result = campaign.probe_batch(NAME, "unused", ["by exact", "by simp", "by assumption", "by aesop"])

        self.assertEqual([item[1] for item in seen], [candidate_id] * 4)
        self.assertEqual([item["index"] for item in result["drafts"]], [1, 2, 3, 4])
        with self.assertRaisesRegex(ValueError, "one and four"):
            campaign.probe_batch(NAME, "unused", ["by exact"] * 5)

    def test_probe_batch_compiles_distinct_drafts_once_and_records_in_draft_order(self):
        compiled = []

        def fake_compile(name, row, proof):
            compiled.append(proof)
            return {"ok": True, "mode": "probe", "tokens": 1, "compat": {"v": {"passed": False}}}

        with patch("arena.campaign._compile_probe", side_effect=fake_compile), \
             patch("arena.campaign._probe_workers", return_value=4), \
             patch("arena.campaign.lean_lock") as lock:
            results = campaign._compile_probes(NAME, Path("unused"), ["by exact", "by simp", " by exact", "by exact"])
        self.assertEqual(len(compiled), 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(lock.call_count, 1)

    def test_evaluate_rejects_conflicting_references_and_directs_holes_to_probe(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            campaign.evaluate_request(NAME, "unused", "complete", candidate_ref="#2")
        with patch("arena.campaign.record_evaluation", side_effect=ValueError("FORBIDDEN: sorry")):
            with self.assertRaisesRegex(ValueError, "use arena_probe"):
                campaign.evaluate_request(NAME, "unused", campaign.problem(NAME)["statement"] + " := by sorry")

    def test_08_source_pagination_and_one_line_errors(self):
        row = campaign.problem(NAME)
        path = row["file_path"]
        big = cli(self.run_id, "source", "--handle", path, "--first", "1", "--last", "5000")
        self.assertEqual(len(big["text"].splitlines()), 400)
        self.assertEqual(big["next_first"], 401)
        beyond = cli(self.run_id, "source", "--handle", path, "--first", str(big["file_lines"] + 5), "--last", "9999999")
        self.assertFalse(beyond["ok"])
        self.assertIn(f"has {big['file_lines']} lines", beyond["error"])
        clamped = cli(self.run_id, "source", "--handle", path, "--first", str(big["file_lines"] - 2), "--last", "9999999")
        self.assertEqual(clamped["last"], big["file_lines"])
        outside = cli(self.run_id, "source", "--handle", "../secrets.lean", "--first", "1", "--last", "2")
        self.assertFalse(outside["ok"])
        self.assertIn("inside the pinned project", outside["error"])
        missing = cli(self.run_id, "source", "--handle", "No/Such.lean", "--first", "1", "--last", "2")
        self.assertIn("does not exist", missing["error"])
        self.assertFalse(cli(self.run_id, "candidate", "--candidate", "#999")["ok"])


@LEAN
class ProfileCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = f"test-{uuid.uuid4().hex[:10]}"
        cls.work = Path(tempfile.mkdtemp())
        assert "packet" in cli(cls.run_id, "init")
        cls.reference = cli(cls.run_id, "profile", "--candidate", "#1")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(campaign.run_dir(cls.run_id), ignore_errors=True)
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_reference_profile_attributes_cost_close_to_the_measured_total(self):
        profile = self.reference
        self.assertTrue(profile["ok"], profile)
        self.assertEqual(profile["granularity"], "tactic")
        self.assertTrue(4000 <= profile["measured_total"] <= 4500, profile["measured_total"])
        self.assertAlmostEqual(profile["profiled_total"], profile["measured_total"], delta=0.1 * profile["measured_total"])
        self.assertEqual(profile["unattributed"], profile["measured_total"] - profile["profiled_total"])
        self.assertGreater(len(profile["entries"]), 10)
        self.assertEqual(profile["entries"][0]["lines"], "10")
        self.assertTrue(profile["line_profile"])
        self.assertEqual(profile["line_tokens_total"], profile["tokens"])
        self.assertEqual(profile["line_profile"][0]["proof_line"], 1)
        self.assertEqual(profile["line_profile"][0]["file_line"], campaign.problem(NAME)["start_line"])
        self.assertGreater(profile["statement_floor_hb"], 0)

    def test_simp_all_lines_carry_nonzero_cost_and_top_costs_are_cumulative(self):
        costly = [e for e in self.reference["entries"] if "simp_all" in e["text"] and e["depth"] > 0]
        self.assertTrue(costly)
        self.assertTrue(all(e["hb"] > 0 for e in costly))
        top = self.reference["top_self_cost"]
        self.assertEqual([t["cumulative_share_pct"] for t in top],
                         sorted(t["cumulative_share_pct"] for t in top))
        self.assertGreater(top[-1]["cumulative_share_pct"], 50)

    def test_profile_of_a_candidate_and_cached_repeat(self):
        good = FIXTURE.read_text()
        path = self.work / "good.lean"
        path.write_text(good)
        assert cli(self.run_id, "evaluate", "--proof-file", str(path))["ok"]
        first = cli(self.run_id, "profile", "--candidate", "#2")
        self.assertTrue(first["ok"], first)
        self.assertLess(first["measured_total"], 1000)
        again = cli(self.run_id, "profile")
        self.assertTrue(again["cached"])
        self.assertEqual(again["profiled_total"], first["profiled_total"])

    def test_probe_with_sorry_cannot_be_profiled(self):
        statement = campaign.problem(NAME)["statement"]
        path = self.work / "draft.lean"
        path.write_text(statement + " := by\n  intros Hup Hinit\n  sorry")
        probe = cli(self.run_id, "probe", "--proof-file", str(path))
        result = cli(self.run_id, "profile", "--candidate", probe["probe"])
        self.assertFalse(result["ok"])
        self.assertIn("without sorry", result["error"])


@LEAN
class DeclarationTests(unittest.TestCase):
    def test_namespaced_constructor_and_library_names_resolve_where_text_search_cannot(self):
        found = campaign.declarations(NAME, ["Core.UpdateStatesLength"])["items"][0]
        self.assertEqual(found["kind"], "declaration")
        self.assertIn("List.length ks = List.length vs", found["source_text"])
        library = campaign.declarations(NAME, ["List.unzip_zip"])["items"][0]
        self.assertEqual((library["kind"], library["reason"], library["module"]),
                         ("unavailable", "external", "Init.Data.List.Zip"))
        constructor = campaign.declarations(NAME, ["Core.UpdateStates.update_some"])["items"][0]
        self.assertEqual(constructor["kind"], "declaration")
        self.assertIn("update_some", constructor["source_text"])

    def test_a_name_that_does_not_exist_gets_a_hint_not_a_traceback(self):
        missing = campaign.declarations(NAME, ["Core.NoSuchLemmaAnywhere"])["items"][0]
        self.assertEqual(missing["error"], "not_found")
        self.assertIn("hint", missing)
        self.assertFalse(cli("none", "declarations", "--items", json.dumps(["bad name!"]))["ok"])


@LEAN
class TruncationEquivalenceTests(unittest.TestCase):
    def test_dropping_later_declarations_does_not_change_the_result(self):
        from arena.engine import HEARTBEAT_WRAPPER, candidate_file, evaluate, problem, run_lean, versions

        row = problem(NAME)
        version, commit = versions(row)[0]
        proof = FIXTURE.read_text()
        short = candidate_file(row, proof, version, commit, truncate=True)
        full = candidate_file(row, proof, version, commit, truncate=False)
        self.assertGreater(len(full["text"]), len(short["text"]))
        self.assertTrue(full["text"].startswith(short["text"].rstrip("\n")))
        code, output = run_lean(row, full["path"], full["text"][:full["offset"]] + HEARTBEAT_WRAPPER + full["text"][full["offset"]:])
        untruncated = int(__import__("re").search(r"ARENA_HEARTBEATS (\d+)", output)[1])
        result = evaluate(NAME, proof, "fast")
        self.assertEqual((code, result["compat"][version]["passed"]), (0, True))
        self.assertAlmostEqual(result["heartbeat"], untruncated, delta=max(5, untruncated * 0.02))


class ProtocolLogicTests(unittest.TestCase):
    """Behaviour that needs no Lean: lineage defaults, advisory, idea lifecycle."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patches = [patch.object(campaign, "ROOT", Path(self.temporary.name)),
                   patch.object(campaign, "problem", return_value={"name": "T"}),
                   patch.object(campaign, "validate_proof"),
                   patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b")]),
                   patch.object(campaign, "materialize", return_value={"candidate_path": "s.lean"}),
                   patch.object(campaign, "evaluate", side_effect=self.fake_eval)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.directory = campaign.run_dir("logic")
        campaign._append(self.directory, {"kind": "init", "theorem": "T", "versions": [["v1", "a"], ["v2", "b"]]})
        reference = campaign.record_evaluation("T", "logic", "theorem t := by\n  ref", "fast",
                                               origin="reference", materialize_live=False)
        campaign._append(self.directory, {"kind": "current", "candidate_id": reference["candidate_id"]})

    calls: list = []

    @classmethod
    def fake_eval(cls, _name, proof, mode, known=None):
        cls.calls.append((proof, mode, sorted(known or {})))
        tokens = len(proof)
        compat = {"v1": (known or {}).get("v1") or {"passed": "bad" not in proof}}
        if mode == "full":
            compat["v2"] = {"passed": "bad" not in proof and "old" not in proof,
                            "error_headlines": [] if "old" not in proof else ["line 3 (proof line 2): unknown tactic"]}
        score = round(100 - tokens, 2)
        metrics = {"tokens": tokens, "heartbeats": 10, "compiled": "bad" not in proof}
        if metrics["compiled"]:
            metrics["axes"] = {"tokens": {"value": tokens}}
            metrics["proxy" if mode == "full" else "estimated_proxy"] = score
            metrics["deltas"] = {}
        return {"ok": True, "mode": mode, "tokens": tokens, "heartbeat": 10, "compat": compat,
                "local_proxy": score if mode == "full" else None, "metrics": metrics}

    def evaluate(self, text, **kwargs):
        return campaign.evaluate_request("T", "logic", text, kwargs.pop("mode", "fast"), **kwargs)

    def test_parent_defaults_to_the_materialized_candidate(self):
        first = self.evaluate("theorem t := by\n  a")
        second = self.evaluate("theorem t := by\n  ab")
        graph = campaign.graph_state("logic")
        self.assertEqual(graph["nodes"][1]["parents"], [graph["nodes"][0]["id"]])
        self.assertEqual(graph["nodes"][2]["parents"], [graph["nodes"][1]["id"]])
        self.assertEqual((first["candidate"], second["candidate"]), ("#2", "#3"))

    def test_candidate_never_becomes_its_own_parent(self):
        self.evaluate("theorem t := by\n  a")
        again = self.evaluate("theorem t := by\n  a", parents=["#2"], mode="full")
        self.assertTrue(again["ok"])
        self.assertEqual(campaign.graph_state("logic")["nodes"][1]["parents"], [campaign.graph_state("logic")["nodes"][0]["id"]])

    def test_deltas_against_parent_and_best(self):
        self.evaluate("theorem t := by\n  aaaa")
        better = self.evaluate("theorem t := by\n  a", parents=["#2"])
        self.assertEqual(better["metrics"]["deltas"]["vs_parent"]["candidate"], "#2")
        self.assertEqual(better["metrics"]["deltas"]["vs_parent"]["tokens"], -3)
        self.assertEqual(better["metrics"]["deltas"]["vs_best"]["candidate"], "#2")
        self.assertEqual(campaign.state("logic")["leading_unverified"]["candidate"], "#3")

    def test_advisory_states_facts_when_recent_attempts_share_a_lineage_without_gain(self):
        self.evaluate("theorem t := by\n  a")
        for suffix in ("bb", "cc", "dd", "ee"):
            result = self.evaluate("theorem t := by\n  a" + suffix, parents=["#2"])
        self.assertIn("all descend from #2", result["advisory"])
        self.assertNotIn("should", result["advisory"].lower())
        improved = self.evaluate("theorem t := by", parents=["#2"])
        self.assertIsNone(improved.get("advisory"))

    def test_idea_lifecycle_and_validation(self):
        with self.assertRaisesRegex(ValueError, "needs a title"):
            campaign.record_idea("logic")
        created = campaign.record_idea("logic", "Factor repeated cases", "share lemma", "3-9",
                                       {"tokens": "-30", "bogus": "x"})
        self.assertEqual(created["expected_effect"], {"tokens": "-30"})
        with self.assertRaisesRegex(ValueError, "reason"):
            campaign.record_idea("logic", idea_id="i1", status="abandoned")
        with self.assertRaisesRegex(ValueError, "Unknown idea"):
            campaign.record_idea("logic", idea_id="i9", status="active")
        with self.assertRaisesRegex(ValueError, "status must be"):
            campaign.record_idea("logic", idea_id="i1", status="done")
        campaign.record_idea("logic", idea_id="i1", status="succeeded", reason="halved tokens")
        self.evaluate("theorem t := by\n  a", idea_id="i1")
        listed = campaign.frontier("logic")["ideas"][0]
        self.assertEqual((listed["status"], listed["attempts"]), ("succeeded", 1))
        self.assertEqual(listed["best"]["candidate"], "#2")
        self.assertIn("recent_failures", campaign.frontier("logic"))

    def test_a_new_idea_may_carry_the_models_own_id(self):
        # Luna v5 created ideas as {idea_id: "state_algebra", title: ...}; that is a creation.
        made = campaign.record_idea("logic", "State algebra", "h", idea_id="state_algebra")
        self.assertEqual(made["id"], "state_algebra")
        again = campaign.record_idea("logic", idea_id="state_algebra", status="parked", reason="later")
        self.assertEqual(again["status"], "parked")
        self.assertEqual(campaign.record_idea("logic", "Next")["id"], "i2")
        with self.assertRaisesRegex(ValueError, "give a title to create it"):
            campaign.record_idea("logic", idea_id="nope", status="active")
        self.assertEqual(campaign.record_idea("logic", "Odd id", idea_id="has space/slash")["id"], "has_space_slash")

    def test_region_accepts_common_spellings_and_never_rejects(self):
        spans = {"12-30": [12, 30], "12–30": [12, 30], "lines 12-30": [12, 30], "L12-L30": [12, 30],
                 "12..30": [12, 30], "line 7": [7, 7], "30-12": [12, 30]}
        for text, span in spans.items():
            self.assertEqual(campaign.record_idea("logic", f"r {text}", region=text)["region"], span, text)
        free = campaign.record_idea("logic", "free", region="the induction step")
        self.assertEqual(free["region"], "the induction step")

    def test_forbidden_proofs_are_rejected_before_any_node_is_recorded(self):
        with patch.object(campaign, "validate_proof", side_effect=ValueError("FORBIDDEN: sorry")):
            with self.assertRaisesRegex(ValueError, "FORBIDDEN"):
                self.evaluate("theorem t := by\n  sorry")
        self.assertEqual(campaign.frontier("logic")["candidates"], 1)

    def test_autocheck_reuses_the_primary_result_and_checks_best_first(self):
        self.evaluate("theorem t := by\n  aaaa")
        self.evaluate("theorem t := by\n  a")
        self.evaluate("theorem t := by\n  bad")
        self.calls.clear()
        self.assertEqual(campaign.state("logic")["checking"], ["#3", "#2"])
        outcome = campaign.autocheck("T", "logic")
        self.assertEqual(outcome["checked"], ["#3", "#2"])
        self.assertEqual([(mode, known) for _, mode, known in self.calls], [("full", ["v1"]), ("full", ["v1"])])
        state = campaign.state("logic")
        self.assertEqual(state["best"]["candidate"], "#3")
        self.assertIsNone(state["leading_unverified"])
        self.assertEqual([u["text"].split(":")[0] for u in state["updates"]],
                         ["#3 passes all 2 versions", "#2 passes all 2 versions"])
        self.assertEqual(campaign.autocheck("T", "logic")["checked"], [])

    def test_failed_transfer_is_reported_with_its_headline_and_not_submitted(self):
        self.evaluate("theorem t := by\n  old")
        campaign.autocheck("T", "logic")
        update = campaign.state("logic")["updates"][-1]["text"]
        self.assertEqual(update, "#2 fails v2 (1/2 pass): line 3 (proof line 2): unknown tactic")
        self.assertIsNone(campaign.submission("logic")["candidate"])
        self.evaluate("theorem t := by\n  ok")
        campaign.autocheck("T", "logic")
        self.assertEqual(campaign.submission("logic")["candidate"], "#3")
        self.assertEqual((self.directory / "submission.lean").read_text(), "theorem t := by\n  ok")

    def test_only_one_checker_runs_per_run(self):
        import fcntl
        self.evaluate("theorem t := by\n  a")
        with (self.directory / "autocheck.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.assertTrue(campaign.autocheck("T", "logic")["running_elsewhere"])
        self.assertEqual(campaign.autocheck("T", "logic")["checked"], ["#2"])

    def test_a_crashing_check_is_recorded_and_the_queue_moves_on(self):
        self.evaluate("theorem t := by\n  a")
        with patch.object(campaign, "record_evaluation", side_effect=RuntimeError("disk full")):
            outcome = campaign.autocheck("T", "logic")
        self.assertEqual(outcome["remaining"], [])
        self.assertIn("could not run: disk full", campaign.state("logic")["updates"][-1]["text"])

    def test_evaluation_results_do_not_echo_proof_or_frontier(self):
        result = self.evaluate("theorem t := by\n  a")
        self.assertNotIn("next_experiment", result)
        self.assertNotIn("proof", json.dumps(result).replace("proof_line", ""))


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


if __name__ == "__main__":
    unittest.main()
