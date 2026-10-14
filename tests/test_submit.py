"""arena submit on fixture rows. The cold check is injected, so no test runs Lean."""

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arena.cli import app
from arena.submit import SubmitError, build_submission
from arena.submit.gates import cold_check
from arena.submit.select import resolve_runs

STATEMENTS = {
    "A.one": "theorem one : 1 = 1",
    "B.two": "theorem two : 2 = 2",
    "C.three": "theorem three : 3 = 3",
}
VERSIONS = [("v1", "c" * 40)]
AXES = {"tokens": 1.0, "heartbeats": 2.0, "compat": 30.0}


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.runs = self.root / "runs"
        self.out = self.root / "submission"
        self.runs.mkdir()
        self.plan = {}
        self.versions = {name: list(VERSIONS) for name in STATEMENTS}
        self._write_manifest()

    def _write_manifest(self):
        rows = []
        for name, statement in STATEMENTS.items():
            rows.append(
                {
                    "name": name,
                    "statement": statement,
                    "source": "s",
                    "version_info": [{version: commit} for version, commit in self.versions[name]],
                }
            )
        self.manifest = self.root / "warmup.jsonl"
        self.manifest.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    def cold(self, name, proof):
        spec = self.plan.get(proof, {})
        passed = spec.get("passed")
        if passed is None:
            passed = {version: True for version, _commit in self.versions[name]}
        return {
            "passed": passed,
            "tokens": spec.get("tokens", 10),
            "heartbeats": spec.get("heartbeats", 5),
            "proxy": spec.get("proxy", 80.0),
            "axes": AXES,
            "error": spec.get("error"),
        }

    def add_run(
        self,
        run_id,
        theorem="A.one",
        proof=None,
        proxy=80.0,
        spend=(0.5,),
        origin="model",
        tokens=10,
        heartbeats=5,
        code=None,
        tool_call_id=None,
        journal=False,
        config=True,
    ):
        statement = STATEMENTS[theorem]
        proof = statement + " := by\n  rfl\n" if proof is None else proof
        self.plan.setdefault(proof, {"proxy": proxy, "tokens": tokens, "heartbeats": heartbeats})
        directory = self.runs / run_id
        directory.mkdir(parents=True)
        candidate_id = f"cand-{run_id}"
        versions = [list(pair) for pair in self.versions[theorem]]
        if config:
            payload = {
                "theorem": theorem,
                "model": "deepseek-v4.1-flash",
                "provider": "deepseek",
                "model_version": "2026-01",
            }
            if code is not None:
                payload["code"] = code
            (directory / "run-config.json").write_text(json.dumps(payload))
        candidate = {
            "kind": "candidate",
            "candidate_id": candidate_id,
            "origin": origin,
            "source_versions": versions,
            "evaluator_sha256": "e" * 64,
            "ts": 2,
        }
        if tool_call_id:
            candidate["tool_call_id"] = tool_call_id
            candidate["request_id"] = "req-1"
        ledger = [
            {"kind": "init", "theorem": theorem, "versions": versions, "ts": 1},
            candidate,
            {
                "kind": "evaluation",
                "candidate_id": candidate_id,
                "mode": "full",
                "ts": 3,
                "result": {
                    "tokens": tokens,
                    "heartbeat": heartbeats,
                    "local_proxy": proxy,
                    "compat": {version: {"passed": True} for version, _commit in self.versions[theorem]},
                    "metrics": {"proxy": proxy, "axes": {key: {"contribution": value} for key, value in AXES.items()}},
                },
            },
        ]
        (directory / "ledger.jsonl").write_text("\n".join(json.dumps(row) for row in ledger) + "\n")
        proofs = directory / "proofs"
        proofs.mkdir()
        (proofs / f"{candidate_id}.lean").write_text(proof)
        settles = []
        requests = []
        for index, usd in enumerate(spend):
            settle_id = "req-1" if index == 0 and tool_call_id else f"{run_id}-s{index}"
            settles.append({"kind": "settle", "id": settle_id, "usd": usd, "usage_known": True, "tokens": {"input": 1}})
            requests.append({"kind": "request", "id": settle_id, "model": "deepseek-v4.1-flash", "retry_of": None})
        (directory / "cost-ledger.jsonl").write_text("\n".join(json.dumps(row) for row in settles) + "\n")
        if journal or tool_call_id:
            rows = [
                {"kind": "request", "id": "req-1", "turn": 4, "model": "deepseek-v4.1-flash"},
                {"kind": "tool_call", "id": "req-1", "turn": 4, "tool_call_id": tool_call_id or "call", "ts": 4000},
            ]
            (directory / "trace-journal.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        elif requests:
            (directory / "trace-journal.jsonl").write_text("\n".join(json.dumps(row) for row in requests) + "\n")
        return candidate_id, proof, directory

    def build(self, *run_ids, **kwargs):
        return build_submission(
            kwargs.pop("name", "pack"),
            list(run_ids),
            cold_check=self.cold,
            memory_reader=lambda: None,
            runs_root=self.runs,
            output_root=self.out,
            manifest_path=self.manifest,
            **kwargs,
        )

    def test_gate_failures_block_the_file(self):
        cases = {
            "changed": STATEMENTS["A.one"].replace("1 = 1", "1 = 2") + " := by\n  rfl\n",
            "sorry": STATEMENTS["A.one"] + " := by\n  sorry\n",
            "comment": STATEMENTS["A.one"] + " := by\n  rfl -- sorry\n",
        }
        self.versions["A.one"] = [("v1", "c" * 40), ("v2", "d" * 40)]
        self._write_manifest()
        cold_fail = STATEMENTS["A.one"] + " := by\n  rfl\n"
        for name, proof in cases.items():
            with self.subTest(case=name):
                self.add_run(name, proof=proof, proxy=80.0)
                result = self.build(name, name=name)
                self.assertEqual(result.code, 1)
                self.assertFalse((result.directory / "proofs.jsonl").exists())
                text = (result.directory / "blocked.json").read_text()
                self.assertIn("A.one", text)
                self.assertIn("sorry" if name != "changed" else "differs", text)
        self.plan[cold_fail] = {"proxy": 80.0, "passed": {"v1": True, "v2": False}}
        self.add_run("cold", proof=cold_fail, proxy=80.0)
        result = self.build("cold", name="cold")
        self.assertEqual(result.code, 1)
        self.assertFalse((result.directory / "proofs.jsonl").exists())
        self.assertIn("v2", (result.directory / "blocked.json").read_text())

    def test_selection_uses_the_settled_proxy_when_it_disagrees_with_the_record(self):
        high = STATEMENTS["A.one"] + " := by\n  rfl -- HIGH\n"
        low = STATEMENTS["A.one"] + " := by\n  rfl -- LOW\n"
        self.plan[high] = {"proxy": 50.0}
        self.plan[low] = {"proxy": 70.0}
        self.add_run("high", proof=high, proxy=90.0, tokens=4)
        self.add_run("low", proof=low, proxy=70.0, tokens=8)
        result = self.build("high", "low")
        self.assertEqual(result.code, 0)
        rows = [json.loads(line) for line in (result.directory / "proofs.jsonl").read_text().splitlines()]
        self.assertEqual(rows, [{"name": "A.one", "proof": low}])
        manifest = json.loads((result.directory / "manifest.json").read_text())
        self.assertEqual(manifest["rows"][0]["proxy"], 70.0)
        self.assertEqual(manifest["rows"][0]["run_id"], "low")

    def test_a_missing_run_is_carried_and_a_row_with_neither_is_listed(self):
        self.add_run("only", theorem="A.one", proxy=80.0)
        carried = STATEMENTS["B.two"] + " := by\n  rfl\n"
        self.plan[carried] = {"proxy": 70.0}
        previous = self.out / "prev"
        previous.mkdir(parents=True)
        (previous / "proofs.jsonl").write_text(json.dumps({"name": "B.two", "proof": carried}) + "\n")
        (previous / "manifest.json").write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "name": "B.two",
                            "proxy": 90.0,
                            "recorded_proxy": 70.0,
                            "graph_id": "n4",
                            "label": "#4",
                            "candidate_id": "old",
                        }
                    ]
                }
            )
        )
        result = self.build("only", previous="prev")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.missing, ["C.three"])
        manifest = json.loads((result.directory / "manifest.json").read_text())
        by_name = {row["name"]: row for row in manifest["rows"]}
        self.assertEqual(by_name["A.one"]["source"], "run")
        self.assertEqual(by_name["B.two"]["source"], "previous")
        self.assertEqual(by_name["B.two"]["graph_id"], "n4")
        self.assertEqual(by_name["B.two"]["proxy"], 70.0)
        self.assertEqual(by_name["B.two"]["recorded_proxy"], 70.0)
        self.assertEqual(manifest["missing"], ["C.three"])
        names = {json.loads(line)["name"] for line in (result.directory / "proofs.jsonl").read_text().splitlines()}
        self.assertEqual(names, {"A.one", "B.two"})

    def test_a_named_run_with_no_eligible_candidate_does_not_keep_the_previous_proof(self):
        self.add_run("only", theorem="A.one", proxy=80.0)
        self.add_run("empty", theorem="B.two", proxy=90.0)
        ledger = (self.runs / "empty" / "ledger.jsonl").read_text().replace('"mode": "full"', '"mode": "sketch"')
        (self.runs / "empty" / "ledger.jsonl").write_text(ledger)
        carried = STATEMENTS["B.two"] + " := by\n  rfl\n"
        previous = self.out / "prev"
        previous.mkdir(parents=True)
        (previous / "proofs.jsonl").write_text(json.dumps({"name": "B.two", "proof": carried}) + "\n")
        (previous / "manifest.json").write_text(json.dumps({"rows": [{"name": "B.two", "proxy": 70.0}]}) + "\n")
        result = self.build("only", "empty", previous="prev", name="owned")
        self.assertEqual(result.code, 0)
        self.assertIn("B.two", result.missing)
        names = {json.loads(line)["name"] for line in (result.directory / "proofs.jsonl").read_text().splitlines()}
        self.assertEqual(names, {"A.one"})

    def test_provenance_sums_selected_and_discarded_calls_and_the_ceiling_blocks(self):
        winner, _proof, directory = self.add_run(
            "win",
            proxy=80.0,
            spend=(0.4, 0.1),
            tool_call_id="call-9",
            code={"commit": "abc123", "dirty": False},
        )
        session = directory / "session"
        session.mkdir()
        (session / "pi.jsonl").write_text(
            json.dumps({"type": "message", "message": {"role": "assistant", "usage": {"cost": {"total": 5.0}}}}) + "\n"
        )
        self.add_run("lose", proxy=10.0, spend=(0.25,))
        self.add_run("aside", proxy=10.0, spend=(1.5,))
        before = sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file())
        result = self.build("win", "lose")
        after = sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file())
        self.assertEqual(before, after)
        self.assertEqual(result.code, 0)
        provenance = json.loads((result.directory / "provenance.json").read_text())
        row = provenance["problems"]["A.one"]
        self.assertEqual(row["graph_id"], "n1")
        self.assertEqual(row["label"], "#1")
        self.assertEqual(row["candidate_id"], winner)
        self.assertEqual(row["code"]["commit"], "abc123")
        self.assertEqual(row["tool_call_id"], "call-9")
        self.assertEqual(row["request_id"], "req-1")
        self.assertEqual(row["turn"], 4)
        self.assertAlmostEqual(row["spend_usd"], 0.75)
        calls = {call["run_id"]: call for call in row["calls"]}
        self.assertAlmostEqual(calls["win"]["settled_usd"], 0.5)
        self.assertAlmostEqual(calls["win"]["total_usd"], 5.0)
        self.assertEqual(sorted(item["usd"] for item in calls["win"]["attempts"]), [0.1, 0.4])
        self.assertEqual(calls["lose"]["attempts"][0]["usd"], 0.25)
        self.assertTrue(calls["lose"]["discarded"])
        self.assertAlmostEqual(row["unlisted_runs"]["aside"], 1.5)
        manifest = json.loads((result.directory / "manifest.json").read_text())
        self.assertEqual(manifest["rows"][0]["graph_id"], "n1")
        self.assertEqual(manifest["rows"][0]["label"], "#1")
        self.add_run("named", proxy=80.0, spend=(2.0,))
        self.add_run("hidden", proxy=10.0, spend=(1.5,))
        quiet = self.build("named", name="quiet")
        self.assertEqual(quiet.code, 0)
        quiet_row = json.loads((quiet.directory / "provenance.json").read_text())["problems"]["A.one"]
        self.assertAlmostEqual(quiet_row["spend_usd"], 2.0)
        self.assertAlmostEqual(quiet_row["unlisted_runs"]["hidden"], 1.5)
        discovered = self.build("named", name="discovered", discover=True)
        self.assertEqual(discovered.code, 1)
        self.assertIn("5.7500", (discovered.directory / "blocked.json").read_text())
        self.assertIn("hidden", (discovered.directory / "blocked.json").read_text())
        self.assertFalse((discovered.directory / "proofs.jsonl").exists())
        self.add_run("left", proxy=80.0, spend=(2.0,))
        self.add_run("right", proxy=70.0, spend=(1.5,))
        over = self.build("left", "right", name="sum")
        self.assertEqual(over.code, 1)
        body = (over.directory / "blocked.json").read_text()
        self.assertIn("3.5000", body)
        self.assertIn("left", body)
        self.assertIn("right", body)
        self.assertFalse((over.directory / "proofs.jsonl").exists())

    def test_diff_lists_a_worse_row_and_a_dropped_row_first(self):
        worse = STATEMENTS["A.one"] + " := by\n  rfl\n"
        better = STATEMENTS["C.three"] + " := by\n  rfl\n"
        self.plan[worse] = {"proxy": 80.0}
        self.plan[better] = {"proxy": 20.0}
        self.add_run("a", theorem="A.one", proof=worse, proxy=80.0, spend=(0.1,))
        self.add_run("c", theorem="C.three", proof=better, proxy=20.0, spend=(0.1,))
        previous = self.out / "prev"
        previous.mkdir(parents=True)
        (previous / "proofs.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"name": "A.one", "proof": "old a"}),
                    json.dumps({"name": "B.two", "proof": "old b"}),
                    json.dumps({"name": "C.three", "proof": "old c"}),
                ]
            )
            + "\n"
        )
        (previous / "manifest.json").write_text(
            json.dumps(
                {
                    "rows": [
                        {"name": "A.one", "proxy": 90.0},
                        {"name": "B.two", "proxy": 50.0},
                        {"name": "C.three", "proxy": 10.0},
                    ]
                }
            )
        )
        # B stays out of this manifest so the previous row is dropped rather than carried.
        kept = self.manifest.read_text()
        rows = [json.loads(line) for line in kept.splitlines() if json.loads(line)["name"] != "B.two"]
        self.manifest.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        result = self.build("a", "c", previous="prev")
        self.assertEqual(result.code, 0)
        text = (result.directory / "diff.md").read_text()
        worse_section, other = text.split("## Other changes")
        self.assertIn("A.one", worse_section)
        self.assertIn("B.two", worse_section)
        self.assertIn("dropped", worse_section)
        self.assertIn("C.three", other)
        diff = json.loads((result.directory / "diff.json").read_text())
        self.assertEqual(diff["worse"], ["A.one", "B.two"])
        self.assertEqual([row["name"] for row in diff["rows"][:2]], ["A.one", "B.two"])

    def test_a_clean_fixture_writes_every_submission_file(self):
        proof_id, proof, directory = self.add_run("good", proxy=80.0, spend=(0.2,), code={"commit": "abc123"})
        before = {path.relative_to(directory).as_posix() for path in directory.rglob("*")}
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("hi\n")
        import subprocess

        def git(*args):
            subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                check=True,
                capture_output=True,
            )

        git("init", "-q")
        git("add", ".")
        git("commit", "-qm", "init")
        result = self.build("good", archive=True, repo=repo)
        self.assertEqual(result.code, 0)
        self.assertEqual({path.relative_to(directory).as_posix() for path in directory.rglob("*")}, before)
        written = sorted(path.name for path in result.directory.iterdir())
        self.assertEqual(
            written,
            [
                "MANIFEST.md",
                "REPRODUCE.md",
                "code.tar.gz",
                "diff.json",
                "diff.md",
                "manifest.json",
                "proofs.jsonl",
                "provenance.json",
            ],
        )
        self.assertIn("no previous submission", (result.directory / "diff.md").read_text())
        row = json.loads((result.directory / "proofs.jsonl").read_text())
        self.assertEqual(row, {"name": "A.one", "proof": proof})
        self.assertEqual(
            json.loads((result.directory / "provenance.json").read_text())["problems"]["A.one"]["candidate_id"],
            proof_id,
        )
        self.assertIn("uv run arena submit --name pack --runs good", (result.directory / "REPRODUCE.md").read_text())

    def test_unknown_run_and_unknown_provenance_are_rejected(self):
        with self.assertRaises(SubmitError) as raised:
            self.build("missing-run")
        self.assertIn("missing-run", str(raised.exception))
        (self.runs / "aa").mkdir()
        (self.runs / "aa-extra").mkdir()
        (self.runs / "aa" / "run-config.json").write_text("{}")
        self.assertEqual(resolve_runs(["aa"], self.runs), ["aa"])
        self.assertEqual(resolve_runs(["aa-"], self.runs), ["aa-extra"])
        bare = self.runs / "bare"
        bare.mkdir()
        (self.runs / "aa-bare").mkdir()
        self.add_run("aa-kept", theorem="A.one", proxy=80.0)
        mixed = self.build("aa-", "bare", name="bare")
        self.assertEqual(mixed.code, 0)
        self.assertTrue((mixed.directory / "proofs.jsonl").is_file())
        provenance = json.loads((mixed.directory / "provenance.json").read_text())
        rejected = {item["run_id"]: item["reasons"] for item in provenance["rejected_runs"]}
        self.assertEqual(rejected["bare"], ["unknown provenance"])
        self.assertEqual(rejected["aa-bare"], ["unknown provenance"])
        self.assertNotIn("aa-kept", rejected)
        names = {json.loads(line)["name"] for line in (mixed.directory / "proofs.jsonl").read_text().splitlines()}
        self.assertIn("A.one", names)

    def test_cold_check_stops_after_the_cap(self):
        high = STATEMENTS["A.one"] + " := by\n  rfl -- HIGH\n"
        low = STATEMENTS["A.one"] + " := by\n  rfl -- LOW\n"
        self.plan[high] = {"proxy": 10.0}
        self.plan[low] = {"proxy": 70.0}
        self.add_run("high", proof=high, proxy=90.0)
        self.add_run("low", proof=low, proxy=70.0)
        result = self.build("high", "low", name="capped", max_cold=1)
        self.assertEqual(result.code, 1)
        self.assertIn("A.one", (result.directory / "blocked.json").read_text())
        self.assertFalse((result.directory / "proofs.jsonl").exists())

    def test_cold_check_waits_for_free_memory_and_skips_when_unknown(self):
        canned = {
            "compat": {"v1": {"passed": True}},
            "tokens": 3,
            "heartbeat": 4,
            "local_proxy": 1.5,
            "metrics": {"axes": {"tokens": {"contribution": 0.5}}},
        }
        sleeps = []
        with patch("arena.engine.evaluate", return_value=canned):
            unknown = cold_check("A.one", "proof", memory_reader=lambda: None, sleep=lambda _seconds: sleeps.append(1))
        self.assertEqual(sleeps, [])
        self.assertEqual(unknown["proxy"], 1.5)
        self.assertEqual(unknown["heartbeats"], 4)
        free = iter([1.0, 9.0])
        with patch("arena.engine.evaluate", return_value=canned):
            cold_check("A.one", "proof", memory_reader=lambda: next(free), sleep=lambda _seconds: sleeps.append(1))
        self.assertEqual(sleeps, [1])

    def test_help_lists_the_upload_checklist_and_a_bad_name_exits_2(self):
        output = io.StringIO()
        with patch("sys.stdout", output), patch("sys.stderr", output):
            status = app(["submit", "--help"])
        self.assertIn(status, (0, None))
        text = output.getvalue()
        self.assertIn("prepares files only", text.lower())
        self.assertIn("owner uploads", text.lower())
        self.assertIn("November 1, 2026", text)
        self.assertIn("November 8, 2026", text)
        self.assertIn("Submit", text)
        with patch("sys.stderr", io.StringIO()):
            code = app(["submit", "--name", "bad name", "--runs", "x"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
