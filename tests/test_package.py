"""Offline tests for the submission packager: fixture run directories, no Pi, Lean or network."""

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from arena import package

STATEMENTS = {"A.one": "theorem one : 1 = 1", "B.two": "theorem two : 2 = 2"}


def sha(text):
    return package.sha256_text(text)


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.runs = self.root / "runs"
        self.manifest = self.root / "warmup.jsonl"
        self.manifest.write_text(
            "\n".join(json.dumps({"name": n, "source": "s", "statement": s}) for n, s in STATEMENTS.items()) + "\n"
        )

    def run_dir(
        self,
        run_id,
        theorem="A.one",
        model="deepseek-v4.1-flash",
        proof=None,
        origin="model",
        spend=(0.5,),
        verified_by="cold compile",
        journal=True,
        candidate=True,
        passed=True,
        retry=False,
        config=None,
        proxy=70.0,
        cold=None,
    ):
        d = self.runs / run_id
        d.mkdir(parents=True)
        statement = STATEMENTS[theorem]
        proof = proof if proof is not None else statement + " := by\n  rfl\n"
        cid = sha(theorem + "\0" + proof)
        (d / "run-config.json").write_text(
            json.dumps(
                {"theorem": theorem, "model": model, "thinking": "high", "packet_sha256": "p" * 64, **(config or {})}
            )
        )
        versions = [["v4.29.1", "c" * 40]]
        ledger = [
            {"ts": 1.0, "kind": "init", "theorem": theorem, "versions": versions},
            {
                "ts": 2.0,
                "kind": "candidate",
                "candidate_id": cid,
                "origin": origin,
                "source_versions": versions,
                "evaluator_sha256": "e" * 64,
            },
            {"ts": 3.0, "kind": "candidate", "candidate_id": "x" * 64, "origin": "model", "source_versions": versions},
            {
                "ts": 4.0,
                "kind": "evaluation",
                "candidate_id": cid,
                "mode": "full",
                "result": {
                    "metrics": {"score": proxy},
                    "compat": {"v4.29.1": {"passed": passed, "lean": {"path": "cold"}}},
                },
            },
        ]
        if cold is not None:
            ledger.append({"ts": 5.0, "kind": "cold_verification", "candidate_id": cid, "confirmed": cold})
        (d / "ledger.jsonl").write_text("\n".join(map(json.dumps, ledger)) + "\n")
        answer = {"ok": True, "candidate": "#2" if candidate else None}
        if candidate:
            answer |= {
                "candidate_id": cid,
                "tokens": 10,
                "heartbeats": 5,
                "proxy": proxy,
                "proof_file": "submission.lean",
                "verified_by": verified_by,
            }
            (d / "submission.lean").write_text(proof)
            (d / "proofs").mkdir()
            (d / "proofs" / f"{cid}.lean").write_text(proof)
        (d / "submission.json").write_text(json.dumps(answer))
        cost, trace = [], []
        for i, usd in enumerate(spend):
            rid = f"{run_id}-r{i}"
            cost += [
                {"kind": "reserve", "id": rid, "usd": usd * 2},
                {"kind": "settle", "id": rid, "usd": usd, "usage_known": True, "ts": 10 + i},
            ]
            trace += [
                {
                    "kind": "request",
                    "id": rid,
                    "model": model,
                    "retry_of": f"{run_id}-r0" if retry and i else None,
                    "trace_id": f"trace-{run_id}",
                },
                {"kind": "response", "id": rid, "response_model": model + "-2026"},
            ]
        (d / "cost-ledger.jsonl").write_text("\n".join(map(json.dumps, cost)) + "\n")
        if journal:
            (d / "trace-journal.jsonl").write_text("\n".join(map(json.dumps, trace)) + "\n")
        return cid, proof

    def select(self, *ids):
        return package.select(list(ids), package.load_manifest(self.manifest), self.runs)

    def reasons(self, *ids):
        return {r["run_id"]: r["reasons"] for r in self.select(*ids)["rejected"]}


