"""Shared fake-Lean seam for graph and campaign protocol tests."""

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import campaign


class FakeRunCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patches = [
            patch.object(campaign, "ROOT", Path(self.temporary.name)),
            patch.object(campaign, "problem", return_value={"name": "T"}),
            patch.object(campaign, "validate_proof"),
            patch.object(campaign, "versions", return_value=[("v1", "a"), ("v2", "b")]),
            patch.object(campaign, "materialize", return_value={"candidate_path": "s.lean"}),
            patch.object(campaign, "evaluate", side_effect=self.fake_eval),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.directory = campaign.run_dir("logic")
        campaign._append(self.directory, {"kind": "init", "theorem": "T", "versions": [["v1", "a"], ["v2", "b"]]})
        reference = campaign.record_evaluation(
            "T", "logic", "theorem t := by\n  ref", "fast", origin="reference", materialize_live=False
        )
        campaign._append(self.directory, {"kind": "current", "candidate_id": reference["candidate_id"]})

    calls: ClassVar[list] = []

    @classmethod
    def fake_eval(cls, _name, proof, mode, known=None):
        cls.calls.append((proof, mode, sorted(known or {})))
        tokens = len(proof)
        compat = {"v1": (known or {}).get("v1") or {"passed": "bad" not in proof}}
        if mode == "full":
            compat["v2"] = {
                "passed": "bad" not in proof and "old" not in proof,
                "error_headlines": [] if "old" not in proof else ["line 3 (proof line 2): unknown tactic"],
            }
        score = round(100 - tokens, 2)
        metrics = {"tokens": tokens, "heartbeats": 10, "compiled": "bad" not in proof}
        if metrics["compiled"]:
            metrics["axes"] = {"tokens": {"value": tokens}}
            metrics["proxy" if mode == "full" else "estimated_proxy"] = score
            metrics["deltas"] = {}
        return {
            "ok": True,
            "mode": mode,
            "tokens": tokens,
            "heartbeat": 10,
            "compat": compat,
            "local_proxy": score if mode == "full" else None,
            "metrics": metrics,
        }

    def evaluate(self, text, **kwargs):
        return campaign.evaluate_request("T", "logic", text, kwargs.pop("mode", "fast"), **kwargs)
