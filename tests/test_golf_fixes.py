"""Smoke tests for the golf-run fixes: floor claims, open worker requests, the receipt's tools, island acceptance."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import orchestration, team_reply


def _node(node_id, route, score, tokens, heartbeats, versions=(True, True, True)):
    return SimpleNamespace(id=node_id, proof_id=f"p-{node_id}", status="closed", route=route, score=score,
                           verified=True, origin="model", tokens=tokens, heartbeats=heartbeats,
                           versions={f"v{i}": ok for i, ok in enumerate(versions)}, attempts=[{"job_id": "j1"}])


def _card(job_id, version, ts, **fields):
    return {"actor_id": f"w-{job_id}", "job_id": job_id, "version": version, "ts": ts, "fields": fields}


class GolfFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        (self.directory / "run-config.json").write_text(json.dumps({"golf": True, "cards": True}))
        self.addCleanup(self.tmp.cleanup)

    def test_floor_claim_reply_and_receipt_tools(self):
        self.assertTrue(orchestration.card_claims_floor({"best": "63 is the floor"}))
        self.assertFalse(orchestration.card_claims_floor({"best": "not the floor yet"}))
        self.assertIn("patterns", orchestration.worker_tools(self.directory))
        self.assertIn("`patterns`", team_reply.render("card", {"ok": True, "version": 2, "floor": True}, self.directory))
        self.assertNotIn("patterns", team_reply.render("card", {"ok": True, "version": 2}, self.directory))

    def test_asks_and_floor_push_stay_until_a_job_starts(self):
        nodes = {"p1": _node("n1", "a", 90.0, 100, 50), "p2": _node("n2", "b", 88.0, 90, 70)}
        cards = {"w": _card("j1", 3, 10.0, asks="try the b shape", best="heartbeat floor confirmed")}
        delegations = [{"job_id": "j1", "ts": 1.0}]
        with patch.object(orchestration, "current_cards", lambda d: cards), \
                patch.object(orchestration, "_delegations", lambda d: delegations), \
                patch.object(orchestration, "job_labels", lambda d: {"j1": "job1"}), \
                patch.object(orchestration, "_job_rows", lambda d, j: delegations), \
                patch.object(orchestration, "proof_nodes", lambda d: nodes), \
                patch.object(orchestration, "island_status", lambda d, j: {"route": "a"}):
            shown = "\n".join(team_reply.open_requests(self.directory))
            self.assertIn("asks: try the b shape", shown)
            self.assertIn("n2", shown)  # a different shape's node, named at runtime
            self.assertNotIn("n1", shown.split("floor_options")[0].split("Candidates")[-1])
            delegations.append({"job_id": "j2", "ts": 20.0})
            with patch.object(orchestration, "_job_rows", lambda d, j: [r for r in delegations if r["job_id"] == j]):
                self.assertEqual(team_reply.open_requests(self.directory), [])

    def test_open_requests_and_cards_ride_in_context_and_leave_the_await_text(self):
        protocol = importlib.import_module("arena.cli.protocol")

        with patch.object(protocol, "run_dir", return_value=self.directory), \
                patch.object(team_reply, "open_requests", return_value=["## Open", "asks"]), \
                patch.object(protocol.tool_reply, "card_lines", return_value=["## Cards", "card"]):
            result = protocol._with_text("await_results", {"ok": True, "wake_reason": "no_pending_work"}, "run-1")
        self.assertNotIn("asks", result["text"])
        self.assertNotIn("card", result["text"])
        self.assertEqual(result["context"]["sections"], [["## Open", "asks"], ["## Cards", "card"]])
        self.assertEqual(result["context"]["kinds"], ["open_requests", "cards"])

    def test_floor_claim_naming_an_uncompiled_construct_is_flagged_unmeasured(self):
        (self.directory / "proofs").mkdir()
        (self.directory / "proofs" / "p.lean").write_text("theorem t : True := by exact List.length_pos_iff.mpr h")
        claim = {"best": "`List.of_mem_zip` costs ≥14 tokens, so 63 is the floor; `length_pos_iff` is fine"}
        self.assertTrue(orchestration.card_claims_floor({"best": "this direction cannot work"}))
        self.assertEqual(orchestration.unmeasured_constructs(self.directory, claim), ["List.of_mem_zip"])
        self.assertIn("`List.of_mem_zip`", team_reply.render(
            "card", {"ok": True, "version": 2, "floor": True, "unmeasured": ["List.of_mem_zip"]}, self.directory))

    def test_island_best_needs_every_toolchain(self):
        nodes = {"p1": _node("n1", "a", None, 100, 40, versions=(True, False, True)),
                 "p2": _node("n2", "a", 80.0, 100, 60)}
        with patch.object(orchestration, "proof_nodes", lambda d: nodes), \
                patch.object(orchestration, "_job_original", lambda d, j: {"objective": "heartbeats"}), \
                patch.object(orchestration, "events", lambda d: [{"versions": ["a", "b", "c"]}]):
            self.assertEqual(orchestration.island_status(self.directory, "j1")["node"], "n2")


if __name__ == "__main__":
    unittest.main()
