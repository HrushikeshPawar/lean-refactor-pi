"""Smoke tests: card delivery is once per version and race-free, workers see peers' cards, stale-card nudges, plateau."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import campaign, orchestration
from arena import reply as proof_reply

_PROOF = "theorem demo : True ∧ True := by\n  trivial\n  trivial\n"


def _seed_parent(directory: Path) -> None:
    (directory / "run-config.json").write_text(json.dumps({"theorem": "demo", "model": "gpt-6-sol"}))
    (directory / "proofs").mkdir(parents=True)
    (directory / "proofs" / "parent.lean").write_text(_PROOF)
    (directory / "ledger.jsonl").write_text(
        json.dumps({"kind": "candidate", "candidate_id": "parent", "origin": "reference"}) + "\n"
    )


def _save(directory: Path, actor: str, op: str, **fields):
    return orchestration.save_card(directory, operation_id=op, job_id=None, run_id="run-1", actor_id=actor,
                                   session_id="session", fields=fields)


def _node(node_id, route, score, job_id=None, status="closed", tokens=100, heartbeats=5):
    return SimpleNamespace(id=node_id, proof_id=f"p-{node_id}", status=status, route=route, score=score,
                           verified=True, origin="model", tokens=tokens, heartbeats=heartbeats,
                           attempts=[{"job_id": job_id}] if job_id else [])


class CardDeliveryTests(unittest.TestCase):
    def test_parallel_replies_deliver_a_card_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "worker-a", "c1", focus="s4 route")
            real_cards = orchestration.current_cards

            def slow_cards(path):
                time.sleep(0.05)  # widen the window in which two processes could both read cards_seen
                return real_cards(path)

            results: list[list[str]] = []
            with patch.object(campaign, "run_dir", return_value=directory), \
                    patch.object(orchestration, "current_cards", slow_cards), \
                    patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol"}):
                threads = [threading.Thread(target=lambda: results.append(proof_reply.card_lines("run-1")))
                           for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            self.assertEqual(len(results), 4)
            self.assertEqual(sum(1 for lines in results if lines), 1)

    def test_a_worker_sees_the_orchestrators_and_peers_cards_but_not_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "sol", "c1", ideas="try the n7 shape")
            _save(directory, "worker-a", "c2", focus="own focus")
            _save(directory, "worker-b", "c3", focus="peer focus")
            with patch.object(campaign, "run_dir", return_value=directory):
                lines = proof_reply._card_lines("run-1", "worker-a", {})
            text_lines = "\n".join(lines)
            self.assertIn("orchestrator card v1", text_lines)
            self.assertIn("worker-b card v1", text_lines)
            self.assertIn("peer focus", text_lines)
            self.assertNotIn("worker-a card", text_lines)
            self.assertNotIn("own focus", text_lines)

    def test_a_worker_is_told_once_when_its_best_node_is_newer_than_its_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "worker-a", "c1", focus="s4 route")
            node = _node("n83", "s4", 80.0, job_id="job-a")
            # The node was saved after the card, so it is a new best for this worker.
            times = {node.proof_id: time.time() + 3600}
            bucket: dict = {}
            with patch.object(campaign, "run_dir", return_value=directory), \
                    patch.object(orchestration, "worker_job_labels", return_value={"worker-a": "job1"}), \
                    patch.object(orchestration, "resolve_job", return_value="job-a"), \
                    patch.object(orchestration, "proof_nodes", return_value={node.proof_id: node}), \
                    patch.object(proof_reply, "_first_saved_times", return_value=times):
                first = proof_reply._card_stale_note("run-1", "worker-a", bucket)
                again = proof_reply._card_stale_note("run-1", "worker-a", bucket)
            self.assertEqual(first, ["Your card predates your nodes n83; update it with what they showed."])
            self.assertEqual(again, [])

    def test_a_worker_is_reminded_at_most_once_per_five_minutes_and_names_deferred_nodes_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "worker-a", "c1", focus="s4 route")
            first_node = _node("n83", "s4", 80.0, job_id="job-a")
            second_node = _node("n84", "s4", 90.0, job_id="job-a")
            second_node.proof_id = "p-n84"
            nodes = {first_node.proof_id: first_node}
            times = {"p-n83": time.time() + 3600, "p-n84": time.time() + 7200}
            clock = {"now": 1_000_000.0}
            bucket: dict = {}
            with patch.object(campaign, "run_dir", return_value=directory), \
                    patch.object(orchestration, "worker_job_labels", return_value={"worker-a": "job1"}), \
                    patch.object(orchestration, "resolve_job", return_value="job-a"), \
                    patch.object(orchestration, "proof_nodes", return_value=nodes), \
                    patch.object(proof_reply, "_first_saved_times", return_value=times), \
                    patch.object(proof_reply.time, "time", side_effect=lambda: clock["now"]):
                first = proof_reply._card_stale_note("run-1", "worker-a", bucket)
                nodes[second_node.proof_id] = second_node
                clock["now"] += 60
                within = proof_reply._card_stale_note("run-1", "worker-a", bucket)
                clock["now"] += 241
                later = proof_reply._card_stale_note("run-1", "worker-a", bucket)
            self.assertEqual(first, ["Your card predates your nodes n83; update it with what they showed."])
            self.assertEqual(within, [])
            self.assertEqual(later, ["Your card predates your nodes n84; update it with what they showed."])

    def test_the_orchestrator_hears_of_a_plateau_once_with_the_other_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            now = time.time()
            history = [{"ts": now - 3600, "kind": "candidate", "candidate_id": "parent"}]
            best = _node("n1", "r1", 80.0)
            nodes = {
                "p-n1": best,
                "p-n2": _node("n2", "r2", 70.0, tokens=500, heartbeats=9),
                "p-n3": _node("n3", "r3", 60.0, tokens=900, heartbeats=2),
            }
            nodes["p-n1"].origin = "reference"
            bucket: dict = {}
            with patch.object(campaign, "run_dir", return_value=directory), \
                    patch.object(campaign, "events", return_value=history), \
                    patch.object(orchestration, "run_best", return_value=best), \
                    patch.object(orchestration, "proof_nodes", return_value=nodes), \
                    patch.object(proof_reply, "_plateau_costly", return_value=None):
                first = proof_reply._plateau_note("run-1", "sol", bucket)
                again = proof_reply._plateau_note("run-1", "sol", bucket)
                worker = proof_reply._plateau_note("run-1", "worker-a", {})
            self.assertEqual(first, [
                "The run best n1 80.0 has not gained 1.0 points in 10 minutes. "
                "Other families with closed proofs: r2 best n2 70.0 (500 tok, 9 HB); r3 best n3 60.0 (900 tok, 2 HB). "
                "Shortest closed proof: n1 100 tokens (5 HB); cheapest: n3 2 HB (900 tokens)."
            ])
            self.assertEqual(again, [])
            self.assertEqual(worker, [])

    def test_the_plateau_names_the_run_best_costliest_steps_from_cached_profiles(self):
        proof = "theorem demo : True ∧ True := by\n  constructor\n  trivial\n  trivial\n"
        node = SimpleNamespace(id="n1", proof_id="p-n1", proof_text=proof, tokens=40, heartbeats=300, origin="model")
        entries = [
            {"depth": 0, "proof_line": 2, "hb": 10, "self_hb": 10, "kind": "tactic"},
            {"depth": 0, "proof_line": 3, "hb": 200, "self_hb": 200, "kind": "tactic"},
            {"depth": 0, "proof_line": 4, "hb": 90, "self_hb": 90, "kind": "tactic"},
        ]
        history = [{"kind": "profile", "proof_id": "p-n1", "theorem": "demo",
                    "result": {"entries": entries, "measured_total": 300}}]
        line = proof_reply._plateau_costly(history, node)
        self.assertEqual(line, "Costliest steps of n1: s2 1 tok 200 HB; s3 1 tok 90 HB; s1 1 tok 10 HB.")
        self.assertIsNone(proof_reply._plateau_costly([{"kind": "candidate", "theorem": "demo"}], node))


if __name__ == "__main__":
    unittest.main()
