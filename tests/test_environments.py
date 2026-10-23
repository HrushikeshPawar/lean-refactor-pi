import importlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from arena import engine, environments
from arena.engine import ROOT
from tests.slow import slow

arena_certify = importlib.import_module("arena.cli.certify")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def make_repo(path: Path, message: str = "x") -> str:
    path.mkdir(parents=True)

    def run(*args):
        return subprocess.run(
            ["git", *args],
            cwd=path,
            env=GIT_ENV,
            check=True,
            capture_output=True,
            text=True,
        )

    run("init", "-q")
    (path / "A.lean").write_text(f"-- {message}\n")
    run("add", ".")
    run("commit", "-q", "-m", message)
    return run("rev-parse", "HEAD").stdout.strip()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_workspace_is_found_by_commit_whatever_its_directory_is_called(self):
        commit = make_repo(self.root / "some-copy", "one")
        make_repo(self.root / "other", "two")
        self.assertEqual(environments.resolve("physlib", "v4.32.0", commit, self.root), self.root / "some-copy")

    def test_the_conventionally_named_directory_wins_when_several_match(self):
        commit = make_repo(self.root / "zz-backup", "one")
        (self.root / "strata-v4.1.0").symlink_to(self.root / "zz-backup")
        self.assertEqual(environments.resolve("strata", "v4.1.0", commit, self.root).name, "strata-v4.1.0")

    def test_an_explicit_registry_entry_takes_precedence_and_covers_non_git_copies(self):
        (self.root / "plain-dir").mkdir()
        (self.root / "registry.json").write_text(json.dumps({"cslib@v4.31.0@abc": "plain-dir"}))
        self.assertEqual(environments.resolve("cslib", "v4.31.0", "abc", self.root), self.root / "plain-dir")

    def test_a_missing_environment_gets_an_actionable_message(self):
        with self.assertRaisesRegex(FileNotFoundError, "not provisioned: arklib v4.31.0 at deadbeef"):
            environments.resolve("arklib", "v4.31.0", "deadbeef" * 5, self.root)

    def test_provisioned_reports_what_each_row_is_missing(self):
        commit = make_repo(self.root / "have", "one")
        row = {"source": "s", "version_info": [{"v1": commit}, {"v2": "f" * 40}]}
        found = environments.provisioned(row, self.root)
        self.assertEqual([(v, p is not None) for v, _, p in found], [("v1", True), ("v2", False)])

    def test_engine_resolves_through_the_registry(self):
        commit = make_repo(self.root / "renamed", "one")
        with patch.object(environments, "WORKSPACES", self.root):
            self.assertEqual(engine.workspace({"source": "x"}, "v9", commit), self.root / "renamed")


class StandaloneTests(unittest.TestCase):
    ROW: ClassVar[dict] = {
        "name": "putnam_1999_a1",
        "source": "putnambench",
        "file_path": "",
        "header": "import Mathlib\n\nopen Nat\n\n",
        "statement": "theorem putnam_1999_a1 : True",
        "src": "theorem putnam_1999_a1 : True := by\n  trivial",
        "version_info": [{"v4.25.0": "c1"}],
    }

    def test_the_file_is_the_header_followed_by_the_candidate(self):
        with patch.object(engine, "workspace", return_value=Path("/ws")):
            built = engine.candidate_file(self.ROW, self.ROW["src"], "v4.25.0", "c1")
        self.assertEqual(
            built["text"], "import Mathlib\n\nopen Nat\n\ntheorem putnam_1999_a1 : True := by\n  trivial\n"
        )
        self.assertEqual((built["start_line"], built["end_line"]), (5, 6))
        self.assertEqual(built["text"].splitlines()[built["start_line"] - 1], "theorem putnam_1999_a1 : True := by")
        self.assertEqual(engine.source_path(self.ROW), "ArenaScratch/putnam_1999_a1.lean")
        self.assertTrue(engine.is_standalone(self.ROW))

    def test_a_standalone_row_without_a_header_is_refused(self):
        with (
            patch.object(engine, "workspace", return_value=Path("/ws")),
            self.assertRaisesRegex(ValueError, "needs its header"),
        ):
            engine.candidate_file({**self.ROW, "header": ""}, self.ROW["src"], "v4.25.0", "c1")

    def test_repository_rows_keep_their_file_path(self):
        row = engine.problem("Core.InitsUpdatesComm")
        self.assertEqual(engine.source_path(row), row["file_path"])
        self.assertFalse(engine.is_standalone(row))

    def test_standalone_rows_in_the_benchmark_have_headers(self):
        names = [json.loads(line) for line in engine.BENCHMARK.read_text().splitlines()]
        standalone = [row for row in names if engine.is_standalone(row)]
        self.assertTrue(standalone)
        self.assertTrue(all(row["header"].strip() for row in standalone))


