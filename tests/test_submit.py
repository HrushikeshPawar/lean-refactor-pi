"""arena submit on fixture rows. The cold check is injected, so no test runs Lean."""

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from arena.cli import app
from arena.package import load_manifest
from arena.steps import split_steps
from arena.submit import SubmitError, build_submission
from arena.submit.gates import cold_check, gate
from arena.submit.select import load_runs, resolve_runs

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
        step_goals=None,
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
        if step_goals is not None:
            ledger.append({"kind": "step_goals", "proof_id": candidate_id, "goals": step_goals})
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
                            "spend_usd": 0.3,
                            "contributing_runs": ["gone"],
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
        provenance = json.loads((result.directory / "provenance.json").read_text())
        self.assertAlmostEqual(provenance["problems"]["B.two"]["spend_usd"], 0.3)
        self.assertEqual(provenance["problems"]["B.two"]["run_ids"], ["gone"])

    def write_previous(self, rows, name="prev"):
        previous = self.out / name
        previous.mkdir(parents=True)
        (previous / "proofs.jsonl").write_text(
            "".join(json.dumps({"name": row["name"], "proof": row["proof"]}) + "\n" for row in rows)
        )
        described = [{key: value for key, value in row.items() if key != "proof"} for row in rows]
        (previous / "manifest.json").write_text(json.dumps({"rows": described}) + "\n")

    def test_a_carried_row_counts_its_runs_against_the_ceiling(self):
        self.add_run("only", theorem="A.one", proxy=80.0, spend=(0.1,))
        self.add_run("earlier", theorem="B.two", proxy=70.0, spend=(2.0,))
        carried = STATEMENTS["B.two"] + " := by\n  rfl\n"
        self.write_previous(
            [{"name": "B.two", "proof": carried, "proxy": 70.0, "spend_usd": 0.1, "contributing_runs": ["earlier"]}]
        )
        # The run is still on disk, so its settle rows are summed again rather than trusting the record.
        result = self.build("only", previous="prev")
        self.assertEqual(result.code, 0)
        row = json.loads((result.directory / "provenance.json").read_text())["problems"]["B.two"]
        self.assertAlmostEqual(row["spend_usd"], 2.0)
        self.assertEqual(row["unlisted_runs"], {})
        over = self.build("only", previous="prev", name="over", ceiling_usd=1.5)
        self.assertEqual(over.code, 1)
        self.assertEqual([item["row"] for item in over.blocked], ["B.two"])
        self.assertIn("2.0000", over.blocked[0]["reasons"][0])
        self.write_previous([{"name": "B.two", "proof": carried, "proxy": 70.0}], name="unpriced")
        unknown = self.build("only", previous="unpriced", name="unknown")
        self.assertEqual(unknown.code, 1)
        self.assertEqual([item["row"] for item in unknown.blocked], ["B.two"])

    def test_a_named_run_with_no_verified_candidate_carries_the_previous_proof_and_its_spend(self):
        self.add_run("only", theorem="A.one", proxy=80.0, spend=(0.1,))
        self.add_run("empty", theorem="B.two", proxy=90.0, spend=(0.4,))
        ledger = (self.runs / "empty" / "ledger.jsonl").read_text().replace('"mode": "full"', '"mode": "sketch"')
        (self.runs / "empty" / "ledger.jsonl").write_text(ledger)
        carried = STATEMENTS["B.two"] + " := by\n  rfl\n"
        self.plan[carried] = {"proxy": 70.0}
        self.write_previous(
            [{"name": "B.two", "proof": carried, "proxy": 70.0, "spend_usd": 0.25, "contributing_runs": ["gone"]}]
        )
        result = self.build("only", "empty", previous="prev", name="owned")
        self.assertEqual(result.code, 0)
        self.assertNotIn("B.two", result.missing)
        manifest = {row["name"]: row for row in json.loads((result.directory / "manifest.json").read_text())["rows"]}
        self.assertEqual(manifest["B.two"]["source"], "previous")
        self.assertAlmostEqual(manifest["B.two"]["spend_usd"], 0.65)
        self.assertEqual(sorted(manifest["B.two"]["contributing_runs"]), ["empty", "gone"])
        names = {json.loads(line)["name"] for line in (result.directory / "proofs.jsonl").read_text().splitlines()}
        self.assertEqual(names, {"A.one", "B.two"})
        without = self.build("only", "empty", name="without")
        self.assertEqual(without.code, 0)
        self.assertIn("B.two", without.missing)
        self.plan[carried] = {"proxy": 70.0, "passed": {"v1": False}}
        regated = self.build("only", "empty", previous="prev", name="regated")
        self.assertEqual(regated.code, 1)
        self.assertEqual([item["row"] for item in regated.blocked], ["B.two"])
        self.assertFalse((regated.directory / "proofs.jsonl").exists())

    def test_static_gate_failures_never_reach_the_cold_compile(self):
        forbidden = STATEMENTS["A.one"] + " := by\n  native_decide\n"
        good = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.plan[good] = {"proxy": 70.0}
        self.add_run("forbidden", proof=forbidden, proxy=95.0)
        self.add_run("good", proof=good, proxy=70.0)
        compiled = []

        def recording(name, proof):
            compiled.append(proof)
            return self.cold(name, proof)

        result = build_submission(
            "static",
            ["forbidden", "good"],
            max_cold=1,
            cold_check=recording,
            runs_root=self.runs,
            output_root=self.out,
            manifest_path=self.manifest,
        )
        self.assertEqual(result.code, 0)
        self.assertEqual(compiled, [good])
        rejected = json.loads((result.directory / "manifest.json").read_text())["rejected"]
        self.assertEqual([item["row"] for item in rejected], ["A.one"])
        self.assertTrue(any("native_decide" in reason for reason in rejected[0]["reasons"]))

    def test_recombination_aligns_recorded_goals_and_keeps_full_lineage(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.add_run(
            "base",
            proof=base,
            proxy=70,
            step_goals=[
                {"id": "s1", "before": "⊢ 1 = 1", "after": "⊢ 1 = 1"},
                {"id": "s2", "before": "⊢ 1 = 1", "after": "⊢ True"},
            ],
        )
        self.add_run(
            "donor",
            proof=donor,
            proxy=60,
            step_goals=[{"id": "s1", "before": "⊢ 1 = 1", "after": "⊢ 1 = 1"}],
        )
        result = self.build("base", "donor", name="goal-hybrid")
        self.assertEqual(result.code, 0)
        hybrid = result.rows[0]
        self.assertEqual(hybrid["origin"], "submit_merge")
        self.assertEqual(hybrid["merged_from"][0]["run"], "donor")
        self.assertEqual(hybrid["merged_from"][0]["step"], "s1")
        self.assertEqual(hybrid["contributing_run_ids"], ["base", "donor"])
        manifest = json.loads((result.directory / "manifest.json").read_text())
        attempts = manifest["rows"][0]["hybrid_attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0]["accepted"])
        markdown = (result.directory / "MANIFEST.md").read_text()
        self.assertIn("merged from:", markdown)
        self.assertIn("hybrid attempt 1:", markdown)
        self.assertTrue((result.directory / "proofs-no-hybrids.jsonl").exists())
        self.assertTrue((result.directory / "hybrids" / "A.one-1.lean").exists())
        self.assertEqual((self.runs / "base" / "proofs" / "cand-base.lean").read_text(), base)
        self.assertEqual((self.runs / "donor" / "proofs" / "cand-donor.lean").read_text(), donor)

    def test_goal_mismatch_is_rejected_and_v6_uses_position_and_hash(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.add_run(
            "base",
            proof=base,
            proxy=70,
            step_goals=[
                {"id": "s1", "before": "goal A", "after": "goal B"},
                {"id": "s2", "before": "goal C", "after": "goal D"},
            ],
        )
        self.add_run(
            "wrong",
            proof=donor,
            proxy=60,
            step_goals=[{"id": "s1", "before": "different", "after": "goal D"}],
        )
        no_match = self.build("base", "wrong", name="no-goal-match")
        no_match_manifest = json.loads((no_match.directory / "manifest.json").read_text())
        self.assertEqual(no_match_manifest["rows"][0]["hybrid_attempts"], [])

        partial_base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        partial_donor = STATEMENTS["A.one"] + " := by\n  rfl\n  exact rfl\n"
        self.add_run(
            "partial-base",
            proof=partial_base,
            proxy=70,
            step_goals=[{"id": "s2", "before": "base goal", "after": None}],
        )
        self.add_run(
            "partial-donor",
            proof=partial_donor,
            proxy=60,
            step_goals=[{"id": "s2", "before": "donor goal", "after": None}],
        )
        partial = self.build("partial-base", "partial-donor", name="partial-goals")
        partial_manifest = json.loads((partial.directory / "manifest.json").read_text())
        self.assertEqual(partial_manifest["rows"][0]["hybrid_attempts"], [])

        v6_donor = STATEMENTS["A.one"] + " := by\n  rfl\n  exact rfl\n"
        self.add_run("v6-base", proof=base, proxy=70)
        self.add_run("v6-short", proof=donor, proxy=60)
        wrong_count = self.build("v6-base", "v6-short", name="v6-wrong-count")
        self.assertEqual(wrong_count.rows[0].get("origin"), None)
        self.add_run("v6-donor", proof=v6_donor, proxy=60)
        fallback = self.build("v6-base", "v6-donor", name="v6-match")
        self.assertEqual(fallback.rows[0]["origin"], "submit_merge")
        self.assertEqual(fallback.rows[0]["merged_from"][0]["run"], "v6-donor")

    def test_hybrid_cold_failure_and_non_improving_proxy_are_logged(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n"
        hybrid_proof = base.replace("simp_all [Nat.add_comm]", "rfl")
        self.add_run("base", proof=base, proxy=70)
        self.add_run("donor", proof=donor, proxy=60)
        self.plan[hybrid_proof] = {"proxy": 65, "error": "cold failed"}
        rejected = self.build("base", "donor", name="cold-rejected")
        self.assertEqual(rejected.rows[0].get("origin"), None)
        attempt = json.loads((rejected.directory / "manifest.json").read_text())["rows"][0]["hybrid_attempts"][0]
        self.assertFalse(attempt["accepted"])
        self.assertEqual(attempt["reason"], "gate failed")

        self.plan[hybrid_proof] = {"proxy": 70}
        flat = self.build("base", "donor", name="proxy-rejected")
        attempt = json.loads((flat.directory / "manifest.json").read_text())["rows"][0]["hybrid_attempts"][0]
        self.assertFalse(attempt["accepted"])
        self.assertEqual(attempt["reason"], "settled proxy did not improve")

    def test_no_hybrids_keeps_single_run_output_and_ceiling_counts_donor_calls(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.add_run("base", proof=base, proxy=70, spend=(0.4,))
        self.add_run("donor", proof=donor, proxy=60, spend=(0.4,))
        plain = self.build("base", "donor", name="plain", hybrids=False)
        self.assertEqual(plain.rows[0]["proof"], base)
        self.assertFalse((plain.directory / "proofs-no-hybrids.jsonl").exists())
        self.assertNotIn("hybrid_attempts", json.loads((plain.directory / "manifest.json").read_text())["rows"][0])

        over = self.build("base", "donor", name="over-ceiling", ceiling_usd=0.7)
        self.assertEqual(over.code, 1)
        self.assertIn("$0.8000", over.blocked[0]["reasons"][0])

    def test_static_hybrid_failure_does_not_use_the_cold_check_limit(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all only [Nat.add_comm, Nat.add_assoc, Nat.mul_comm]\n"
        forbidden = STATEMENTS["A.one"] + " := by\n  sorry\n"
        valid = STATEMENTS["A.one"] + " := by\n  exact rfl\n"
        self.add_run("base", proof=base, proxy=70)
        self.add_run("forbidden", proof=forbidden, proxy=60)
        self.add_run("valid", proof=valid, proxy=50)
        self.plan[valid] = {"proxy": 80}
        compiled = []

        def recording(name, proof):
            compiled.append(proof)
            return self.cold(name, proof)

        result = build_submission(
            "static-hybrid",
            ["base", "forbidden", "valid"],
            max_hybrids=1,
            cold_check=recording,
            runs_root=self.runs,
            output_root=self.out,
            manifest_path=self.manifest,
        )
        self.assertEqual(result.code, 0)
        attempts = json.loads((result.directory / "manifest.json").read_text())["rows"][0]["hybrid_attempts"]
        self.assertIn("static gate failed", [attempt["reason"] for attempt in attempts])
        self.assertTrue(any(attempt["accepted"] for attempt in attempts), attempts)
        self.assertEqual(len(compiled), 2)
        self.assertEqual(compiled[0], base)

    def attempts(self, result):
        return json.loads((result.directory / "manifest.json").read_text())["rows"][0]["hybrid_attempts"]

    def test_a_cheaper_step_with_only_one_matching_goal_is_never_swapped(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.add_run(
            "base",
            proof=base,
            proxy=70,
            step_goals=[{"id": "s1", "before": "goal A", "after": "goal B"}, {"id": "s2", "before": "goal B"}],
        )
        cases = {
            "before-differs": ("other", "goal B", []),
            "after-differs": ("goal A", "other", []),
            "both-match": ("goal A", "goal B", [True]),
        }
        for run_id, (before, after, accepted) in cases.items():
            self.add_run(run_id, proof=donor, proxy=60, step_goals=[{"id": "s1", "before": before, "after": after}])
            result = self.build("base", run_id, name=run_id)
            self.assertEqual([attempt["accepted"] for attempt in self.attempts(result)], accepted, run_id)

    def test_goals_on_one_side_only_never_align(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n"
        goals = [{"id": "s1", "before": "goal A", "after": "goal B"}, {"id": "s2", "before": "goal B"}]
        self.add_run("goal-base", proof=base, proxy=70, step_goals=goals)
        self.add_run("v6-donor", proof=donor, proxy=60)
        self.assertEqual(self.attempts(self.build("goal-base", "v6-donor", name="donor-v6")), [])
        self.add_run("v6-base", proof=base, proxy=70)
        self.add_run("goal-donor", proof=donor, proxy=60, step_goals=goals)
        self.assertEqual(self.attempts(self.build("v6-base", "goal-donor", name="base-v6")), [])

    def test_a_donor_step_is_spliced_at_the_base_indentation(self):
        base = (
            STATEMENTS["A.one"] + " := by\n  skip\n  simp_all only [Nat.add_comm, Nat.mul_comm, Nat.add_assoc]\n  rfl\n"
        )
        donor = STATEMENTS["A.one"] + " := by\n    skip\n    first\n      | rfl\n      | rfl\n    rfl\n"
        expected = STATEMENTS["A.one"] + " := by\n  skip\n  first\n    | rfl\n    | rfl\n  rfl\n"
        self.add_run("base", proof=base, proxy=70)
        self.add_run("donor", proof=donor, proxy=60)
        self.plan[expected] = {"proxy": 90}
        row = self.build("base", "donor").rows[0]
        self.assertEqual(row["proof"], expected)
        self.assertEqual([step["text"] for step in row["steps"]], [step.text for step in split_steps(expected)])

    def test_a_one_line_proof_is_not_recombined(self):
        one_line = STATEMENTS["A.one"] + " := by simp_all [Nat.add_comm]\n"
        self.add_run("one-line", proof=one_line, proxy=70)
        self.add_run("short", proof=STATEMENTS["A.one"] + " := by\n  rfl\n", proxy=60)
        result = self.build("one-line", "short", name="one-line-base")
        self.assertEqual(result.rows[0]["proof"], one_line)
        self.assertEqual(self.attempts(result), [])

        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        self.add_run("base", proof=base, proxy=70, step_goals=[{"id": "s1", "before": "goal A", "after": "goal B"}])
        self.add_run(
            "one-line-donor",
            proof=STATEMENTS["A.one"] + " := by rfl\n",
            proxy=60,
            step_goals=[{"id": "s1", "before": "goal A", "after": "goal B"}],
        )
        self.assertEqual(self.attempts(self.build("base", "one-line-donor", name="one-line-donor")), [])

    def test_a_hybrid_built_twice_is_compiled_once(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n"
        donor = STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n"
        self.add_run("base", proof=base, proxy=70)
        self.add_run("first", proof=donor, proxy=60)
        self.add_run("second", proof=donor, proxy=60)
        compiled = []

        def recording(name, proof):
            compiled.append(proof)
            return self.cold(name, proof)

        result = build_submission(
            "twice",
            ["base", "first", "second"],
            cold_check=recording,
            runs_root=self.runs,
            output_root=self.out,
            manifest_path=self.manifest,
        )
        self.assertEqual(compiled, [base, donor])
        self.assertEqual(len(self.attempts(result)), 1)

    def test_greedy_rounds_stack_swaps_and_donors_are_not_discarded(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  simp_all [Nat.mul_comm]\n  rfl\n"
        first = STATEMENTS["A.one"] + " := by\n  rfl\n  simp_all [Nat.mul_comm]\n  rfl\n"
        second = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  exact rfl\n  rfl\n"
        both = STATEMENTS["A.one"] + " := by\n  rfl\n  exact rfl\n  rfl\n"
        self.add_run("base", proof=base, proxy=70, spend=(0.2,))
        self.add_run("first", proof=first, proxy=60, spend=(0.3,))
        self.add_run("second", proof=second, proxy=60, spend=(0.4,))
        self.add_run("idle", proof=STATEMENTS["A.one"] + " := by\n  decide\n", proxy=50, spend=(0.1,))
        self.plan[first] = {"proxy": 85}
        self.plan[both] = {"proxy": 90}
        result = self.build("base", "first", "second", "idle")
        row = result.rows[0]
        self.assertEqual(row["proof"], both)
        self.assertEqual([item["run"] for item in row["merged_from"]], ["first", "second", "base"])
        accepted = [attempt for attempt in self.attempts(result) if attempt["accepted"]]
        self.assertEqual([attempt["donor_run"] for attempt in accepted], ["first", "second"])
        self.assertEqual(accepted[1]["base_node"], "A.one-1")
        self.assertEqual((result.directory / "hybrids" / "A.one-2.lean").read_text(), both)
        calls = {
            call["run_id"]: call
            for call in json.loads((result.directory / "provenance.json").read_text())["problems"]["A.one"]["calls"]
        }
        self.assertTrue(calls["base"]["selected_run"])
        for run_id in ("first", "second"):
            self.assertTrue(calls[run_id]["donor"], run_id)
            self.assertFalse(calls[run_id]["discarded"], run_id)
        self.assertTrue(calls["idle"]["discarded"])
        self.assertNotIn("donor", calls["idle"])

    def test_no_hybrids_writes_what_the_build_wrote_before_recombination(self):
        self.add_run("base", proof=STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n", proxy=70)
        self.add_run("donor", proof=STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n", proxy=60)
        self.plan[STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n"] = {"proxy": 90}
        self.add_run("other", theorem="B.two", proxy=75)

        def tree(root):
            files = {}
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                body = path.read_bytes()
                if path.suffix == ".json":
                    document = json.loads(body)
                    if isinstance(document, dict):
                        document.pop("generated", None)
                    body = json.dumps(document, sort_keys=True).encode()
                files[path.relative_to(root).as_posix()] = body
            return files

        def build(output_root, **kwargs):
            return build_submission(
                "same",
                ["base", "donor", "other"],
                cold_check=self.cold,
                runs_root=self.runs,
                output_root=output_root,
                manifest_path=self.manifest,
                **kwargs,
            )

        plain = build(self.root / "plain", hybrids=False)
        with patch("arena.submit.recombine", lambda rows, *_args: (rows, None)):
            before = build(self.root / "before")
        self.assertEqual(tree(plain.directory), tree(before.directory))
        hybrid = build(self.root / "hybrid")
        self.assertEqual(hybrid.rows[0]["origin"], "submit_merge")

    def test_recombination_leaves_every_source_run_file_untouched(self):
        self.add_run("base", proof=STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n  rfl\n", proxy=70)
        self.add_run("donor", proof=STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n", proxy=60)
        self.plan[STATEMENTS["A.one"] + " := by\n  rfl\n  rfl\n"] = {"proxy": 90}

        def snapshot():
            return {
                path.relative_to(self.runs).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in sorted(self.runs.rglob("*"))
                if path.is_file()
            }

        before = snapshot()
        result = self.build("base", "donor")
        self.assertEqual(result.rows[0]["origin"], "submit_merge")
        self.assertEqual(snapshot(), before)

    def test_a_raising_cold_check_fails_the_hybrid_gate(self):
        base = STATEMENTS["A.one"] + " := by\n  simp_all [Nat.add_comm]\n"
        self.add_run("base", proof=base, proxy=70)
        self.add_run("donor", proof=STATEMENTS["A.one"] + " := by\n  rfl\n", proxy=60)

        def raising(name, proof):
            if proof != base:
                raise RuntimeError("lean crashed")
            return self.cold(name, proof)

        result = build_submission(
            "raising",
            ["base", "donor"],
            cold_check=raising,
            runs_root=self.runs,
            output_root=self.out,
            manifest_path=self.manifest,
        )
        self.assertEqual(result.code, 0)
        self.assertEqual(result.rows[0]["proof"], base)
        attempt = self.attempts(result)[0]
        self.assertFalse(attempt["accepted"])
        self.assertEqual(attempt["reason"], "gate failed")

    def test_a_blocked_rebuild_keeps_the_last_good_submission(self):
        good = STATEMENTS["A.one"] + " := by\n  rfl\n"
        self.add_run("good", proof=good, proxy=80.0)
        first = self.build("good", name="keep")
        self.assertEqual(first.code, 0)
        kept = {path.name: path.read_bytes() for path in first.directory.iterdir()}
        self.add_run("bad", proof=STATEMENTS["A.one"] + " := by\n  sorry\n", proxy=90.0)
        second = self.build("bad", name="keep", previous="keep", overwrite=True)
        self.assertEqual(second.code, 1)
        for name, body in kept.items():
            self.assertEqual((second.directory / name).read_bytes(), body, name)
        self.assertIn("sorry", (second.directory / "blocked.json").read_text())

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

    def test_cold_check_gives_up_when_memory_stays_low(self):
        sleeps = []

        def sleep(_seconds):
            sleeps.append(1)
            if len(sleeps) > 10:
                raise AssertionError("still waiting past the timeout")

        with patch("arena.engine.evaluate", side_effect=AssertionError("compiled under low memory")):
            result = cold_check("A.one", "proof", memory_reader=lambda: 1.0, sleep=sleep, memory_timeout=3)
        self.assertEqual(len(sleeps), 3)
        self.assertIn("free memory", result["error"])
        row = load_manifest(self.manifest)["A.one"]
        reasons = gate(row, STATEMENTS["A.one"] + " := by\n  rfl\n", {**result, "recorded_proxy": 80.0})
        self.assertTrue(any("free memory" in reason for reason in reasons))

    def test_an_oversized_proof_fails_the_official_filter_gate(self):
        row = load_manifest(self.manifest)["A.one"]
        proof = STATEMENTS["A.one"] + " := by\n  rfl\n-- " + "a" * (256 * 1024) + "\n"
        cold = {**self.cold("A.one", proof), "recorded_proxy": 80.0}
        self.assertEqual(gate(row, proof, cold), ["official filter: too large (> 256 KB)"])

    def test_a_run_the_graph_reader_cannot_build_is_rejected_not_raised(self):
        self.add_run("good", proxy=80.0)
        _candidate, _proof, directory = self.add_run("old", proxy=90.0)
        rows = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines()]
        rows[-1]["result"]["compat"]["v1"]["diagnostics"] = ["Foo.lean:1:2: error: unknown identifier"]
        (directory / "ledger.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        loaded, rejected = load_runs(["old", "good"], self.runs)
        self.assertEqual([item["run_id"] for item in rejected], ["old"])
        self.assertEqual([run.run_id for run in loaded if run.reason is None], ["good"])
        result = self.build("old", "good")
        self.assertEqual(result.code, 0)
        provenance = json.loads((result.directory / "provenance.json").read_text())
        self.assertEqual([item["run_id"] for item in provenance["rejected_runs"]], ["old"])
        self.assertEqual(provenance["problems"]["A.one"]["run_id"], "good")

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
        self.assertIn("--hybrids", text)
        self.assertIn("--no-hybrids", text)
        self.assertIn("--max-hybrids", text)
        with patch("sys.stderr", io.StringIO()):
            code = app(["submit", "--name", "bad name", "--runs", "x"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
