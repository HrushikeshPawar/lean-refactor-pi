"""Seeded runs: the graph, the provenance row, the prior-work section and the campaign requeue. No Lean or provider."""

import contextlib
import importlib
import io
import json
import os
import signal
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

from rich.console import Console

from arena import campaign, seed
from arena import text as agent_text
from arena.cli import campaigns as rc
from arena.graph import Graph
from tests.graph_support import FakeRunCase
from tests.pi_support import PI_AVAILABLE, FakeRun, message_text
from tests.slow import slow
from tests.test_campaign import LOCK, campaign_args, offline_campaign
from tests.test_findings_v7_ski2 import _history
from tests.test_runner import FIXTURE, SPEND_90_PCT, STOP, STOP_TEXT, cheap_tool

SOL = "gpt-6.1-sol"
DEEPSEEK = "deepseek-v4.1-flash"


def write_seed(root: Path, name: str = "seed-run") -> Path:
    """An ended run of theorem T: three nodes (the best scores 70), bookkeeping rows, a session and a summary."""
    directory = root / name
    history, proofs = _history({"a": (60.0, True), "b": (70.0, True), "c": (65.0, True)})
    noise = [
        {"kind": "scratch", "code_sha256": "x", "tool_call_id": "call-1", "turn": 1},
        {"kind": "restart", "proof_id": "a"},
        {"kind": "cold_verification", "candidate_id": "b", "confirmed": True},
        {"kind": "closing_drain", "checked": 0},
    ]
    stamped = [
        {**row, "tool_call_id": "call-9", "request_id": "r-9", "turn": 3} if row["kind"] == "edge" else row
        for row in history
    ]
    rows = [stamped[0], *noise, *stamped[1:]]
    directory.mkdir(parents=True)
    (directory / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (directory / "proofs").mkdir()
    for key, proof in proofs.items():
        (directory / "proofs" / f"{key}.lean").write_text(proof)
    (directory / "cost-ledger.jsonl").write_text('{"cost": 1.0}\n')
    (directory / "summary.json").write_text('{"stop_reason": "usage_limit"}')
    (directory / "session").mkdir()
    (directory / "session" / "s.jsonl").write_text(session_text(4))
    return directory


def session_text(turns: int) -> str:
    """Pi session rows: turn n reasons readably when n is even, else only with an encrypted signature."""
    rows = [{"type": "session", "id": "s"}]
    for n in range(1, turns + 1):
        thinking = {"type": "thinking", "thinking": f"idea {n}" if n % 2 == 0 else "", "thinkingSignature": "enc"}
        call = {"type": "toolCall", "id": f"c{n}", "name": "compile", "arguments": {"drafts": ["x " * 400]}}
        rows.append({"type": "message", "message": {"role": "assistant", "content": [thinking, call]}})
        result = {
            "role": "toolResult",
            "toolCallId": f"c{n}",
            "content": [{"type": "text", "text": f"## Result\nn{n} compiles"}],
        }
        rows.append({"type": "message", "message": result})
    rows.append(
        {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "all done"}]}}
    )
    return "".join(json.dumps(row) + "\n" for row in rows)


@contextlib.contextmanager
def seeded_run(root: Path, run_id: str = "new-run"):
    """A run directory holding only the new run's init row, as `init` leaves it before carrying a seed over."""
    original = campaign.run_dir
    with (
        mock.patch.object(campaign, "run_dir", lambda ident: root / ident),
        mock.patch.object(campaign, "materialize") as materialize,
    ):
        directory = root / run_id
        directory.mkdir(parents=True)
        first = campaign.events(root / "seed-run")[0]
        campaign._append(directory, first)
        yield directory, materialize
    assert campaign.run_dir is original


class CarryOverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed = write_seed(self.root)
        self.addCleanup(self.tmp.cleanup)

    def graph(self, directory: Path) -> Graph:
        return Graph.from_history(campaign.events(directory), campaign._proof_reader(directory))

    def test_the_new_run_has_the_seeds_nodes_ids_and_best(self):
        with seeded_run(self.root) as (directory, materialize):
            info = seed.carry_over("T", "new-run", self.seed)
            old, new = self.graph(self.seed), self.graph(directory)
            self.assertEqual(
                [(n.id, n.proof_id, n.score) for n in new.nodes], [(n.id, n.proof_id, n.score) for n in old.nodes]
            )
            self.assertEqual(info["best_proxy"], 70.0)
            self.assertEqual(campaign.state("new-run")["best"]["proxy"], 70.0)
            self.assertEqual(campaign.state("new-run")["best"]["candidate"], "#2")
            self.assertEqual(materialize.call_args.args[2], (self.seed / "proofs" / "b.lean").read_text())

    def test_one_seeded_row_records_the_source_and_bookkeeping_rows_stay_behind(self):
        with seeded_run(self.root) as (directory, _):
            seed.carry_over("T", "new-run", self.seed)
            history = campaign.events(directory)
        kinds = [row["kind"] for row in history]
        self.assertEqual(kinds.count("seeded"), 1)
        self.assertEqual(kinds.count("init"), 1)
        self.assertFalse({"scratch", "restart", "cold_verification", "closing_drain"} & set(kinds))
        row = next(item for item in history if item["kind"] == "seeded")
        self.assertEqual((row["source_run"], row["best_proxy"]), ("seed-run", 70.0))
        self.assertEqual(kinds[-2:], ["focus", "current"])
        self.assertEqual(history[-1]["candidate_id"], "b")
        self.assertFalse(any({"tool_call_id", "request_id", "turn"} & set(item) for item in history))

    def test_spend_starts_at_zero(self):
        with seeded_run(self.root) as (directory, _):
            seed.carry_over("T", "new-run", self.seed)
            self.assertFalse((directory / "cost-ledger.jsonl").exists())
            self.assertFalse((directory / "cost.json").exists())

    def test_a_seed_must_be_an_ended_run_of_the_same_theorem(self):
        (self.seed / "summary.json").unlink()
        with self.assertRaisesRegex(ValueError, "summary.json"):
            seed.check_seed(self.seed)
        with self.assertRaisesRegex(ValueError, "not a directory"):
            seed.check_seed(self.root / "missing")
        (self.seed / "summary.json").write_text("{}")
        with seeded_run(self.root) as _, self.assertRaisesRegex(ValueError, "not a run of Other"):
            seed.carry_over("Other", "new-run", self.seed)


class PriorWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.seed = write_seed(self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_the_section_holds_the_map_and_the_digest_and_names_no_model(self):
        with seeded_run(self.root) as (directory, _):
            seed.carry_over("T", "new-run", self.seed)
            section = seed.prior_work("new-run", self.seed)
            delivered = json.loads((directory / "tool-delivery.json").read_text())
        self.assertIn(agent_text.render("messages/prior-work.map_heading"), section)
        self.assertIn(agent_text.render("replies/tools.section_map"), section)
        self.assertIn("best n2", section)
        self.assertIn("reasoning: idea 2", section)
        self.assertIn("call compile", section)
        self.assertIn("result: n1 compiles", section)
        self.assertIn("said: all done", section)
        for word in ("gpt", "deepseek", "Sol", "DeepSeek", "finish", "stop", "10%", "budget"):
            self.assertNotIn(word, section)
        self.assertGreaterEqual(delivered["delivered_seq"], 0)
        self.assertIn("n2", delivered["seen_nodes"])

    def test_a_call_to_the_finish_tool_never_reaches_the_digest(self):
        rows = [json.loads(line) for line in (self.seed / "session" / "s.jsonl").read_text().splitlines()]
        call = {"type": "toolCall", "id": "f", "name": "finish", "arguments": {}}
        rows.append({"type": "message", "message": {"role": "assistant", "content": [call]}})
        (self.seed / "session" / "s.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.assertNotIn("finish", seed.session_digest(self.seed))

    def test_unreadable_reasoning_is_left_out(self):
        turns = seed.digest_turns(self.seed)
        self.assertNotIn("reasoning", turns[0])
        self.assertIn("reasoning: idea 2", turns[1])

    def test_a_long_digest_keeps_the_latest_turns_and_counts_the_rest(self):
        full = seed.session_digest(self.seed)
        self.assertNotIn("not shown", full)
        trimmed = seed.session_digest(self.seed, limit=900)
        self.assertIn("said: all done", trimmed)
        self.assertNotIn("Turn 1\n", trimmed)
        self.assertRegex(trimmed, r"^\(\d+ earlier turns are not shown\.\)")
        self.assertLessEqual(len(trimmed), 900 + 80)

    def test_the_digest_cap_is_a_named_constant(self):
        self.assertEqual(seed.DIGEST_CHARS, 24_000)


class RunRefusalTests(unittest.TestCase):
    def test_a_seed_without_a_summary_is_refused_before_anything_starts(self):
        run_module = importlib.import_module("arena.cli.run")
        from arena.engine import ROOT

        theorem = json.loads((ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines()[0])["name"]
        with tempfile.TemporaryDirectory() as tmp:
            options = run_module.RunOptions(
                model=rc.MODELS[0], theorem=theorem, run_id="seed-refusal-test", seed_run=Path(tmp), dry_run=True
            )
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(run_module.run(options), 2)
        self.assertIn("summary.json", error.getvalue())


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SeededRunTests(unittest.TestCase):
    """A run seeded from an ended fake run: the provider sees the prior-work section, the ledger says where it came from."""

    def test_a_seeded_run_starts_from_the_seeds_graph_at_zero_spend(self):
        steps = [cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), *STOP]
        first = FakeRun(steps)
        second = None
        try:
            first.run()
            seed_ledger = first.jsonl("ledger.jsonl")
            second = FakeRun(steps)
            second.run("--seed-run", str(first.directory))
            assert second.result is not None
            self.assertEqual(second.result.returncode, 0, second.result.stderr)
            ledger = second.jsonl("ledger.jsonl")
            seeded = [row for row in ledger if row["kind"] == "seeded"]
            self.assertEqual([row["source_run"] for row in seeded], [first.run_id])
            self.assertEqual(
                [row["candidate_id"] for row in ledger if row["kind"] == "candidate"],
                [row["candidate_id"] for row in seed_ledger if row["kind"] == "candidate"],
            )
            prompt = message_text(second.requests[0]["messages"][-1])
            self.assertIn(agent_text.render("messages/prior-work.heading"), prompt)
            self.assertIn("call read", prompt)
            self.assertIsNone(STOP_TEXT.search(prompt[prompt.index("Prior work.") :]))
            self.assertLess(second.json("cost.json")["spent_usd"], 0.12)  # its own $0.1 run, not the seed's spend added
        finally:
            first.cleanup()
            if second is not None:
                second.cleanup()


@slow
@unittest.skipUnless(PI_AVAILABLE, "pi and the Strata fixture are required")
class SeedProofRunTests(unittest.TestCase):
    """A run seeded from a proof file: the seed is checked on every toolchain first, then Pi starts from it."""

    def test_a_run_starts_from_the_proof_and_a_failing_proof_refuses_to_start(self):
        fixture = FIXTURE.read_text()
        work = Path(tempfile.mkdtemp())
        good, bad = work / "good.lean", work / "bad.lean"
        good.write_text(fixture.replace("intros Hup Hinit", "intro Hup Hinit"))
        bad.write_text(fixture.replace("InitStatesUpdated Hinit", "InitStatesUpdatedNoSuchLemma Hinit"))
        refused = FakeRun([*STOP])
        run = FakeRun([cheap_tool("read", {"view": "map"}, output=SPEND_90_PCT), *STOP])
        try:
            refused.run("--seed-proof", str(bad), guard=False)
            assert refused.result is not None
            self.assertEqual(refused.result.returncode, 2, refused.result.stderr)
            self.assertIn("does not pass every toolchain", refused.result.stderr)
            self.assertEqual(refused.requests, [])  # Pi never started
            run.run("--seed-proof", str(good))
            assert run.result is not None
            self.assertEqual(run.result.returncode, 0, run.result.stderr)
            ledger = run.jsonl("ledger.jsonl")
            self.assertEqual([row["source_proof"] for row in ledger if row["kind"] == "seeded"], [str(good)])
            self.assertEqual([row["origin"] for row in ledger if row["kind"] == "candidate"][:2], ["reference", "seed"])
            prompt = message_text(run.requests[0]["messages"][-1])
            self.assertIn(agent_text.render("messages/prior-work.heading"), prompt)
            self.assertNotIn(agent_text.render("messages/prior-work.digest_heading"), prompt)
            self.assertEqual(run.json("run-config.json")["seed_proof"], str(good))
        finally:
            refused.cleanup()
            run.cleanup()
            good.unlink()
            bad.unlink()
            work.rmdir()


class RequeueSeedTests(unittest.TestCase):
    spec = types.MappingProxyType({"row": "A", "model": SOL, "replicate": 1, "run_id": f"v8-A-{SOL}-r1"})

    def test_the_command_carries_the_seed(self):
        argv = rc.command({**self.spec, "seed_run": "/runs/x"}, 0.5, "high", [])
        self.assertEqual(argv[argv.index("--seed-run") + 1], "/runs/x")
        self.assertNotIn("--seed-run", rc.command(self.spec, 0.5, "high", []))

    def test_a_requeued_run_is_seeded_with_the_stopped_run_and_never_collides(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rc, "RUNS", Path(tmp)):
            results = [{"stop_reason": "usage_limit"}]
            (moved,) = rc.usage_limit_specs([self.spec], results, DEEPSEEK)
            self.assertEqual(moved["seed_run"], str(Path(tmp) / self.spec["run_id"]))
            self.assertEqual(moved["run_id"], f"v8-A-{DEEPSEEK}-r1")
            (Path(tmp) / moved["run_id"]).mkdir()
            (again,) = rc.usage_limit_specs([self.spec], results, DEEPSEEK)
            self.assertEqual(again["run_id"], f"v8-A-{DEEPSEEK}-r1-s1")
            self.assertEqual(again["seed_run"], moved["seed_run"])

    def test_a_row_moved_before_it_started_has_nothing_to_seed(self):
        self.assertNotIn("seed_run", rc.fallback_spec(self.spec, DEEPSEEK))

    def test_never_launched_counts_requeued_runs_in_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = rc.plan("fake", ["A"], [SOL], 1)
            launched = []

            def fake_run(cmd, **_kw):
                launched.append(cmd)
                run_id = cmd[cmd.index("--run-id") + 1]
                (root / run_id).mkdir()
                (root / run_id / "run-config.json").write_text(json.dumps({"packet_sha256": "hash"}))
                if len(launched) == 2:  # the operator stops the campaign during the requeued run
                    os.kill(os.getpid(), signal.SIGINT)
                return SimpleNamespace(returncode=130 if len(launched) == 2 else 0)

            args = campaign_args("fake")
            args.fallback_model = DEEPSEEK
            output = io.StringIO()
            summaries = iter([{"stop_reason": "usage_limit"}, {"stop_reason": "interrupted"}])
            with (
                offline_campaign(root),
                mock.patch("arena.summary.build_summary", side_effect=lambda _d: next(summaries)),
                mock.patch.object(rc, "subscription_room", return_value=(True, "room")),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc._run_campaign(
                    args, ["A"], [SOL], specs, [], LOCK, run_fn=fake_run, console=Console(file=output, width=140)
                )
        self.assertEqual(len(launched), 2)
        self.assertIn("--seed-run", launched[1])
        self.assertIn("1 run(s) stopped, 0 never launched", output.getvalue())


class SeedProofTests(FakeRunCase):
    """`--seed-proof`: the proof becomes a candidate (origin seed), is checked on every toolchain, then focus and current."""

    proof = "theorem t := by\n  exact seed"

    def write(self, text: str | None = None) -> Path:
        path = Path(self.temporary.name) / "seed.lean"
        path.write_text(text or self.proof)
        return path

    def rows(self, kind: str) -> list[dict]:
        return [row for row in campaign.events(self.directory) if row["kind"] == kind]

    def test_a_passing_proof_is_a_seed_candidate_and_the_runs_focus_and_current(self):
        path = self.write()
        started = seed.start_from_proof("T", "logic", path)
        (candidate,) = [row for row in self.rows("candidate") if row["origin"] == "seed"]
        reference = next(row for row in self.rows("candidate") if row["origin"] == "reference")
        self.assertEqual(candidate["parents"], [reference["candidate_id"]])
        self.assertEqual(started["candidate_id"], candidate["candidate_id"])
        (seeded,) = self.rows("seeded")
        self.assertEqual(seeded["source_proof"], str(path))
        self.assertEqual(seeded["best_proxy"], started["best_proxy"])
        self.assertEqual(self.rows("focus")[-1]["proof_id"], candidate["candidate_id"])
        self.assertEqual(self.rows("current")[-1]["candidate_id"], candidate["candidate_id"])
        self.assertEqual(campaign.state("logic")["best"]["candidate"], "#2")
        full = [row for row in self.rows("evaluation") if row["candidate_id"] == candidate["candidate_id"]]
        self.assertEqual([row["mode"] for row in full], ["full"])

    def test_a_proof_failing_a_toolchain_is_refused_and_leaves_no_seed_rows(self):
        for text, version in (("theorem t := by\n  bad", "v1"), ("theorem t := by\n  old", "v2")):
            with self.subTest(version=version), self.assertRaises(ValueError) as caught:
                seed.start_from_proof("T", "logic", self.write(text))
            self.assertIn("does not pass every toolchain", str(caught.exception))
            self.assertIn(version, str(caught.exception))
        self.assertEqual(self.rows("seeded"), [])
        self.assertNotIn("seed", [row["reason"] for row in self.rows("focus")])

    def test_an_unreadable_or_foreign_proof_is_refused_before_any_check(self):
        with self.assertRaises(ValueError) as caught:
            seed.start_from_proof("T", "logic", Path(self.temporary.name) / "missing.lean")
        self.assertIn("cannot be read", str(caught.exception))
        with mock.patch.object(campaign, "validate_proof", side_effect=ValueError("statement modified")):
            with self.assertRaises(ValueError) as caught:
                seed.start_from_proof("T", "logic", self.write())
            self.assertIn("is not a proof of T", str(caught.exception))
        self.assertEqual([row for row in self.rows("candidate") if row["origin"] == "seed"], [])

    def test_the_reference_proof_is_no_seed(self):
        started = seed.start_from_proof("T", "logic", self.write("theorem t := by\n  ref"))
        self.assertTrue(started["reference"])
        self.assertEqual(self.rows("seeded"), [])

    def test_the_first_prompt_gets_the_prior_work_heading_and_map_without_a_digest(self):
        seed.start_from_proof("T", "logic", self.write())
        section = seed.prior_work("logic")
        self.assertIn(agent_text.render("messages/prior-work.heading"), section)
        self.assertIn(agent_text.render("messages/prior-work.map_heading"), section)
        self.assertIn("n2", section)
        self.assertNotIn(agent_text.render("messages/prior-work.digest_heading"), section)
        self.assertIsNone(STOP_TEXT.search(section))


class SeedProofColdVerificationTests(SeedProofTests):
    """A proof checked in a Lean session is only a fast estimate: it must also pass the cold compile."""

    lean_info: ClassVar[dict] = {"path": "session"}

    def test_a_proof_failing_the_cold_verification_is_refused(self):
        cold = {"confirmed": False, "passed": {"v1": True, "v2": False}, "cold_heartbeats": 99}
        with (
            mock.patch.object(campaign, "cold_verify", return_value=cold) as verify,
            self.assertRaises(ValueError) as caught,
        ):
            seed.start_from_proof("T", "logic", self.write())
        verify.assert_called_once()
        self.assertIn("cold verification", str(caught.exception))
        self.assertEqual(self.rows("seeded"), [])

    def test_a_confirmed_proof_is_seeded(self):
        with mock.patch.object(campaign, "cold_verify", return_value={"confirmed": True}) as verify:
            seed.start_from_proof("T", "logic", self.write())
        verify.assert_called_once()
        self.assertEqual(len(self.rows("seeded")), 1)


class SeedProofRunOptionTests(unittest.TestCase):
    def options(self, **kwargs):
        from arena.engine import ROOT

        theorem = json.loads((ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines()[0])["name"]
        run_module = importlib.import_module("arena.cli.run")
        return run_module, run_module.RunOptions(
            model=rc.MODELS[0], theorem=theorem, run_id="seed-proof-option-test", dry_run=True, **kwargs
        )

    def refused(self, **kwargs) -> str:
        run_module, options = self.options(**kwargs)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(run_module.run(options), 2)
        return error.getvalue()

    def test_it_cannot_go_with_the_other_ways_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = Path(tmp) / "p.lean"
            proof.write_text("theorem x : True := by\n  trivial")
            for other in ({"seed_run": Path(tmp)}, {"resume_run": True}, {"preflight": True}):
                with self.subTest(other=other):
                    self.assertIn("--seed-proof", self.refused(seed_proof=proof, **other))

    def test_a_missing_or_foreign_proof_file_is_refused_before_anything_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("cannot be read", self.refused(seed_proof=Path(tmp) / "none.lean"))
            foreign = Path(tmp) / "foreign.lean"
            foreign.write_text("theorem unrelated : True := by\n  trivial")
            self.assertIn("is not a proof of", self.refused(seed_proof=foreign))

    def test_the_flags_exist_with_their_defaults(self):
        _, options = self.options()
        self.assertEqual((options.seed_proof, options.no_golf), (None, False))


class CampaignSeedProofsTests(unittest.TestCase):
    rows = ("Core.InitsUpdatesComm", "Cslib.SKI.parallelReduction_diamond")

    def write_dir(self, root: Path, names=None) -> Path:
        directory = root / "best"
        directory.mkdir()
        lines = [json.dumps({"name": name, "proof": f"theorem {name} := by\n  p\n"}) for name in names or self.rows]
        (directory / "submission.jsonl").write_text("\n".join(lines) + "\n")
        return directory

    def test_proofs_are_read_per_row_and_a_bad_line_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sorted(rc.load_seed_proofs(self.write_dir(Path(tmp)))), sorted(self.rows))
            (Path(tmp) / "best" / "submission.jsonl").write_text('{"name": "A"}\n')
            with self.assertRaises(ValueError) as caught:
                rc.load_seed_proofs(Path(tmp) / "best")
            self.assertIn("line 1", str(caught.exception))

    def test_each_rows_runs_get_the_flag_and_rows_without_a_proof_run_unseeded(self):
        specs = rc.plan("p", [*self.rows, "Other.row"], ["deepseek-v4.1-flash"], 2)
        out = Path("/campaign-out")
        missing = rc.assign_seed_proofs(specs, dict.fromkeys(self.rows, "x"), out)
        self.assertEqual(missing, ["Other.row"])
        for spec in specs:
            argv = rc.command(spec, 0.5, "high", [])
            if spec["row"] == "Other.row":
                self.assertNotIn("--seed-proof", argv)
            else:
                self.assertEqual(
                    argv[argv.index("--seed-proof") + 1], str(out / "seeds" / f"{rc.slug(spec['row'], 200)}.lean")
                )

    def test_a_requeue_seeds_from_the_stopped_run_not_the_proof(self):
        spec = {"row": "A", "model": SOL, "replicate": 1, "run_id": f"v8-A-{SOL}-r1", "seed_proof": "/s/A.lean"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rc, "RUNS", Path(tmp)):
            (moved,) = rc.usage_limit_specs([spec], [{"stop_reason": "usage_limit"}], DEEPSEEK)
        argv = rc.command(moved, 0.5, "high", [])
        self.assertIn("--seed-run", argv)
        self.assertNotIn("--seed-proof", argv)

    def test_the_dry_run_shows_the_flag_notes_missing_rows_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = self.write_dir(Path(tmp), self.rows[:1])
            out = io.StringIO()
            with (
                mock.patch.object(
                    rc.engine, "problem", side_effect=lambda name: {"name": name, "source": name, "version_info": []}
                ),
                mock.patch.object(rc, "RUNS", Path(tmp) / "runs"),
                contextlib.redirect_stdout(out),
            ):
                code = rc.cli_execute(
                    rc.CampaignOptions(
                        prefix="p",
                        rows=",".join(self.rows),
                        models="deepseek-v4.1-flash",
                        replicates=1,
                        limit_usd=0.1,
                        seed_proofs=directory,
                        dry_run=True,
                        plain=True,
                    )
                )
            self.assertEqual(code, 0)
            shown = out.getvalue()
            self.assertEqual(shown.count("--seed-proof"), 1)
            self.assertIn(f"has no proof for {self.rows[1]}", shown)
            self.assertFalse((Path(tmp) / "runs").exists())

    def test_a_missing_directory_is_refused(self):
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(error):
            code = rc.cli_execute(
                rc.CampaignOptions(
                    prefix="p",
                    rows="Core.InitsUpdatesComm",
                    models="deepseek-v4.1-flash",
                    seed_proofs=Path(tmp) / "none",
                    dry_run=True,
                )
            )
        self.assertEqual(code, 2)
        self.assertIn("--seed-proofs", error.getvalue())

    def test_the_campaign_writes_the_seed_files_records_the_settings_and_launches_with_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = rc.plan("fake", ["A", "B"], [SOL], 1)
            proofs = {"A": "theorem a := by\n  p\n"}
            rc.assign_seed_proofs(specs, proofs, root / "fake-campaign")
            launched = []

            def fake_run(cmd, **_kw):
                launched.append(cmd)
                run_id = cmd[cmd.index("--run-id") + 1]
                (root / run_id).mkdir()
                (root / run_id / "run-config.json").write_text(json.dumps({"packet_sha256": "hash"}))
                return SimpleNamespace(returncode=0)

            args = campaign_args("fake")
            args.seed_proofs, args.seed_texts = Path("/seeds"), proofs
            with (
                offline_campaign(root),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                rc._run_campaign(args, ["A", "B"], [SOL], specs, [], LOCK, run_fn=fake_run)
            seeded = root / "fake-campaign" / "seeds" / "A.lean"
            self.assertEqual(seeded.read_text(), "theorem a := by\n  p\n")
            self.assertFalse((root / "fake-campaign" / "seeds" / "B.lean").exists())
            settings = json.loads((root / "fake-campaign" / "campaign.json").read_text())["settings"]
            self.assertEqual((settings["seed_proofs"], settings["seeded_rows"]), ("/seeds", ["A"]))
            by_row = {cmd[cmd.index("--theorem") + 1]: cmd for cmd in launched}
            self.assertEqual(by_row["A"][by_row["A"].index("--seed-proof") + 1], str(seeded))
            self.assertNotIn("--seed-proof", by_row["B"])


if __name__ == "__main__":
    unittest.main()