class MeasurementVersionTests(unittest.TestCase):
    ROW: ClassVar[dict] = {"name": "R", "version_info": [{"v4.27.0": "b"}, {"v4.26.0": "a"}]}

    def test_override_wins_when_listed_and_default_selects_newest(self):
        with tempfile.TemporaryDirectory() as temporary:
            overrides = Path(temporary) / "m.json"
            with patch.object(engine, "_MEASURE_OVERRIDES", overrides):
                self.assertEqual(engine.measure_version(self.ROW), ("v4.27.0", "b"))
                overrides.write_text(json.dumps({"R": "v4.26.0"}))
                self.assertEqual(engine.measure_version(self.ROW), ("v4.26.0", "a"))
                overrides.write_text(json.dumps({"R": "v9.0.0"}))
                with self.assertRaisesRegex(ValueError, "not listed"):
                    engine.measure_version(self.ROW)
                oldest_first = {"name": "OldestFirst", "version_info": [{"v4.25.0": "a"}, {"v4.27.0": "b"}]}
                overrides.write_text("{}")
                self.assertEqual(engine.measure_version(oldest_first), ("v4.27.0", "b"))

    def test_fast_mode_also_compiles_the_measurement_version_and_records_it(self):
        calls = []

        def compile_stub(row, proof, version, commit, measure=False, probe=False, report_start_line=None, lane="model", **_kwargs):
            calls.append((version, measure))
            return {
                "passed": True,
                "heartbeats": 100 if measure else None,
                "diagnostics": [],
                "diagnostic_counts": {},
                "outside_target": {},
                "goals": [],
                "error_headlines": [],
            }

        row = {**self.ROW, "statement": "theorem R : True", "name": "R", "source": "s", "proof_length": 9}
        with (
            patch.object(engine, "problem", return_value=row),
            patch.object(engine, "validate_proof", return_value=5),
            patch.object(engine, "compile_version", side_effect=compile_stub),
            patch.object(engine, "candidate_file", return_value={"start_line": 1}),
            patch.object(engine, "measure_version", return_value=("v4.26.0", "a")),
            patch("arena.scoring.metrics", return_value={"compiled": True}),
        ):
            result = engine.evaluate("R", "theorem R : True := by trivial", "fast")
        self.assertEqual(calls, [("v4.27.0", False), ("v4.26.0", True)])
        self.assertEqual((result["measured_on"], result["heartbeat"]), ("v4.26.0", 100))


class CertificationTests(unittest.TestCase):
    def good(self, tokens=224, heartbeats=4251, passed=True):
        return {
            "tokens": tokens,
            "heartbeat": heartbeats,
            "measured_on": "v4.29.1",
            "local_proxy": 33.33,
            "compat": {"v4.29.1": {"passed": True}, "v4.27.0": {"passed": passed}},
        }

    def run_certify(self, result, provisioned=True):
        found = [("v", "c", Path("/ws") if provisioned else None)]
        with (
            patch.object(arena_certify.environments, "provisioned", return_value=found),
            patch.object(arena_certify, "evaluate", return_value=result),
            patch.object(arena_certify, "render_packet", return_value="packet"),
        ):
            return arena_certify.certify("Core.InitsUpdatesComm")

    def test_matching_reference_is_certified(self):
        self.assertEqual(self.run_certify(self.good())["status"], "certified")

    def test_calibration_and_compatibility_problems_are_reported_as_reasons(self):
        bad = self.run_certify(self.good(tokens=230, heartbeats=5000, passed=False))
        self.assertEqual(bad["status"], "failed")
        joined = " ".join(bad["reasons"])
        self.assertIn("does not compile on v4.27.0", joined)
        self.assertIn("tokens 230 differ from the published 224", joined)
        self.assertIn("drift", joined)

    def test_unprovisioned_rows_are_reported_not_failed(self):
        result = self.run_certify(self.good(), provisioned=False)
        self.assertEqual(result["status"], "unprovisioned")
        self.assertIn("unprovisioned", arena_certify.render([result]))

    @slow
    @unittest.skipUnless((ROOT / "workspaces/strata-v4.29.1").is_dir(), "Strata fixture environment is not provisioned")
    def test_the_fixture_reference_is_certified_with_real_lean(self):
        result = arena_certify.certify("Core.InitsUpdatesComm")
        self.assertEqual(result["status"], "certified", result)
        self.assertEqual(result["tokens"], {"local": 224, "published": 224})
        self.assertLess(result["heartbeats"]["drift_pct"], 5)


if __name__ == "__main__":
    unittest.main()
