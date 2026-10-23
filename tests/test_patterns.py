"""Strategy cards (--cards): ranking, position buckets, tool gating, the worker packet push, the protocol call."""

import importlib
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from arena import context, orchestration, patterns, pi_rpc
from arena.steps import split_steps
from tests.test_text import ROWS

protocol = importlib.import_module("arena.cli.protocol")  # `arena.cli.protocol` the attribute is a function

PROOF = "theorem t (p q : Prop) (h : p ∧ q) : q ∧ p := by\n  obtain ⟨hp, hq⟩ := h\n  simp only [and_comm]\n  exact ⟨hq, hp⟩"


class RankingTests(unittest.TestCase):
    def test_features_use_the_cards_tag_vocabulary(self):
        found = patterns.features("obtain ⟨a, b⟩ := h\nsimp only [foo] at h\nsimp_all\nexact?")
        self.assertTrue({"obtain", "anonymous-constructor", "simp only", "simp", "simp_all", "exact?"} <= found)
        self.assertNotIn("simp", patterns.features("simp_all"))  # a different tactic, not the bare word
        self.assertNotIn("rw", patterns.features("exact foo"))

    def test_rank_orders_by_tag_overlap_then_confidence(self):
        step = "rcases h with ⟨a, b⟩\nobtain ⟨c, d⟩ := a"
        ranked = patterns.rank(step, 5)
        self.assertTrue(ranked)
        found = patterns.features(step)
        overlaps = [len(found & set(card["tags"])) for card in ranked]
        self.assertEqual(overlaps, sorted(overlaps, reverse=True))
        confidence = {"high": 2, "medium": 1, "low": 0}
        for first, second, a, b in zip(ranked, ranked[1:], overlaps, overlaps[1:]):
            if a == b:
                self.assertGreaterEqual(confidence[first["effect"]["confidence"]], confidence[second["effect"]["confidence"]])

    def test_a_step_with_no_known_feature_gets_no_card(self):
        self.assertEqual(patterns.rank("zzz qqq", 5), [])
        self.assertIn("No reference card", patterns.render_cards("zzz qqq", "middle"))

    def test_position_buckets_match_the_mining_rule(self):
        self.assertEqual(patterns.position(0, 1), "opening")
        self.assertEqual(patterns.position(0, 10), "opening")
        self.assertEqual(patterns.position(1, 10), "opening")  # centre 0.15 < 0.2
        self.assertEqual(patterns.position(2, 10), "middle")
        self.assertEqual(patterns.position(7, 10), "middle")
        self.assertEqual(patterns.position(8, 10), "closing")
        self.assertEqual(patterns.position(9, 10), "closing")
        self.assertEqual(patterns.position(2, 3), "closing")  # last step

    def test_rendered_card_shows_only_the_heartbeat_direction_of_its_position(self):
        card = {"title": "T", "when": "W", "how": "H", "before": "B", "after": "A",
                "effect": {"tokens": "down", "confidence": "high", "note": "",
                           "heartbeats": {"opening": "down", "middle": "up", "closing": "mixed"}}}
        opening, closing = patterns.render_card(card, "opening"), patterns.render_card(card, "closing")
        for body in (opening, closing):
            for part in ("T", "When: W", "How: H", "Before:\nB", "After:\nA", "Tokens: usually lower"):
                self.assertIn(part, body)
            self.assertEqual(body.count("Heartbeats"), 1)
        self.assertIn("opening of a proof: usually lower", opening)
        self.assertNotIn("usually higher", opening)
        self.assertIn("closing of a proof: mixed", closing)

    def test_costliest_step_follows_the_price_table(self):
        node = SimpleNamespace(id="n1", proof_text=PROOF)
        rows = [{"id": "s1", "pts_if_gone": 1.0, "tokens": 9}, {"id": "s2", "pts_if_gone": 3.0, "tokens": 5},
                {"id": "s3", "pts_if_gone": None, "tokens": 50}]
        with patch("arena.campaign.price_table", return_value={"rows": rows}):
            step, body, where = patterns.costliest_step("t", "run", node)
        self.assertEqual((step, where), ("s2", "middle"))
        self.assertIn("simp only", body)


