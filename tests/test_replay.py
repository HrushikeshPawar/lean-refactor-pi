"""Replay splits a request the way the extension does, and rebuilds a turn from the journal."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena.campaign import _append
from arena.replay import (
    V7_SECTIONS,
    ReplayError,
    created_nodes,
    load_run,
    node_turn,
    render_turn,
    request_parts,
    rerender_v7,
    split_request,
)
from arena.traces import call_context, read_journal
from tests.pi_support import PI_AVAILABLE, FakeRun
from tests.slow import slow
from tests.test_runner import FIXTURE, cheap_tool

FIXTURES = Path(__file__).parent / "fixtures" / "replay"
ROOT = Path(__file__).resolve().parents[1]
STOP_TEXT = re.compile(r"\b(?:finish\w*|stop\w*|threshold\w*|tenth|end(?:s|ing)? the run)\b", re.I)
A = "aaaaaaaabbbbbbbb"
B = "1234abcd5678ef90"
C = "cccccccceeeeeeee"
D = "ddddddddffffffff"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write(
    directory: Path,
    journal: list[dict],
    ledger: list[dict] | None = None,
    cost: list[dict] | None = None,
    config: dict | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "trace-journal.jsonl").write_text("".join(json.dumps(row) + "\n" for row in journal))
    (directory / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in (ledger or [])))
    if cost is not None:
        (directory / "cost-ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in cost))
    if config is not None:
        (directory / "run-config.json").write_text(json.dumps(config))


def _payload() -> dict:
    return json.loads((FIXTURES / "request-payload.json").read_text())


def _request(request_id: str, turn_ts: int, post: dict | None = None) -> dict:
    return {"kind": "request", "id": request_id, "ts": turn_ts, "post_hook": post if post is not None else _payload()}


class ReplayTests(unittest.TestCase):
    def test_split_request_matches_the_shared_fixture(self):
        payload = _payload()
        expected = json.loads((FIXTURES / "request-split.json").read_text())
        parts = split_request(payload)
        for key in ("system", "skill", "tools", "packet"):
            self.assertEqual(parts[key], expected[key])
            self.assertEqual(_sha(parts[key]), expected["sha256"][key])
        self.assertEqual(parts["messages"], expected["messages"])
        blank = split_request(None)
        self.assertEqual([blank[key] for key in ("system", "skill", "tools", "packet")], ["", "", "", ""])
        self.assertEqual(split_request({"messages": [{"role": "user", "content": "only"}]})["packet"], "only")

    def test_v6_journal_is_numbered_and_split_from_the_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write(
                directory,
                [_request("r1", 1500), _request("r2", 5000, {"messages": [{"role": "user", "content": "later"}]})],
            )
            loaded = load_run(str(directory))
            self.assertEqual([item.number for item in loaded.turns], [1, 2])
            parts = request_parts(loaded.turns[0], directory)
            expected = json.loads((FIXTURES / "request-split.json").read_text())
            self.assertEqual(parts["system"], expected["system"])
            self.assertEqual(parts["packet"], expected["packet"])
            rendered = dict(render_turn(loaded, 1))
            self.assertEqual(rendered["Tools"], "compile: Compile a draft.")
            self.assertIn("<cwd>", rendered["Messages"])
            self.assertNotIn("<cwd>", rendered["System prompt"])

    def test_blob_parts_are_read_and_a_missing_blob_names_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            packet = "blob packet"
            digest = _sha(packet)
            request = _request("r1", 1500)
            request["blobs"] = {"packet": digest}
            _write(directory, [request])
            blobs = directory / "blobs"
            blobs.mkdir()
            (blobs / digest).write_text(packet)
            loaded = load_run(str(directory))
            parts = request_parts(loaded.turns[0], directory)
            self.assertEqual(parts["packet"], packet)
            self.assertEqual(parts["messages"], _payload()["messages"])
            (blobs / digest).unlink()
            with self.assertRaises(ReplayError) as caught:
                request_parts(loaded.turns[0], directory)
            self.assertIn(digest, str(caught.exception))

    def test_node_turn_joins_by_tool_call_or_by_time_and_orders_a_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_sample(directory)
            loaded = load_run(str(directory))
            self.assertEqual(node_turn(loaded, "n2"), 1)
            self.assertEqual(node_turn(loaded, "#2"), 1)
            self.assertEqual(node_turn(loaded, "1234abcd"), 1)
            self.assertEqual(node_turn(loaded, "n4"), 2)
            self.assertEqual(created_nodes(loaded, 1), ["n2", "n3"])
            self.assertEqual(created_nodes(loaded, 2), ["n4"])
            with self.assertRaises(ReplayError) as caught:
                node_turn(loaded, "n1")
            self.assertIn("n1", str(caught.exception))

    def test_trimmed_tool_result_renders_the_diff_against_untrimmed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            footer = "budget: 0.01 of 1.00 spent · 99% left"
            journal = [
                _request("r1", 1500),
                {
                    "kind": "tool_result",
                    "id": "r1",
                    "ts": 3000,
                    "name": "compile",
                    "trimmed": True,
                    "text": "alpha\nbeta\ngamma",
                    "delivered_text": "alpha\ngamma",
                    "footer": footer,
                    "result": {
                        "content": [
                            {"type": "text", "text": "alpha"},
                            {"type": "text", "text": "gamma"},
                            {"type": "text", "text": footer},
                        ]
                    },
                },
                _request("r2", 5000, {"messages": []}),
                {
                    "kind": "response",
                    "id": "r2",
                    "ts": 5500,
                    "text": "done",
                    "content": [{"type": "thinking", "thinking": "because"}],
                    "usage": {"input": 3},
                    "settled_usd": 0.02,
                },
            ]
            _write(directory, journal)
            rendered = dict(render_turn(load_run(str(directory)), 2))
            self.assertIn("-beta", rendered["Tool result compile"])
            self.assertIn("because", rendered["Thinking"])
            self.assertIn("settled_usd=0.02", rendered["Usage"])

    def test_v7_render_shows_nodes_by_graph_id_and_hides_finish_until_the_final_tenth(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_sample(directory)
            loaded = load_run(str(directory))
            early = dict(rerender_v7(loaded, 2))
            late = dict(rerender_v7(loaded, 3))
            self.assertIn("Packet", early)
            self.assertIn("n2 closed", early["Nodes"])
            self.assertIn("tokens=11", early["Nodes"])
            self.assertIn("heartbeats=4", early["Nodes"])
            self.assertIn("compat=1/1", early["Nodes"])
            self.assertIn("score=2.5", early["Nodes"])
            self.assertIn("parent=n1", early["Nodes"])
            self.assertNotIn("#1", early["Nodes"])
            self.assertIn("compile:", early["Tools"])
            self.assertNotIn("finish:", early["Tools"])
            self.assertNotRegex(early["Tools"], STOP_TEXT)
            self.assertNotRegex(early["Nodes"], STOP_TEXT)
            self.assertIn("finish:", late["Tools"])
            self.assertRegex(late["Tools"], STOP_TEXT)

    def test_v7_map_shows_the_best_node_and_only_nodes_created_before_the_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_sample(directory)
            loaded = load_run(str(directory))
            title = [name for name, _ in rerender_v7(loaded, 2)][list(V7_SECTIONS).index("map")]
            early = dict(rerender_v7(loaded, 2))[title]
            late = dict(rerender_v7(loaded, 3))[title]
            best = early.splitlines()[0]
            self.assertRegex(best, r"\bn2\b.*\b2\.5\b.*\b11\b.*\b4\b")
            self.assertNotRegex(early, r"\bn4\b")
            self.assertRegex(late, r"\bn4\b")

    def test_encoded_raw_payload_hashes_to_the_stored_sha256(self):
        first = b'{"n":1}'
        second = b'{"n":2}'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            journal = [
                {
                    "kind": "request",
                    "id": "r1",
                    "turn": 1,
                    "ts": 1000,
                    "post_hook_encoding": "text",
                    "post_hook": first.decode(),
                    "post_hook_sha256": _sha(first.decode()),
                },
                {
                    "kind": "request",
                    "id": "r2",
                    "turn": 2,
                    "ts": 2000,
                    "post_hook_encoding": "delta",
                    "post_hook_prefix": 5,
                    "post_hook_suffix": 1,
                    "post_hook": "2",
                    "post_hook_sha256": _sha(second.decode()),
                },
            ]
            _write(directory, journal)
            loaded = load_run(str(directory))
            rendered = render_turn(loaded, 2, raw=True)
            self.assertEqual(len(rendered), 1)
            self.assertEqual(_sha(rendered[0][1]), journal[1]["post_hook_sha256"])
            proc = subprocess.run(
                [sys.executable, "-m", "arena.cli", "replay", str(directory), "--raw", "--turn", "2"],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(hashlib.sha256(proc.stdout).hexdigest(), journal[1]["post_hook_sha256"])

    def test_cli_rejects_bad_flags_and_a_run_with_no_journal(self):
        both = subprocess.run(
            [sys.executable, "-m", "arena.cli", "replay", "missing-run", "--turn", "1", "--node", "n1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(both.returncode, 2)
        self.assertNotIn("predates the journal", both.stderr)
        unknown = subprocess.run(
            [sys.executable, "-m", "arena.cli", "replay", "missing-run", "--render", "v6"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("v7", unknown.stderr)
        combined = subprocess.run(
            [sys.executable, "-m", "arena.cli", "replay", "missing-run", "--raw", "--render", "v7", "--turn", "1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(combined.returncode, 2)
        with tempfile.TemporaryDirectory() as tmp:
            missing = subprocess.run(
                [sys.executable, "-m", "arena.cli", "replay", tmp],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("predates the journal", missing.stderr)
        self.assertIn(tmp, missing.stderr)

    def _write_sample(self, directory: Path) -> None:
        journal = [
            _request("r1", 1500),
            {"kind": "tool_call", "id": "r1", "ts": 2000, "tool_call_id": "t1", "name": "compile", "args": {}},
            {
                "kind": "tool_result",
                "id": "r1",
                "ts": 3000,
                "tool_call_id": "t1",
                "name": "compile",
                "result": {"content": [{"type": "text", "text": "ok"}]},
            },
            _request("r2", 5000),
            {"kind": "tool_call", "id": "r2", "ts": 6000, "tool_call_id": "t9", "name": "compile", "args": {}},
            {
                "kind": "tool_result",
                "id": "r2",
                "ts": 7000,
                "tool_call_id": "t9",
                "name": "compile",
                "result": {"content": [{"type": "text", "text": "ok"}]},
            },
            _request("r3", 10000, {"messages": []}),
        ]
        passed = {"compat": {"v1": {"passed": True}}, "tokens": 11, "heartbeat": 4, "metrics": {"proxy": 2.5}}
        ledger = [
            {"kind": "init", "theorem": "Not.A.Real.Theorem", "ts": 0.5},
            {"kind": "candidate", "candidate_id": A, "origin": "reference", "parents": [], "ts": 1.0},
            {"kind": "candidate", "candidate_id": B, "origin": "model", "parents": [A], "ts": 2.5},
            {"kind": "candidate", "candidate_id": C, "origin": "model", "parents": [A], "ts": 2.6},
            {"kind": "evaluation", "candidate_id": B, "mode": "primary", "result": passed, "ts": 2.8},
            {
                "kind": "candidate",
                "candidate_id": D,
                "origin": "model",
                "parents": [B],
                "tool_call_id": "t9",
                "ts": 8.5,
            },
        ]
        cost = [
            {"kind": "settle", "id": "r1", "ts": 4000, "usd": 0.05, "spent_usd": 0.05},
            {"kind": "settle", "id": "r2", "ts": 8000, "usd": 0.90, "spent_usd": 0.95},
        ]
        _write(directory, journal, ledger, cost, {"theorem": "Not.A.Real.Theorem", "limit_usd": 1.0})


class CallContextTests(unittest.TestCase):
    def test_append_uses_the_event_tool_call_and_adds_request_and_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            env = {"ARENA_TOOL_CALL_ID": "from-env", "ARENA_REQUEST_ID": "req-1", "ARENA_TURN": "3"}
            with patch.dict(os.environ, env):
                _append(directory, {"kind": "candidate", "tool_call_id": "from-event"})
            row = json.loads((directory / "ledger.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["tool_call_id"], "from-event")
            self.assertEqual(row["request_id"], "req-1")
            self.assertEqual(row["turn"], 3)
            self.assertIsInstance(row["ts"], float)
        with patch.dict(os.environ, {"ARENA_TOOL_CALL_ID": "", "ARENA_REQUEST_ID": "", "ARENA_TURN": ""}):
            self.assertEqual(call_context(), {})


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class ReplaySeamTests(unittest.TestCase):
    def test_fake_run_records_blobs_turns_and_tool_call_ids(self):
        run = FakeRun(
            [cheap_tool("compile", {"drafts": [FIXTURE.read_text()], "check": "lean"}), {"text": "done"}],
            timeout=300,
        )
        try:
            run.run()
            journal = [
                json.loads(line) for line in (run.directory / "trace-journal.jsonl").read_text().splitlines() if line
            ]
            expanded = read_journal(run.directory / "trace-journal.jsonl")
            requests = [row for row in expanded if row.get("kind") == "request"]
            self.assertTrue(requests)
            blob_dir = run.directory / "blobs"
            hashes = set()
            for request in requests:
                blobs = request["blobs"]
                self.assertEqual(set(blobs), {"system", "skill", "tools", "packet"})
                for digest in blobs.values():
                    body = (blob_dir / digest).read_bytes()
                    self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
                    hashes.add(digest)
            self.assertEqual({path.name for path in blob_dir.iterdir() if path.is_file()}, hashes)
            for key in ("system", "skill", "tools", "packet"):
                self.assertEqual(len({request["blobs"][key] for request in requests}), 1)
            self.assertEqual(len(hashes), 4)
            cost = run.jsonl("cost-ledger.jsonl")
            for row in journal + cost:
                self.assertIn("turn", row)
                if row.get("turn"):
                    self.assertIn("request_id", row)
            model = [
                row
                for row in run.jsonl("ledger.jsonl")
                if row.get("kind") == "candidate" and row.get("origin") == "model"
            ]
            self.assertTrue(model)
            for row in model:
                self.assertTrue(row.get("tool_call_id"))
        finally:
            run.cleanup()
