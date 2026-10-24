"""Smoke tests: card delivery is once per version and race-free, workers see peers' cards, plateau."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import campaign, orchestration, text
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

    def test_a_receiver_that_saw_a_card_gets_only_the_fields_changed_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "worker-b", "c1", focus="peer focus", asks="first ask")
            bucket: dict = {}
            with patch.object(campaign, "run_dir", return_value=directory):
                first = "\n".join(proof_reply._card_lines("run-1", "worker-a", bucket))
                _save(directory, "worker-b", "c2", asks="second ask")
                _save(directory, "worker-b", "c3", focus="n9 shape")
                later = "\n".join(proof_reply._card_lines("run-1", "worker-a", bucket))
            self.assertIn("peer focus", first)
            self.assertIn("second ask", later)
            self.assertIn("n9 shape", later)
            self.assertNotIn("peer focus", later)

    def test_a_changed_field_shows_only_its_new_sentences_and_a_long_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "worker-b", "c1", asks="Try the split. Merge the cases.")
            bucket: dict = {}
            with patch.object(campaign, "run_dir", return_value=directory):
                proof_reply._card_lines("run-1", "worker-a", bucket)
                _save(directory, "worker-b", "c2", asks="Try the split. Merge the cases. Fold the last step.")
                later = "\n".join(proof_reply._card_lines("run-1", "worker-a", bucket))
                _save(directory, "worker-b", "c3", asks="Try the split. Merge the cases. Fold the last step.", focus="n2")
                only_focus = "\n".join(proof_reply._card_lines("run-1", "worker-a", bucket))
            self.assertIn("asks: Fold the last step.", later)
            self.assertNotIn("Try the split", later)
            self.assertNotIn("asks:", only_focus)
            self.assertIn("focus: n2", only_focus)
            limit = text.numbers()["card_field_chars"]
            long = _save(directory, "worker-b", "c4", focus="x" * (limit + 1))
            self.assertFalse(long["ok"])
            self.assertIn(f"{limit + 1} characters", long["hint"])
            self.assertEqual(orchestration.current_cards(directory)["worker-b"]["version"], 3)

    def test_a_card_with_only_focus_and_asks_reaches_another_actor_and_an_old_row_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            old = {"type": "card", "actor_id": "worker-c", "job_id": None, "label": "job3", "version": 1,
                   "fields": {"focus": "old focus", "best": "n1", "held": "h", "failed": "f", "ideas": "i"},
                   "changed": ["focus", "best", "held", "failed", "ideas"]}
            with (directory / "ledger.jsonl").open("a") as ledger:
                ledger.write(json.dumps(old) + "\n")
            saved = _save(directory, "worker-b", "c1", focus="new focus", asks="need a split", best="ignored")
            self.assertTrue(saved["ok"])
            self.assertEqual(orchestration.current_cards(directory)["worker-b"]["fields"],
                             {"focus": "new focus", "asks": "need a split"})
            with patch.object(campaign, "run_dir", return_value=directory):
                shown = "\n".join(proof_reply._card_lines("run-1", "worker-a", {}))
            self.assertIn("focus: new focus", shown)
            self.assertIn("asks: need a split", shown)
            self.assertIn("focus: old focus", shown)
            for removed in ("best:", "held:", "failed:", "ideas:"):
                self.assertNotIn(removed, shown)

    def test_a_map_is_sent_again_only_when_its_step_table_moves(self):
        def key(*steps, node="n1"):
            return proof_reply._map_key({"best": {"node": node}, "effort": [
                {"step": step, "at_stake": points, "tokens": 5} for step, points in steps]})

        first = key(("s1", 3.0), ("s2", 1.0))
        self.assertFalse(proof_reply._map_changed(first, key(("s1", 3.4), ("s2", 1.0), node="n7")))
        self.assertTrue(proof_reply._map_changed(first, key(("s1", 4.2), ("s2", 1.0))))
        self.assertTrue(proof_reply._map_changed(first, key(("s1", 3.0), ("s3", 1.0))))
        self.assertTrue(proof_reply._map_changed(None, first))

    def test_an_orchestrator_message_stays_open_on_the_worker_until_a_card_changes(self):
        rows = [{"type": "job_message", "job_id": "j1", "text": "try the n7 shape", "disposition": "sent"}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(orchestration, "_history", side_effect=lambda _d: list(rows)), \
                patch.object(campaign, "run_dir", return_value=Path(tmp)), \
                patch.object(orchestration, "worker_job_labels", return_value={"worker-a": "job1"}), \
                patch.object(orchestration, "resolve_job", return_value="j1"):
            self.assertEqual(orchestration.open_ask(Path(tmp), "j1"), "try the n7 shape")
            self.assertEqual(proof_reply._open_ask_note("run-1", "worker-a"),
                             ["Orchestrator asked: try the n7 shape"])
            rows.append({"type": "card", "job_id": "j1", "changed": []})
            self.assertIsNotNone(orchestration.open_ask(Path(tmp), "j1"))
            rows.append({"type": "card", "job_id": "j1", "changed": ["focus"]})
            self.assertIsNone(orchestration.open_ask(Path(tmp), "j1"))
            self.assertEqual(proof_reply._open_ask_note("run-1", "worker-a"), [])

    def test_a_worker_sees_the_orchestrators_and_peers_cards_but_not_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _seed_parent(directory)
            _save(directory, "sol", "c1", asks="try the n7 shape")
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
                "Shortest closed proof: n1 100 tokens (5 HB); cheapest: n3 2 HB (900 tokens). "
                "Proof structures you have not tried remain: rework the best proof a new way, starting from its costliest step."
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