class GoalAwareTests(unittest.TestCase):
    GOAL = "⊢ ∑ i ∈ Finset.range n, i = n * (n - 1) / 2"

    def test_goal_constants_rank_a_card_the_tactics_do_not_reach(self):
        self.assertEqual(patterns.rank("zzz", 3), [])
        ranked = patterns.rank("zzz", 3, self.GOAL)
        self.assertEqual(ranked[0]["id"], "S58-finset-sum-closers")
        self.assertTrue(patterns.goal_hits(ranked[0], "Finset.range n |>.sum id"))  # method form matches too

    def test_a_card_whose_move_the_step_already_makes_is_dropped(self):
        ids = {card["id"] for card in patterns.rank("grind", 99)}
        self.assertNotIn("S09-grind-closer", ids)  # recommends grind, which the step already is
        self.assertIn("S10-grind-to-explicit", ids)  # replaces grind, which the step has
        self.assertNotIn("S10-grind-to-explicit", {card["id"] for card in patterns.rank("omega", 99)})  # no grind to replace

    def test_cards_are_not_repeated_for_one_actor_and_run_dir(self):
        with tempfile.TemporaryDirectory() as name, patch.dict("os.environ", {"ARENA_ACTOR_ID": "w1"}):
            directory = Path(name)
            first = patterns.render_fresh("exact foo", "middle", self.GOAL, directory, "w1")
            again = patterns.render_fresh("exact foo", "middle", self.GOAL, directory, "w1")
            other = patterns.render_fresh("exact foo", "middle", self.GOAL, directory, "w2")
            self.assertIn("Close sum/product identities", first)
            self.assertNotIn("Close sum/product identities", again)
            self.assertIn("Close sum/product identities", other)
            for _ in range(5):
                last = patterns.render_fresh("exact foo", "middle", self.GOAL, directory, "w1")
            self.assertIn("already seen every card", last)

    def test_new_tight_proof_cards_are_in_the_bank_and_compile(self):
        cards = {card["id"]: card for card in patterns.load_cards()}
        for ident in ("S71-drop-helper-reclose-dependents", "S72-sibling-fact-without-premise",
                      "S73-helper-must-pay"):
            self.assertEqual(set(cards[ident]["verified"].values()), {"pass"})
            self.assertEqual(set(cards[ident]["at"]), set(patterns.POSITIONS))
        self.assertIn("At the closing of this proof", patterns.render_card(cards["S73-helper-must-pay"], "closing"))


class GatingTests(unittest.TestCase):
    def launch(self, **config):
        with tempfile.TemporaryDirectory() as name:
            Path(name, "run-config.json").write_text(json.dumps({"theorem": "demo", **config}))
            return pi_rpc.worker_launch(Path(name), run_id="r", worker_actor_id="w", worker_session_id="s",
                                        job_id="j", activation_id="a", anchor={"node": "n1"})

    def test_worker_tools_are_unchanged_without_cards(self):
        launch = self.launch()
        self.assertEqual(launch["tools"], list(pi_rpc.WORKER_TOOLS))
        self.assertNotIn("patterns", launch["argv"][launch["argv"].index("--tools") + 1])
        self.assertNotIn("ARENA_CARDS", launch["env"])

    def test_a_cards_run_adds_the_tool_for_workers(self):
        launch = self.launch(cards=True)
        self.assertEqual(launch["tools"], [*pi_rpc.WORKER_TOOLS, "patterns"])
        self.assertEqual(launch["argv"][launch["argv"].index("--tools") + 1], ",".join(launch["tools"]))
        self.assertEqual(launch["env"]["ARENA_CARDS"], "1")

    def test_extension_registers_the_tool_only_with_the_cards_env(self):
        source = Path(pi_rpc.__file__).parents[1].joinpath("packages/arena-pi/extensions/arena.ts").read_text()
        self.assertIn('if (process.env.ARENA_CARDS === "1") {', source)
        self.assertEqual(source.count('name: "patterns"'), 1)

    def test_run_config_flag(self):
        with tempfile.TemporaryDirectory() as name:
            Path(name, "run-config.json").write_text(json.dumps({"theorem": "demo"}))
            self.assertFalse(orchestration.is_cards(Path(name)))
            Path(name, "run-config.json").write_text(json.dumps({"theorem": "demo", "cards": True}))
            self.assertTrue(orchestration.is_cards(Path(name)))

    def test_the_tool_is_not_in_any_role_list(self):
        schemas = json.loads(Path(pi_rpc.__file__).parents[1].joinpath("agent-text/tool-schemas.json").read_text())
        self.assertTrue(schemas["tools"]["patterns"]["handler"])
        self.assertFalse(any("patterns" in tools for tools in schemas["roles"].values()))


