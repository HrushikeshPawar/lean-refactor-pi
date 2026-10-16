"""Helpers kept from the v6 packager: hashes, attempts, archive and report text."""

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from arena import package


class HelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_load_manifest_and_hash(self):
        path = self.root / "warmup.jsonl"
        path.write_text(json.dumps({"name": "A.one", "statement": "theorem one : 1 = 1"}) + "\n")
        self.assertEqual(package.load_manifest(path)["A.one"]["statement"], "theorem one : 1 = 1")
        self.assertEqual(
            package.sha256_text("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        with self.assertRaises(package.PackageError):
            package.load_manifest(self.root / "missing.jsonl")

    def test_attempts_join_settles_to_the_journal(self):
        directory = self.root / "run"
        directory.mkdir()
        (directory / "cost-ledger.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"kind": "settle", "id": "a", "usd": 0.4, "usage_known": True}),
                    json.dumps({"kind": "settle", "id": "b", "usd": 0.1, "usage_known": True}),
                ]
            )
            + "\n"
        )
        (directory / "trace-journal.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"kind": "request", "id": "a", "model": "m", "retry_of": None, "trace_id": "t-1"}),
                    json.dumps({"kind": "response", "id": "a", "response_model": "m-1"}),
                    json.dumps({"kind": "request", "id": "b", "model": "m", "retry_of": "a"}),
                ]
            )
            + "\n"
        )
        spent = package.attempts(directory)
        self.assertAlmostEqual(spent["total_usd"], 0.5)
        self.assertEqual(spent["retries"], 1)
        self.assertEqual(spent["settles"][0]["model"], "m")
        self.assertEqual(spent["settles"][1]["retry_of"], "a")
        self.assertEqual(package.trace_ids(directory, {}), ["t-1"])

    def test_reproduce_text_names_arena_submit(self):
        text = package.reproduce_text("abc", ["r1", "r2"], [], ["v1"], "demo")
        self.assertIn("uv run arena submit --name demo --runs r1 r2", text)
        self.assertIn("prepares files only", text)

    def test_archive_and_report(self):
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "packages").mkdir()
        (repo / "packages" / "app.py").write_text("print(1)\n")
        (repo / ".gitmodules").write_text('[submodule "x"]\n')

        def run(*args):
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                check=True,
                capture_output=True,
            )

        run("init", "-q")
        run("add", ".")
        run("commit", "-qm", "init")
        text = "reproduce\n"
        archive = package.build_archive(repo, "HEAD", self.root / "code.tar.gz", {"REPRODUCE.md": text})
        with tarfile.open(self.root / "code.tar.gz") as bundle:
            self.assertIn("REPRODUCE.md", bundle.getnames())
            self.assertIn(".gitmodules", archive["dependency_files"])
        prov = {
            "problems": {
                "A.one": {
                    "model": {"name": "m", "response_models": ["m-1"]},
                    "run_id": "r",
                    "spend_usd": 0.5,
                    "ceiling_usd": 3.0,
                    "calls": [{"attempts": [{}], "retries": 0}],
                }
            },
            "rejected": [],
            "eligible_models": ["m"],
            "ceiling_usd": 3.0,
        }
        report = package.report(prov, "abc", "demo")
        positions = [
            report.index(f"## {section}") for section in ("Approach", "Models", "Budget accounting", "Reproduction")
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("0.5000", report)


if __name__ == "__main__":
    unittest.main()
