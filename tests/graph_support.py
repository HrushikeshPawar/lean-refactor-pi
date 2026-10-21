"""Shared fake-Lean seam for graph and campaign protocol tests."""

import re
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import campaign
from arena.engine import instrument_sorries


class FakeRunCase(unittest.TestCase):
    cascade_errors: ClassVar[bool] = False
    no_goal_marker: ClassVar[str | None] = None
    # Per-version Lean path info as engine.run_lean records it; None leaves it out.
    lean_info: ClassVar[dict | None] = None

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
    def fake_eval(cls, _name, proof, mode, known=None, **_kwargs):
        cls.calls.append((proof, mode, sorted(known or {})))
        tokens = len(proof)
        bad_lines = [index for index, line in enumerate(proof.splitlines(), 1) if "bad" in line.split()]
        if cls.cascade_errors:
            bad_lines = bad_lines[:1]
        diagnostics = [
            {"severity": "error", "proof_line": line, "file_line": line, "message": "fixture error"}
            for line in bad_lines
        ]
        instrumented = instrument_sorries(proof)
        sorry_lines = [int(match.group(1)) for match in re.finditer(r"ARENA_SORRY (\d+)", instrumented)]
        compat: dict[str, dict] = {
            "v1": (known or {}).get("v1") or {"passed": not bad_lines, "exit_code": 1 if bad_lines else 0, "diagnostics": diagnostics}
        }
        if mode == "full":
            compat["v2"] = {
                "passed": not bad_lines and "old" not in proof,
                "exit_code": 1 if bad_lines or "old" in proof else 0,
                "diagnostics": diagnostics,
                "error_headlines": [] if "old" not in proof else ["line 3 (proof line 2): unknown tactic"],
            }
        if cls.lean_info is not None:
            for info in compat.values():
                info.setdefault("lean", dict(cls.lean_info))
        score = round(100 - tokens, 2)
        metrics = {"tokens": tokens, "heartbeats": 10, "compiled": not bad_lines}
        if metrics["compiled"]:
            metrics["axes"] = {"tokens": {"value": tokens}}
            metrics["proxy" if mode == "full" else "estimated_proxy"] = score
            metrics["deltas"] = {}
        result = {
            "ok": True,
            "mode": mode,
            "tokens": tokens,
            "heartbeat": 10,
            "compat": compat,
            "local_proxy": score if mode == "full" else None,
            "metrics": metrics,
        }
        if mode == "probe":
            result["contains_sorry"] = bool(re.search(r"\bsorry\b", proof))
            lines = proof.splitlines()
            result["goals"] = [
                {"proof_line": line, "goals": [f"goal at line {line}"]}
                for line in sorry_lines
                if cls.no_goal_marker is None or cls.no_goal_marker not in lines[line - 1]
            ]
        return result

    def evaluate(self, text, **kwargs):
        return campaign.evaluate_request("T", "logic", text, kwargs.pop("mode", "fast"), **kwargs)
