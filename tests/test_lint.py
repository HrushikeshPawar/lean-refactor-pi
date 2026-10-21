import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PyflakesTests(unittest.TestCase):
    def test_arena_has_no_undefined_names_or_pyflakes_errors(self):
        # Live run v8-SKI-r2 lost every worker to a missing `import json` that tests had patched around.
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "F", "--output-format", "concise", "arena"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