class SelectionTests(Fixture):
    def test_picks_best_proxy_per_problem(self):
        self.run_dir("lo", proxy=60.0)
        self.run_dir("hi", proxy=80.0)
        self.run_dir("two", theorem="B.two")
        result = self.select("lo", "hi", "two")
        self.assertEqual({k: v["run_id"] for k, v in result["selected"].items()}, {"A.one": "hi", "B.two": "two"})
        self.assertEqual(result["rejected"], [])

    def test_rejections(self):
        self.run_dir("none", candidate=False)
        self.run_dir("warm", verified_by="session")
        self.run_dir("coldfail", cold=False)
        self.run_dir("ref", origin="reference")
        self.run_dir("hybrid", origin="hybrid")
        self.run_dir("unknownorigin", origin=None)
        self.run_dir("v5", journal=False)
        self.run_dir("marked", config={"hybrid": True})
        self.run_dir("fails", passed=False)
        got = self.reasons("none", "warm", "coldfail", "ref", "hybrid", "unknownorigin", "v5", "marked", "fails")
        self.assertEqual(len(got), 9)
        text = {k: " ".join(v) for k, v in got.items()}
        self.assertIn("no candidate", text["none"])
        self.assertIn("not cold verified", text["warm"])
        self.assertIn("did not confirm", text["coldfail"])
        self.assertIn("not model-produced", text["ref"])
        self.assertIn("'hybrid'", text["hybrid"])
        self.assertIn("not model-produced", text["unknownorigin"])
        self.assertIn("v5 or legacy", text["v5"])
        self.assertIn("hybrid", text["marked"])
        self.assertIn("passing every toolchain", text["fails"])

    def test_missing_run_and_missing_candidate_event(self):
        self.assertIn("does not exist", self.reasons("ghost")["ghost"][0])
        self.run_dir("noevent")
        (self.runs / "noevent" / "ledger.jsonl").write_text("")
        self.assertTrue(any("unknown provenance" in r for r in self.reasons("noevent")["noevent"]))

    def test_prohibited_constructs(self):
        for word in ("sorry", "admit", "axiom foo : True", "native_decide"):
            self.run_dir("p-" + word[:4], proof=STATEMENTS["A.one"] + f" := by\n  {word}\n")
        got = self.reasons("p-sorr", "p-admi", "p-axio", "p-nati")
        self.assertEqual(len(got), 4)
        self.assertTrue(all("FORBIDDEN" in r[0] for r in got.values()), got)


class ManifestAndHashTests(Fixture):
    def test_statement_mismatch_and_unknown_name(self):
        self.run_dir("changed", proof="theorem one : 1 = 2 := by\n  rfl\n")
        self.assertIn("STATEMENT_MODIFIED", self.reasons("changed")["changed"][0])
        self.run_dir("other", theorem="A.one")
        manifest = package.load_manifest(self.manifest)
        del manifest["A.one"]
        result = package.select(["other"], manifest, self.runs)
        self.assertIn("not in the official manifest", result["rejected"][0]["reasons"][0])

    def test_tampered_proof_hash(self):
        self.run_dir("t")
        (self.runs / "t" / "submission.lean").write_text(STATEMENTS["A.one"] + " := by\n  simp\n")
        self.assertTrue(any("hash" in r or "snapshot" in r for r in self.reasons("t")["t"]))


