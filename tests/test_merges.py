"""A harness-combined proof is reported, never submitted: submissions stay model-written."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign
from arena.merges import merge_report, merge_text

BASE = "theorem t := by\n  intro x\n  have h := x\n  exact h\n"
LEFT = BASE.replace("have h := x", "have h : _ := x")
RIGHT = BASE.replace("exact h", "simpa using h")
MERGED = LEFT.replace("exact h", "simpa using h")
PROXY = {BASE: 40.0, LEFT: 60.0, RIGHT: 55.0, MERGED: 80.0}


def fake_eval(_name, proof, mode, known=None):
    compat = {"v1": {"passed": True}}
    score = PROXY[proof]
    return {"ok": True, "mode": mode, "tokens": len(proof), "heartbeat": 3, "compat": compat, "local_proxy": None,
            "metrics": {"tokens": len(proof), "heartbeats": 3, "compiled": True, "proxy": score if mode == "full" else None,
                        "estimated_proxy": score}}


class MergeReportTests(unittest.TestCase):
    def run_merge(self):
        stack = [patch.object(campaign, "problem", return_value={"name": "T"}), patch.object(campaign, "validate_proof"),
                 patch.object(campaign, "versions", return_value=[("v1", "a")]),
                 patch.object(campaign, "evaluate", side_effect=fake_eval),
                 patch.object(campaign, "materialize")]
        for item in stack:
            item.start()
            self.addCleanup(item.stop)
        directory = campaign.run_dir("m")
        campaign._append(directory, {"kind": "init", "theorem": "T"})
        root = campaign.record_evaluation("T", "m", BASE, "full", materialize_live=False)["candidate_id"]
        for proof in (LEFT, RIGHT):
            campaign.record_evaluation("T", "m", proof, "full", [root], materialize_live=False)
        campaign.merge_once("m")
        campaign.merge_once("m")
        return directory

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(campaign, "ROOT", Path(temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_combination_is_reported_and_not_submitted(self):
        directory = self.run_merge()
        rows = merge_report(campaign.events(directory))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["proxy"], 80.0)
        self.assertTrue(rows[0]["beats_parents"])
        self.assertFalse(rows[0]["submitted"])
        self.assertIn("never submitted", merge_text(rows))
        answer = campaign.submission("m")
        self.assertEqual(answer["candidate"], "#2", "the best model-written candidate, not the 80.0 combination")
        self.assertEqual((directory / "submission.lean").read_text(), LEFT)

if __name__ == "__main__":
    unittest.main()
