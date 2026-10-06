"""Seam A: the campaign JSON CLI, with real Lean on the Strata fixture plus mock-backed logic."""

import json
import shutil
import subprocess
import sys
import tempfile
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
        self.assertEqual(result["best_so_far"]["fast_only"]["candidate"], "#2")
        self.assertNotIn("proof", result)
        self.assertNotIn("exchange_rates", result)

    def test_02_arbitrary_idea_and_unknown_parent_never_reject(self):
        variant = self.good + "\n  -- annotated"
        result = cli(self.run_id, "evaluate", "--proof-file", self.proof(variant),
                     "--idea-id", "whatever", "--parent", "#99")
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("parent #99 ignored" in note for note in result["notes"]))
        self.assertTrue(any("idea_id whatever" in note for note in result["notes"]))

    def test_03_full_recheck_of_existing_candidate_by_number(self):
        result = cli(self.run_id, "evaluate", "--candidate", "#2", "--mode", "full")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["metrics"]["proxy"], 76.72)
        self.assertEqual(result["candidate"], "#2")
        self.assertEqual(result["best_so_far"]["verified"]["candidate"], "#2")

    def test_04_probe_with_sorry_reports_goals_and_cannot_be_promoted(self):
        statement = campaign.problem(NAME)["statement"]
        before = len(campaign.frontier(self.run_id)["top"]), campaign.frontier(self.run_id)["candidates"]
        probe = cli(self.run_id, "probe", "--proof-file",
                    self.proof(statement + " := by\n  intros Hup Hinit\n  sorry"))
        self.assertEqual(probe["probe"], "p1")
        self.assertEqual(len(probe["goals"]), 1)
        self.assertIn("Hup", probe["goals"][0]["goals"])
        self.assertIs(probe["scored"], False)
        promoted = cli(self.run_id, "evaluate", "--from-probe", "p1")
        self.assertFalse(promoted["ok"])
        self.assertIn("FORBIDDEN: sorry", promoted["error"])
        after = campaign.frontier(self.run_id)
        self.assertEqual((len(after["top"]), after["candidates"]), before)

    def test_05_probe_restore_and_promote_without_resending_the_proof(self):
        draft = self.good + "\n  -- promoted"
        probe = cli(self.run_id, "probe", "--proof-file", self.proof(draft), "--idea-id", "i1")
        self.assertTrue(probe["compat"]["v4.29.1"]["passed"], probe)
        self.assertTrue(probe["probe"].startswith("p"))
        restored = cli(self.run_id, "candidate", "--candidate", probe["probe"])
        self.assertEqual(restored["proof"], draft)
        self.assertEqual(Path(restored["candidate_path"]).read_text().count("-- promoted"), 1)
        promoted = cli(self.run_id, "evaluate", "--from-probe", probe["probe"])
        self.assertTrue(promoted["ok"], promoted)
        self.assertEqual(promoted["idea_id"], "i1")
        self.assertTrue(promoted["candidate"].startswith("#"))

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

    def test_07_ideas_are_model_owned_and_summarised_in_the_frontier(self):
        made = cli(self.run_id, "idea", "--title", "Rewrite the induction", "--hypothesis",
                   "tail IH gives witness", "--region", "10-20",
                   "--expected-effect", json.dumps({"tokens": "-40", "heartbeats": "-2000"}))
        self.assertEqual(made["id"], "i1")
        self.assertEqual(made["status"], "active")
        cli(self.run_id, "evaluate", "--proof-file", self.proof(self.good + "\n  -- tagged"), "--idea-id", "i1")
        bad = cli(self.run_id, "idea", "--idea-id", "i1", "--status", "abandoned")
        self.assertFalse(bad["ok"])
        self.assertIn("reason", bad["error"])
        cli(self.run_id, "idea", "--idea-id", "i1", "--status", "parked", "--reason", "needs more work")
        state = cli(self.run_id, "frontier")
        idea = next(item for item in state["ideas"] if item["id"] == "i1")
        self.assertEqual((idea["status"], idea["reason"]), ("parked", "needs more work"))
        self.assertGreaterEqual(idea["attempts"], 1)
        self.assertIn("recent_failures", state)

    def test_08_source_pagination_and_one_line_errors(self):
        row = campaign.problem(NAME)
        path = row["file_path"]
        big = cli(self.run_id, "source", "--path", path, "--first", "1", "--last", "5000")
        self.assertEqual(len(big["text"].splitlines()), 400)
        self.assertEqual(big["next_first"], 401)
        beyond = cli(self.run_id, "source", "--path", path, "--first", str(big["file_lines"] + 5), "--last", "9999999")
        self.assertFalse(beyond["ok"])
        self.assertIn(f"has {big['file_lines']} lines", beyond["error"])
        clamped = cli(self.run_id, "source", "--path", path, "--first", str(big["file_lines"] - 2), "--last", "9999999")
        self.assertEqual(clamped["last"], big["file_lines"])
        outside = cli(self.run_id, "source", "--path", "../secrets.lean", "--first", "1", "--last", "2")
        self.assertFalse(outside["ok"])
        self.assertIn("inside the pinned project", outside["error"])
        missing = cli(self.run_id, "source", "--path", "No/Such.lean", "--first", "1", "--last", "2")
        self.assertIn("does not exist", missing["error"])
        self.assertFalse(cli(self.run_id, "candidate", "--candidate", "#999")["ok"])


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

    @staticmethod
    def fake_eval(_name, proof, mode):
        tokens = len(proof)
        compat = {"v1": {"passed": "bad" not in proof}}
        if mode == "full":
            compat["v2"] = {"passed": "bad" not in proof}
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
        self.assertEqual(better["best_so_far"]["fast_only"]["candidate"], "#3")

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

    def test_forbidden_proofs_are_rejected_before_any_node_is_recorded(self):
        with patch.object(campaign, "validate_proof", side_effect=ValueError("FORBIDDEN: sorry")):
            with self.assertRaisesRegex(ValueError, "FORBIDDEN"):
                self.evaluate("theorem t := by\n  sorry")
        self.assertEqual(campaign.frontier("logic")["candidates"], 1)

    def test_evaluation_results_do_not_echo_proof_or_frontier(self):
        result = self.evaluate("theorem t := by\n  a")
        self.assertNotIn("next_experiment", result)
        self.assertNotIn("proof", json.dumps(result).replace("proof_line", ""))


if __name__ == "__main__":
    unittest.main()