class StageTests(Fixture):
    def repo(self):
        repo = self.root / "repo"
        if repo.exists():
            return repo
        repo.mkdir()
        (repo / "packages").mkdir()
        (repo / "packages" / "app.py").write_text("print(1)\n")
        (repo / ".gitmodules").write_text('[submodule "x"]\n')

        def run(*a):
            return subprocess.run(
                ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                check=True,
                capture_output=True,
            )

        run("init", "-q")
        run("add", ".")
        run("commit", "-qm", "init")
        return repo

    def stage(self, *ids, **kw):
        return package.stage(
            "test-pack",
            list(ids),
            runs_root=self.runs,
            manifest_path=self.manifest,
            output_root=self.root / "out",
            repo=self.repo(),
            **kw,
        )

    def test_stage_outputs_provenance_archive_report(self):
        cid, proof = self.run_dir("good", spend=(0.4, 0.3), retry=True)
        self.run_dir("loser", spend=(0.2,), proxy=10.0)  # discarded run, still charged
        out = self.stage("good", "loser")
        rows = [json.loads(line) for line in (out / "proofs.jsonl").read_text().splitlines()]
        self.assertEqual(rows, [{"name": "A.one", "proof": proof}])
        self.assertEqual(set(rows[0]), {"name", "proof"})
        prov = json.loads((out / "provenance.json").read_text())
        row = prov["problems"]["A.one"]
        self.assertEqual(row["proof_sha256"], sha(proof))
        self.assertEqual((row["candidate_id"], row["run_id"]), (cid, "good"))
        self.assertEqual(row["pinned_sources"], [["v4.29.1", "c" * 40]])
        self.assertEqual(row["toolchains"], ["v4.29.1"])
        self.assertEqual(row["local_verification"]["lean_paths"], {"v4.29.1": "cold"})
        self.assertEqual(row["langfuse"]["trace_ids"], ["trace-good"])
        self.assertEqual(row["model"]["response_models"], ["deepseek-v4.1-flash-2026"])
        self.assertAlmostEqual(row["spend_usd"], 0.9)  # both attempts and the losing run
        calls = {c["run_id"]: c for c in row["calls"]}
        self.assertEqual(len(calls["good"]["attempts"]), 2)
        self.assertEqual(calls["good"]["retries"], 1)
        self.assertTrue(calls["loser"]["discarded"])
        self.assertEqual(calls["loser"]["attempts"][0]["usd"], 0.2)
        names = tarfile.open(out / "code.tar.gz").getnames()
        self.assertIn("packages/app.py", names)
        self.assertIn("REPRODUCE.md", names)
        self.assertIn(".gitmodules", prov["code_archive"]["dependency_files"])
        self.assertIn("tools/arena_package.py", (out / "REPRODUCE.md").read_text())
        text = (out / "report.md").read_text()
        positions = [text.index(f"## {s}") for s in ("Approach", "Models", "Budget accounting", "Reproduction")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("deepseek-v4.1-flash", text)
        self.assertIn("0.9000", text)

    def test_ceiling_violation_counts_unlisted_runs(self):
        self.run_dir("a", spend=(2.0,))
        self.run_dir("b", spend=(1.5,), proxy=1.0)
        with self.assertRaisesRegex(package.PackageError, "exceeds the \\$3.00 ceiling"):
            self.stage("a", "b")
        with self.assertRaisesRegex(package.PackageError, "ceiling"):
            self.stage("a", discover=True)  # opt-in: b is discovered from the runs directory
        self.stage("a")  # default counts only the listed runs

    def test_unresolved_reservation_counts(self):
        self.run_dir("r", spend=(1.0,))
        with (self.runs / "r" / "cost-ledger.jsonl").open("a") as handle:
            handle.write(json.dumps({"kind": "reserve", "id": "dangling", "usd": 2.5}) + "\n")
        with self.assertRaisesRegex(package.PackageError, "ceiling"):
            self.stage("r")

    def test_ineligible_model(self):
        self.run_dir("bad", model="gpt-5-mystery")
        with self.assertRaisesRegex(package.PackageError, "not in the eligibility list"):
            self.stage("bad")

    def test_nothing_acceptable_refuses(self):
        self.run_dir("ref", origin="reference")
        with self.assertRaisesRegex(package.PackageError, "no acceptable candidate"):
            self.stage("ref")

    def test_pluggable_template(self):
        self.run_dir("g")
        from string import Template

        out = self.stage("g", template=Template("T:$title|$approach|$models|$budget|$reproduction"))
        self.assertTrue((out / "report.md").read_text().startswith("T:Arena submission report: test-pack"))


if __name__ == "__main__":
    unittest.main()
