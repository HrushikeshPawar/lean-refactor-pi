import unittest
from unittest.mock import patch

from arena.engine import evaluate, problem, reconstruct, validate_proof


class EvaluatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.row = problem("Core.InitsUpdatesComm")

    def test_exact_reference_reconstructs_from_pinned_git(self):
        path, source = reconstruct(self.row, self.row["src"], "v4.29.1",
                                   self.row["version_info"][0]["v4.29.1"])
        self.assertIn(self.row["src"], source)
        self.assertEqual(path.name, "strata-v4.29.1")

    def test_forbidden_and_statement_changes_fail_before_compile(self):
        with self.assertRaisesRegex(ValueError, "FORBIDDEN: sorry"):
            validate_proof(self.row, self.row["statement"] + " := by sorry")
        with self.assertRaisesRegex(ValueError, "STATEMENT_MODIFIED"):
            validate_proof(self.row, "theorem Wrong := by trivial")
        with self.assertRaisesRegex(ValueError, "EXTRA_COMMAND"):
            validate_proof(self.row, self.row["src"] + "\ntheorem Extra : True := by trivial")

    def test_fast_checks_one_version_and_full_checks_all(self):
        with patch("arena.engine.compile_version", return_value={"passed": True, "heartbeats": 4399}) as compile_mock:
            fast = evaluate(self.row["name"], self.row["src"], "fast")
            self.assertEqual(compile_mock.call_count, 1)
            self.assertEqual(fast["tokens"], 224)
            self.assertEqual(fast["heartbeat"], 4399)
            compile_mock.reset_mock()
            full = evaluate(self.row["name"], self.row["src"], "full")
            self.assertEqual(compile_mock.call_count, 3)
            self.assertIsNone(full["score"])
            self.assertEqual(full["local_proxy"], 32.17)


if __name__ == "__main__":
    unittest.main()
