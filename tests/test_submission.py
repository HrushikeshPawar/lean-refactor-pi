import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import submission as sub


def write_baseline(directory: Path, rows: dict[str, float]) -> None:
    directory.mkdir(parents=True)
    (directory / "submission.jsonl").write_text("".join(json.dumps({"name": n, "proof": f"base-{n}"}) + "\n" for n in rows))
    (directory / "scores.json").write_text(json.dumps({n: {"proxy": p, "source": "old"} for n, p in rows.items()}))


def write_run(root: Path, run_id: str, theorem: str, proxy: float, ok=True, verified="cold compile") -> None:
    run = root / run_id
    run.mkdir(parents=True)
    (run / "submission.lean").write_text(f"proof-{run_id}")
    summary = {
        "theorem": theorem,
        "model": "m",
        "cost": {"spent_usd": 0.45},
        "submission": {"ok": ok, "tokens": 10, "heartbeats": 20, "proxy": proxy, "proof_file": "submission.lean", "verified_by": verified},
    }
    (run / "summary.json").write_text(json.dumps(summary))


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.base = self.dir / "base"
        self.runs = self.dir / "runs"
        write_baseline(self.base, {"a": 80.0, "b": 90.0, "c": 50.0})
        write_run(self.runs, "r1", "a", 85.0)
        write_run(self.runs, "r2", "a", 83.0)
        write_run(self.runs, "r3", "b", 90.0)
        write_run(self.runs, "r4", "c", 99.0, ok=False)
        write_run(self.runs, "r5", "c", 99.0, verified="fast")
        (self.runs / "r7").mkdir()
        (self.runs / "r7" / "summary.json").write_text('{"theorem": "a", "submission": null}')
        (self.runs / "r6").mkdir()
        (self.runs / "r6" / "summary.json").write_text("{broken")
        self.addCleanup(self.tmp.cleanup)

    def test_run_results_filters_and_skips_broken(self):
        found = sub.run_results(self.runs)
        self.assertEqual({k: [r["run_id"] for r in v] for k, v in found.items()}, {"a": ["r1", "r2"], "b": ["r3"]})
        self.assertEqual(found["a"][0]["proof"], "proof-r1")
        self.assertEqual(sub.run_results(self.runs, ["b"]).keys(), {"b"})

    def test_choose_takes_higher_and_keeps_baseline_on_ties(self):
        base = sub.load_baseline(self.base)
        chosen = sub.choose(base, sub.run_results(self.runs))
        self.assertEqual(chosen["a"]["proof"], "proof-r1")
        self.assertEqual(chosen["a"]["delta"], 5.0)
        self.assertIn("r1", chosen["a"]["source"])
        self.assertEqual(chosen["b"]["proof"], "base-b")
        self.assertEqual(chosen["b"]["delta"], 0.0)
        self.assertFalse(chosen["c"]["changed"])

    def test_gain_order_by_headroom_stable(self):
        base = sub.load_baseline(self.base)
        res = sub.run_results(self.runs)
        self.assertEqual(sub.gain_order(["a", "b", "c"], base, res), ["c", "a", "b"])
        self.assertEqual(sub.gain_order(["b", "a"], {"a": {"proxy": 90.0}, "b": {"proxy": 90.0}}, {}), ["b", "a"])

    def build(self, name="out", **kw):
        with patch.object(sub, "check", return_value=[]):
            return sub.build(self.dir / name, self.base, self.runs, **kw)

    def test_build_writes_files_and_is_next_baseline(self):
        result = self.build()
        out = self.dir / "out"
        self.assertEqual(result["changed"], ["a"])
        self.assertEqual(result["total"], 225.0)
        self.assertEqual(result["mean"], 75.0)
        names = [json.loads(line)["name"] for line in (out / "submission.jsonl").read_text().splitlines()]
        self.assertEqual(names, ["a", "b", "c"])
        manifest = (out / "MANIFEST.md").read_text()
        self.assertLess(manifest.index("| a |"), manifest.index("| b |"))
        self.assertIn("Projected mean: 75.00", manifest)
        again = sub.load_baseline(out)
        self.assertEqual(again["a"]["proxy"], 85.0)
        self.assertEqual(again["a"]["proof"], "proof-r1")

    def test_build_refuses_existing_out_and_bad_rows(self):
        (self.dir / "exists").mkdir()
        with self.assertRaises(sub.SubmissionError):
            self.build("exists")
        with patch.object(sub, "check", side_effect=lambda n, p: ["bad"] if n == "b" else []):
            with self.assertRaises(sub.SubmissionError):
                sub.build(self.dir / "bad", self.base, self.runs)
        self.assertFalse((self.dir / "bad").exists())

    def test_cold_checks_only_changed_rows(self):
        calls = []

        def evaluate(name, proof, mode):
            calls.append((name, mode))
            return {"local_proxy": 85.02, "compat": {"v1": {"passed": True}}}

        with patch("arena.engine.evaluate", evaluate):
            self.build(cold=True)
        self.assertEqual(calls, [("a", "full")])

    def test_cold_fails_on_failure_or_proxy_drift(self):
        for result in (
            {"local_proxy": 85.0, "compat": {"v1": {"passed": False}}},
            {"local_proxy": 84.9, "compat": {"v1": {"passed": True}}},
        ):
            with patch("arena.engine.evaluate", lambda *a, r=result: r), self.assertRaises(sub.SubmissionError):
                self.build("cold-" + str(result["local_proxy"]) + str(result["compat"]["v1"]["passed"]), cold=True)

    def test_check_combines_validate_and_forbidden(self):
        with patch("arena.engine.problem", return_value={}), patch(
            "arena.engine.validate_proof", side_effect=ValueError("stmt")
        ), patch.object(sub, "forbidden_filter", return_value=lambda p: "sorry"):
            self.assertEqual(sub.check("a", "x"), ["validate: stmt", "forbidden: sorry"])
        with patch("arena.engine.problem", return_value={}), patch("arena.engine.validate_proof"), patch.object(
            sub, "forbidden_filter", return_value=lambda p: None
        ):
            self.assertEqual(sub.check("a", "x"), [])

    def test_real_forbidden_filter_rejects_sorry(self):
        self.assertTrue(sub.forbidden_filter()("theorem x : True := by sorry"))
        self.assertFalse(sub.forbidden_filter()("theorem x : True := trivial"))


if __name__ == "__main__":
    unittest.main()