class PacketTests(unittest.TestCase):
    def packet(self, cards=None):
        steps = split_steps(PROOF)
        node = SimpleNamespace(id="n1", proof_text=PROOF, steps=steps, holes=[])
        return context.worker_packet(ROWS["ski"], task="try", anchor={"node": "n1"}, node=node, cards=cards)

    def test_packet_is_unchanged_without_cards(self):
        self.assertNotIn("Reference cards", self.packet())
        self.assertEqual(self.packet(), self.packet(None))

    def test_packet_pushes_the_cards_of_the_costliest_step(self):
        body = patterns.render_cards("simp only [and_comm]", "middle", 3)
        packet = self.packet(("s2", body))
        self.assertIn("Reference cards for the costliest step (step s2)", packet)
        self.assertIn(body.splitlines()[0], packet)
        self.assertLess(packet.index("Reference cards"), packet.index("Anchored proof"))

    def test_worker_packet_builder_takes_the_price_table_step(self):
        steps = split_steps(PROOF)
        node = SimpleNamespace(id="n1", proof_text=PROOF, steps=steps, holes=[], proof_id="p")
        graph = SimpleNamespace(nodes=[node])
        rows = [{"id": "s1", "pts_if_gone": 1.0, "tokens": 5}, {"id": "s2", "pts_if_gone": 4.0, "tokens": 5}]
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name, "run")
            directory.mkdir()
            directory.joinpath("run-config.json").write_text(json.dumps({"theorem": ROWS["ski"], "cards": True}))
            # Other test modules replace `orchestration._worker_packet` for the whole session: load a private copy.
            spec = importlib.util.spec_from_file_location("orchestration_unpatched", orchestration.__file__)
            real = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(real)
            stored = {"anchor": {"node": "n1"}, "scope": "proof", "task": "try"}
            with (
                patch("arena.graph.Graph.from_history", return_value=graph),
                patch.object(real, "events", return_value=[]),
                patch.object(real.run_control, "committed_operation_ids", return_value=set()),
                patch("arena.campaign._proof_reader"),
                patch("arena.campaign.price_table", return_value={"rows": rows}),
            ):
                packet = real._worker_packet(directory, stored)
                directory.joinpath("run-config.json").write_text(json.dumps({"theorem": ROWS["ski"]}))
                plain = real._worker_packet(directory, stored)
        self.assertIn("(step s2)", packet)
        self.assertNotIn("Reference cards", plain)


class ProtocolTests(unittest.TestCase):
    def call(self, request: dict, run_id="run") -> dict:
        with tempfile.TemporaryDirectory() as name:
            file = Path(name, "request.json")
            file.write_text(json.dumps(request))
            with patch("arena.campaign.run_dir", return_value=Path(name, "run")):  # keep the seen-cards memory out of runs/
                return self.run_protocol(file, run_id)

    def run_protocol(self, file, run_id):
        return protocol.run(SimpleNamespace(action="patterns", request_file=file, theorem="t", run_id=run_id))

    def test_snippet_session(self):
        reply = self.call({"text": "obtain ⟨a, b⟩ := h", "position": "closing"})
        self.assertTrue(reply["ok"])
        self.assertIn("Heartbeats at the closing of a proof", reply["text"])
        self.assertLessEqual(reply["text"].count("\nBefore:\n"), 3)

    def test_node_and_step_session(self):
        node = SimpleNamespace(id="n1", proof_text=PROOF)
        with patch("arena.tools._node", return_value=node):
            reply = self.call({"node": "n1", "step": "s2"})
        self.assertTrue(reply["ok"])
        self.assertIn("simp", reply["text"].lower())
        self.assertIn("Heartbeats at the middle", reply["text"])
        with patch("arena.tools._node", return_value=node):
            self.assertFalse(self.call({"node": "n1", "step": "s99"})["ok"])

    def test_bad_requests_are_refused(self):
        for request in ({}, {"node": "n1"}, {"text": "x", "node": "n1", "step": "s1"}, {"text": "x", "position": "end"}):
            self.assertFalse(self.call(request)["ok"], request)

    def test_tool_text_passes_neutrality(self):
        from arena import text

        for key in ("tools/patterns.description", "packet/cards-team", "packet/cards-worker"):
            self.assertTrue(text.render(key))


class RunFlagTests(unittest.TestCase):
    def test_cards_flag_is_off_by_default_and_accepted_by_a_dry_run(self):
        import contextlib
        import io

        run_cli = importlib.import_module("arena.cli.run")
        self.assertFalse(run_cli.RunOptions(model="m", theorem="t", run_id="r").cards)
        options = run_cli.RunOptions(model="gpt-6.1-sol", theorem="Core.InitsUpdatesComm", run_id="cards-dry-run-test",
                                     limit_usd=1.0, cards=True, dry_run=True, plain=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_cli.run(options), 0)


if __name__ == "__main__":
    unittest.main()
