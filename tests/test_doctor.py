"""Arena doctor reports injected machine readings without consulting the host."""

import json
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

doctor = import_module("arena.cli.doctor")

VENDORS = ("arena-space", "lean-refactor")
PINNED = "1" * 40
OTHER = "2" * 40


class DoctorChecks(unittest.TestCase):
    def test_json_report_has_stable_check_records_and_failure_state(self):
        with (
            patch.object(doctor, "checks", return_value=[("pins", "ok", "pinned"), ("prices", "fail", "drift")]),
            tempfile.TemporaryFile(mode="w+") as output,
            patch("builtins.print", side_effect=lambda value: output.write(value)),
        ):
            status = doctor.execute(doctor.DoctorOptions(json=True))
            output.seek(0)
            report = json.loads(output.read())
        self.assertEqual(status, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][1], {"name": "prices", "status": "fail", "detail": "drift"})

    def test_wrong_pi_pin_fails_and_missing_pi_warns(self):
        with (
            patch.object(doctor, "_pin_pi_version", return_value="1.1.0"),
            patch("arena.provenance.code_version", return_value={"pi_version": "1.0.0"}),
        ):
            self.assertEqual(doctor._check_pins()[1], "fail")
        with (
            patch.object(doctor, "_pin_pi_version", return_value="1.1.0"),
            patch("arena.provenance.code_version", return_value={"pi_version": None}),
        ):
            self.assertEqual(doctor._check_pins()[1], "warn")

    def _vendor_check(self, heads, dirty=(), present=VENDORS):
        """Run _check_vendors against a fake git and a temporary vendor tree."""
        recorded = {"arena-space": PINNED, "lean-refactor": PINNED}

        def fake_git(*args, **_):
            if args[0] == "ls-tree":
                name = args[2].removeprefix("vendor/")
                return f"160000 commit {recorded[name]}\t{args[2]}"
            _, path, *command = args
            name = Path(path).name
            if command == ["rev-parse", "HEAD"]:
                return heads[name]
            if command == ["status", "--porcelain"]:
                return " M file.lean" if name in dirty else ""
            raise AssertionError(f"unexpected git call: {args}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in present:
                (root / "vendor" / name).mkdir(parents=True)
            with (
                patch.object(doctor, "ROOT", root),
                patch.object(doctor, "_git", side_effect=fake_git),
            ):
                return doctor._check_vendors()

    def test_vendor_commit_or_dirty_checkout_fails(self):
        clean = {"arena-space": PINNED, "lean-refactor": PINNED}
        with self.subTest("both at recorded commit and clean"):
            name, status, _ = self._vendor_check(clean)
            self.assertEqual((name, status), ("Vendor submodules", "ok"))
        with self.subTest("lean-refactor HEAD differs from its gitlink"):
            name, status, detail = self._vendor_check({**clean, "lean-refactor": OTHER})
            self.assertEqual(status, "fail")
            self.assertIn("differs", detail)
        with self.subTest("lean-refactor matches its gitlink but is dirty"):
            name, status, detail = self._vendor_check(clean, dirty={"lean-refactor"})
            self.assertEqual(status, "fail")
            self.assertIn("dirty", detail)
        with self.subTest("lean-refactor directory is missing"):
            name, status, detail = self._vendor_check(clean, present=("arena-space",))
            self.assertEqual(status, "fail")
            self.assertIn("missing", detail)

    def test_benchmark_digest_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "benchmark/original/warmup.jsonl"
            target.parent.mkdir(parents=True)
            target.write_text("warmup\n")
            (root / "benchmark/SHA256SUMS").write_text("0" * 64 + "  benchmark/original/warmup.jsonl\n")
            with patch.object(doctor, "ROOT", root):
                self.assertEqual(doctor._check_benchmark_hash()[1], "fail")

    def test_token_counter_mismatch_names_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "warmup.jsonl"
            fixture.write_text(json.dumps({"name": "row-a", "src": "proof", "proof_length": 4}) + "\n")
            with patch.object(doctor, "BENCHMARK", fixture), patch.object(doctor, "validate_proof", return_value=5):
                name, status, detail = doctor._check_token_counter()
        self.assertEqual((name, status), ("Official token counter", "fail"))
        self.assertIn("row-a", detail)

    def test_price_problem_fails_and_missing_optional_plugin_warns(self):
        with patch.object(doctor.models, "catalog_price_problems", return_value=["price differs", "another mismatch"]):
            name, status, detail = doctor._check_prices()
            self.assertEqual((name, status), ("Model price table", "fail"))
            self.assertEqual(detail.splitlines(), ["price differs", "another mismatch"])
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(doctor.traces, "INSTALLED_PLUGIN", Path(tmp) / "missing"),
        ):
            self.assertEqual(doctor._check_plugin()[1], "warn")

    def test_unpatched_installed_langfuse_plugin_warns_not_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "plugin.ts"
            installed.write_text("")
            with (
                patch.object(doctor.traces, "INSTALLED_PLUGIN", installed),
                patch.object(doctor.traces, "plugin_problems", return_value=["plugin differs from patch"]),
            ):
                self.assertEqual(doctor._check_plugin()[1], "warn")

    def test_measure_override_must_be_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "benchmark/derived/measure-versions.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"row-a":"v9"}')
            with (
                patch.object(doctor, "ROOT", root),
                patch.object(doctor, "problem", return_value={"name": "row-a"}),
                patch("arena.engine.versions", return_value=[("v1", "commit")]),
            ):
                self.assertEqual(doctor._check_measure_versions()[1], "fail")
