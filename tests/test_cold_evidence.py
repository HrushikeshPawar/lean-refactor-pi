"""Small offline checks for infrastructure evidence at the Lean/model boundary."""

import contextlib
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, engine
from tests.test_cold_outcomes import admit_fixture_proof


class ColdEvidenceTests(unittest.TestCase):
    def test_measurement_context_and_target_errors_remain_distinct(self):
        built = {
            "path": Path("unused"),
            "text": "prefix\ntarget\n",
            "head": 0,
            "start_line": 2,
            "end_line": 2,
            "offset": 7,
        }
        cases = [
            ((0, ""), "measurement", "inconclusive"),
            ((1, "f.lean:1:0: error: wrapper unavailable"), "measurement", "inconclusive"),
            ((1, f"f.lean:{engine.WRAPPER_LINES + 1}:0: error: prefix unavailable"), "context", "inconclusive"),
            (
                (1, f"f.lean:{engine.WRAPPER_LINES + 2}:0: error: identifier not found or denied"),
                "proof_error",
                "proof_error",
            ),
            ((-9, "terminated"), "worker_crash", "inconclusive"),
            ((1, f"f.lean:{engine.WRAPPER_LINES + 2}:0: error: out of memory"), "resource_denial", "inconclusive"),
            (
                (
                    1,
                    f"f.lean:{engine.WRAPPER_LINES + 2}:0: error: out of memory\n"
                    f"f.lean:{engine.WRAPPER_LINES + 2}:1: error: unknown identifier",
                ),
                "proof_error",
                "proof_error",
            ),
        ]
        for output, cause, outcome in cases:
            with self.subTest(cause=cause), contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(engine, "candidate_file", return_value=built))
                stack.enter_context(patch.object(engine, "run_lean", return_value=output))
                stack.enter_context(patch.object(engine, "last_lean_run", return_value={"path": "cold"}))
                info = engine.compile_version({}, "by trivial", "v", "c", measure=True)
                self.assertEqual(info["cause"], cause)
                self.assertEqual(info["outcome"], outcome)
                view = campaign._model_view({"ok": True, "compat": {"v": info}})
                self.assertEqual(view["outcome"], outcome)
                self.assertEqual(view["compat"]["v"]["cause"], cause)
                self.assertEqual(view["compat"]["v"]["exit_code"], output[0])
                self.assertEqual(info["raw_output"], output[1])
        with (
            patch.object(engine, "problem", return_value={"statement": "theorem t : True"}),
            self.assertRaises(engine.ProofValidityError),
        ):
            engine.evaluate("T", "theorem other : True := by trivial")

    def test_cold_projection_rejects_stale_bytes_without_changing_the_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "proofs").mkdir()
            path = directory / "proofs/p.lean"
            path.write_bytes(b"theorem t : True := by trivial\r\n")
            admit_fixture_proof(directory, "p")
            history = [{"theorem": "T", "versions": [["v", "c"]]}]
            with (
                patch.object(campaign, "problem", return_value={"name": "T"}),
                patch.object(campaign, "versions", return_value=[("v", "c")]),
                patch.object(campaign, "_evaluator_sha", return_value="evaluator"),
            ):
                identity, _, error = campaign._cold_input(directory, history, "p", 10)
                self.assertIsNone(error)
                event = {
                    "candidate_id": "p",
                    **identity,
                    "outcome": "passed",
                    "confirmed": True,
                    "passed": {"v": True},
                    "retryable": False,
                }
                self.assertEqual(campaign._cold_view(directory, history, event)["outcome"], "passed")
                path.write_bytes(b"theorem t : True := by exact True.intro\r\n")
                stale = campaign._cold_view(directory, history, event)
                self.assertEqual(stale["outcome"], "inconclusive")
                self.assertEqual(stale["cause"], "context")
                self.assertEqual(event["outcome"], "passed")
                submitted = hashlib.sha256(("T\0" + "theorem t : True := by trivial\r\n").encode()).hexdigest()
                submitted_path = directory / "proofs" / f"{submitted}.lean"
                submitted_path.write_bytes(path.read_bytes())
                _, _, changed_error = campaign._cold_input(directory, history, submitted, 10)
                self.assertIn("submitted proof identity", changed_error)
