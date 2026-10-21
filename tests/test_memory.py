"""Compaction memory is a projection of stored harness state."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arena import campaign, orchestration, reply, tools
from arena.memory import memory, memory_text, original_evidence


class MemoryTests(unittest.TestCase):
    def test_memory_preserves_best_map_used_declarations_reads_and_holes(self):
        state = {
            "best": {
                "id": "n2",
                "price": "tokens 12, heartbeats 34, versions 2/2, score 70.00",
                "proof": "exact Lib.used",
            },
            "map": ["best n2 score 70.0 tokens 12 heartbeats 34"],
            "library": [
                {"name": "Lib.used", "handle": "decl:Lib.used", "module": "Lib", "signature": "Lib.used : X"},
                {"name": "Lib.unused", "handle": "decl:Lib.unused", "module": "Lib", "signature": "Lib.unused : Y"},
            ],
            "reads": [
                {"kind": "read", "handle": "decl:Lib.used", "first": 10, "last": 20},
                {"kind": "read", "handle": "decl:Lib.used", "first": 15, "last": 30},
                {"kind": "read", "handle": "decl:Other", "first": 2, "last": 3},
            ],
            "holes": [{"hole": "n2.h1", "goal": "X"}],
        }
        compacted = memory_text(state)
        seed = memory_text(state, seed=True)
        self.assertIn("exact Lib.used", compacted)
        self.assertIn(state["map"][0], compacted)
        self.assertIn("decl:Lib.used · Lib · Lib.used : X", compacted)
        self.assertNotIn("Lib.unused", compacted)
        self.assertIn("decl:Lib.used lines 10-30", compacted)
        self.assertIn("n2.h1: X", compacted)
        for old_item in ("Allowance:", "idea", "route"):
            self.assertNotIn(old_item, compacted)
        self.assertEqual(compacted.splitlines()[1:], seed.splitlines()[1:])
        self.assertNotEqual(compacted.splitlines()[0], seed.splitlines()[0])

    def test_empty_state_has_explicit_sections(self):
        result = memory_text({})
        self.assertIn("Best node:", result)
        self.assertIn("Map:", result)
        self.assertIn("Read so far:", result)

    def test_v8_resume_recovers_references_not_work(self):
        pin = "sha256:" + "ab" * 32
        proof_id = "cd" * 32
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            with patch.object(campaign, "run_dir", return_value=directory):
                campaign._append(directory, {"kind": "strategy", "actor_id": "sol", "text": "keep the second parent"})
                campaign._append(
                    directory,
                    {
                        "kind": "derivation",
                        "event_id": "der-hidden",
                        "operation_id": "aborted-1",
                        "proof_id": "hidden",
                        "candidate_id": "hidden",
                        "parents": ["proof-main"],
                        "data": {"artifact": "uncommitted"},
                    },
                )
                for index in range(6):
                    campaign._append(
                        directory,
                        {
                            "kind": "derivation",
                            "event_id": f"extra-{index}",
                            "proof_id": "proof-main",
                            "candidate_id": "proof-main",
                            "parents": [],
                        },
                    )
                campaign._append(directory, {"kind": "strategy", "actor_id": "worker", "text": "must not replace strategy"})
                campaign._append(
                    directory,
                    {
                        "type": "delegation",
                        "job_id": "job-done",
                        "activation_id": "act-done",
                        "actor_id": "sol",
                        "worker_actor_id": "worker-a",
                        "worker_session_id": "sess-a",
                        "session_id": "sol-sess",
                        "task": "close the first parent",
                        "hypothesis": "close the first parent",
                        "scope": "proof",
                        "anchor": {"node": "n1"},
                        "tools": [],
                        "state": "active",
                    },
                )
                campaign._append(
                    directory,
                    {
                        "type": "assignment_state",
                        "job_id": "job-done",
                        "activation_id": "act-done",
                        "state": "completed",
                        "occupies_slot": False,
                    },
                )
                campaign._append(
                    directory,
                    {
                        "type": "delegation",
                        "job_id": "job-stop",
                        "activation_id": "act-stop",
                        "actor_id": "sol",
                        "worker_actor_id": "worker-b",
                        "worker_session_id": "sess-b",
                        "session_id": "sol-sess",
                        "task": "try the alternate",
                        "hypothesis": "try the alternate",
                        "scope": "proof",
                        "anchor": {"node": "n2", "step_hashes": [pin]},
                        "tools": [],
                        "state": "active",
                    },
                )
                campaign._append(
                    directory,
                    {
                        "type": "assignment_state",
                        "job_id": "job-stop",
                        "activation_id": "act-stop",
                        "state": "cancelled",
                        "occupies_slot": False,
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "derivation",
                        "event_id": "der-main",
                        "proof_id": "proof-main",
                        "candidate_id": "proof-main",
                        "parents": [],
                        "data": {"relation": "exact", "artifact": "main-body"},
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "derivation",
                        "event_id": "der-alt",
                        "operation_id": "op-alt",
                        "proof_id": "proof-alt",
                        "candidate_id": "proof-alt",
                        "parents": ["proof-main"],
                        "data": {"relation": "exact", "artifact": pin},
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "attempt",
                        "event_id": "att-alt",
                        "proof_id": proof_id,
                        "candidate_id": proof_id,
                        "actor_id": "worker-b",
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "candidate",
                        "event_id": "cand-note",
                        "candidate_id": "proof-alt",
                        "actor_id": "worker-b",
                        "hypothesis": "hole might be Nat",
                        "parents": ["proof-main"],
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "scratch",
                        "phase": "accepted",
                        "state": "accepted",
                        "experiment_id": "exp-1",
                        "actor_id": "worker-a",
                        "run_id": "resume",
                        "context": {"theorem_run": "resume"},
                        "code": "UNIQUE_SNIPPET",
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "scratch",
                        "phase": "outcome",
                        "event_id": "exp-fail",
                        "experiment_id": "exp-1",
                        "actor_id": "worker-a",
                        "outcome": "failure",
                        "promotion": {"state": "not_promoted", "reason": "goal_open"},
                    },
                )
                campaign._append(
                    directory,
                    {
                        "kind": "observation",
                        "event_id": "obs-a",
                        "actor_id": "worker-a",
                        "text": "the first parent stays open",
                        "hypothesis_ref": "job-done",
                    },
                )
                proof_dir = directory / "proofs"
                proof_dir.mkdir()
                (directory / "control.jsonl").write_text(
                    '{"kind":"operation_receipt","status":"committed","operation_id":"op-alt"}\n'
                )
                (proof_dir / f"{proof_id}.lean").write_text("alternate body\n")
                (proof_dir / "escaped.lean").write_text("outside\n")
                campaign._append(
                    directory,
                    {
                        "kind": "observation",
                        "event_id": "obs-shared",
                        "actor_id": "worker-b",
                        "text": "both saw this",
                    },
                )
                reply.set_actor_focus("resume", "proof-main", actor="worker-a")
                reply.set_actor_focus("resume", "proof-b-only", actor="worker-b")
                before = (directory / "ledger.jsonl").read_bytes()
                sol = memory("resume", actor="sol")
                again = memory("resume", actor="sol")
                worker_a = memory("resume", actor="worker-a")
                worker_b = memory("resume", actor="worker-b")
                reloaded = original_evidence("resume", "op-alt")
                main = original_evidence("resume", "der-main")
                experiment = original_evidence("resume", "exp-1")
                proof = original_evidence("resume", proof_id)
                hidden = original_evidence("resume", "der-hidden")
                escaped = original_evidence("resume", "../../../escaped")
                followed = tools.read_tool("T", "resume", {"ref": "op-alt"})
                missing = tools.read_tool("T", "resume", {"ref": "../../../escaped"})
                states = {job["job_id"]: job["state"] for job in orchestration.jobs(directory)["jobs"]}
                self.assertEqual((directory / "ledger.jsonl").read_bytes(), before)
            text = sol["text"]
            self.assertEqual(sol["ok"], True)
            self.assertIn("keep the second parent", text)
            self.assertNotIn("must not replace strategy", text)
            self.assertIn("job-done completed", text)
            self.assertIn("job-stop cancelled", text)
            self.assertNotIn("worker-a proof-main", text)
            self.assertNotIn("proof-b-only", text)
            self.assertNotIn("der-hidden", text)
            self.assertNotIn("uncommitted", text)
            self.assertNotIn("extra-0", text)
            self.assertNotIn("extra-1", text)
            self.assertIn("2 omitted", text)
            self.assertIn("der-main", text)
            self.assertIn("der-alt", text)
            self.assertIn("att-alt", text)
            self.assertIn("exp-1", text)
            self.assertIn("failure goal_open", text)
            self.assertIn("both saw this", text)
            self.assertNotIn("hole might be Nat", text)
            self.assertNotIn("hypothesis job-done", text)
            self.assertNotIn(pin, text)
            self.assertNotIn("UNIQUE_SNIPPET", text)
            self.assertNotIn("alternate body", text)
            self.assertNotIn("voluntary", text.lower())
            self.assertEqual(again["jobs"], sol["jobs"])
            self.assertEqual(states, {"job-done": "completed", "job-stop": "cancelled"})
            self.assertEqual({job["job_id"]: job["state"] for job in sol["jobs"]}, states)
            self.assertIn("job-done completed", worker_a["text"])
            self.assertNotIn("job-stop", worker_a["text"])
            self.assertIn("worker-a proof-main", worker_a["text"])
            self.assertNotIn("proof-b-only", worker_a["text"])
            self.assertIn("hypothesis job-done", worker_a["text"])
            self.assertNotIn("hole might be Nat", worker_a["text"])
            self.assertIn("both saw this", worker_a["text"])
            self.assertIn("job-stop cancelled", worker_b["text"])
            self.assertNotIn("job-done", worker_b["text"])
            self.assertIn("proof-b-only", worker_b["text"])
            self.assertIn("hole might be Nat", worker_b["text"])
            self.assertNotIn("hypothesis job-done", worker_b["text"])
            self.assertEqual(reloaded["event_id"], "der-alt")
            self.assertEqual(reloaded["data"]["artifact"], pin)
            self.assertEqual(main["data"]["artifact"], "main-body")
            self.assertIsNone(hidden)
            self.assertIsNone(escaped)
            self.assertEqual(experiment["code"], "UNIQUE_SNIPPET")
            self.assertEqual(proof["text"], "alternate body\n")
            self.assertTrue(followed["ok"])
            self.assertEqual(followed["items"][0]["record"]["event_id"], "der-alt")
            self.assertFalse(missing["ok"])


if __name__ == "__main__":
    unittest.main()
