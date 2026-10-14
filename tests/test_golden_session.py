"""Golden session: one realistic multi-turn run through every v7 tool form, on the Lean session path.

The first real v7 run broke on what no test drove: session-checked compiles from turn 3 onward
(every one returned internal_error) and a background full check that was never kicked.
"""

import json
import re
import unittest

from tests.pi_support import PI_AVAILABLE, FakeRun, message_text
from tests.slow import slow
from tests.test_runner import FIXTURE, SPEND_90_PCT, START_TOOLS, STOP_TEXT, cheap_tool, offered_tools

# The fixture's update_none branch, closed two ways; the second is the text the sketch's hole is filled with.
NONE_CASE = "exact Exists.intro σ'' ⟨InitStatesUpdated Hinit, Hinit, UpdateStates.update_none⟩"
FILLED = "exact ⟨σ'', InitStatesUpdated Hinit, Hinit, UpdateStates.update_none⟩"

# Ids a node name must never take in delivered text: stored proof hashes, candidate labels, probe labels.
LEAKED_ID = re.compile(r"\b[0-9a-f]{64}\b|#\d|\bp\d+\b")
PYTHON_NONE = re.compile(r"\bNone\b")
# Model thinking time before the finish call; the same window the runner's background-check test gives.
FINISH_THINKING_MS = 150_000


def script() -> tuple[list[tuple[str, dict, str | None]], int]:
    """(tool, arguments, node the call must file) per turn, and the index of the turn that spends into the final tenth."""
    fixture = FIXTURE.read_text()
    variant = fixture.replace("intros Hup Hinit", "intro Hup Hinit")
    broken = fixture.replace("InitStatesUpdated Hinit", "InitStatesUpdatedNoSuchLemma Hinit")
    sketch = fixture.replace(NONE_CASE, "sorry")
    tokens_only = fixture.replace("intros Hup Hinit", "intro Hup\n  intro Hinit")
    assert len({fixture, variant, broken, sketch, tokens_only}) == 5
    turns: list[tuple[str, dict, str | None]] = [
        ("read", {"view": "map"}, None),
        ("read", {"node": "n1", "view": "source"}, None),
        ("search", {"queries": ["InitStatesUpdated", "UpdateStates"], "kind": "name"}, None),
        ("compile", {"drafts": [fixture], "check": "lean"}, "n2"),
        ("compile", {"base": "n2", "drafts": [variant, broken], "check": "lean"}, "n3 n4"),
        ("compile", {"splice": {"base": "n2", "steps": "s1", "text": "rintro Hup Hinit"}}, "n5"),
        ("compile", {"drafts": [sketch]}, "n6"),
        ("compile", {"fill": {"hole": "n6.h1", "text": FILLED}}, "n7"),
        ("compile", {"merge": {"base": "n7", "take": [{"from": "n5", "step": "s1"}]}}, "n8"),
        ("goal", {"node": "n2", "line": 13}, None),
        ("goal", {"node": "n2", "line": 13, "try": [FILLED, "simp"]}, None),
        ("read", {"hole": "n6.h1"}, None),
        ("read", {"handle": "InitStatesUpdated"}, None),  # no decl: prefix: a bad handle
        ("read", {"handle": "decl:InitStatesUpdated"}, None),
        ("read", {"node": "n3", "view": "diff", "against": "n2"}, None),
        ("read", {"node": "n8", "view": "prices"}, None),
        ("compile", {"drafts": [tokens_only], "check": "tokens"}, None),
        ("read", {"node": "n2", "view": "outline"}, None),  # this turn's output spends 90% of the limit
        ("finish", {}, None),
    ]
    return turns, len(turns) - 2


@slow
@unittest.skipUnless(PI_AVAILABLE and FIXTURE.exists(), "pi and the Strata fixture are required")
class GoldenSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        turns, cls.spend_turn = script()
        steps = [
            cheap_tool(name, arguments, **({"output": SPEND_90_PCT} if index == cls.spend_turn else {}))
            for index, (name, arguments, _) in enumerate(turns)
        ]
        # The model thinks before it calls finish, as a real one does: only a full check kicked in the background
        # (not the closing drain) can land in that window. The fake answers faster than Lean checks.
        steps[-1]["delay_ms"] = FINISH_THINKING_MS
        cls.turns = turns
        cls.run_ = FakeRun([*steps, {"text": "done"}], session=True, timeout=1800)
        try:
            cls.run_.run(guard=False)  # every guard condition is asserted below, each on its own
            cls.requests = cls.run_.requests
            cls.journal = cls.run_.jsonl("trace-journal.jsonl")
            cls.ledger = cls.run_.jsonl("ledger.jsonl")
            cls.summary = cls.run_.json("summary.json") if (cls.run_.directory / "summary.json").exists() else {}
            cls.problems = cls.run_.health_problems()
            cls.tool_errors_log = (cls.run_.directory / "tool-errors.log").exists()
        finally:
            cls.run_.cleanup()

    def results(self) -> list[dict]:
        return [row for row in self.journal if row.get("kind") == "tool_result"]

    def delivered(self) -> list[tuple[str, str]]:
        """Everything the arena wrote for the model: tool results (with their footers) and runner messages."""
        texts = [
            (
                f"{row.get('name')} {row.get('tool_call_id')}",
                f"{row.get('delivered_text') or ''}\n{row.get('footer') or ''}",
            )
            for row in self.results()
        ]
        if self.requests:
            texts += [
                (f"user message {index}", message_text(message))
                for index, message in enumerate(self.requests[-1]["messages"])
                if message["role"] == "user"
            ]
        return texts

    def test_every_scripted_turn_reached_the_model_and_finish_ended_the_run(self):
        self.assertEqual(len(self.requests), len(self.turns), self.run_.stdout[-2000:])
        self.assertEqual([row.get("name") for row in self.results()], [name for name, _, _ in self.turns])
        self.assertEqual(self.summary.get("stop_reason"), "finished", self.run_.stdout[-2000:])

    def test_no_tool_result_is_an_internal_error(self):
        self.assertEqual(self.problems, [])
        for row in self.results():
            with self.subTest(tool=row.get("name"), call=row.get("tool_call_id")):
                self.assertNotIn("internal_error", json.dumps(row, ensure_ascii=False), row.get("delivered_text"))

    def test_every_filing_compile_filed_its_node_in_order(self):
        compiles = [row for row in self.results() if row.get("name") == "compile"]
        expected = [node for name, _, node in self.turns if name == "compile"]
        self.assertEqual(len(compiles), len(expected))
        filed = []
        for row, nodes in zip(compiles, expected, strict=True):
            items = ((row.get("result") or {}).get("details") or {}).get("items") or []
            got = [item.get("node") for item in items]
            with self.subTest(call=row.get("tool_call_id"), expected=nodes):
                if nodes is None:
                    self.assertEqual([node for node in got if node], [], row.get("delivered_text"))
                else:
                    self.assertEqual(got, nodes.split(), row.get("delivered_text"))
                    filed += [node for node in got if node]
        numbers = [int(node[1:]) for node in filed if re.fullmatch(r"n\d+", node or "")]
        self.assertEqual(numbers, sorted(set(numbers)), filed)

    def test_delivered_text_names_nodes_only_as_nk(self):
        for where, text in self.delivered():
            with self.subTest(where=where):
                self.assertEqual(sorted(set(LEAKED_ID.findall(text))), [], text[:3000])

    def test_delivered_text_never_shows_python_none(self):
        for where, text in self.delivered():
            with self.subTest(where=where):
                lines = [line for line in text.splitlines() if PYTHON_NONE.search(line)]
                self.assertEqual(lines, [])

    def test_a_full_check_ran_before_the_final_model_response(self):
        full = [
            row
            for row in self.ledger
            if row.get("kind") == "evaluation" and (row.get("result") or {}).get("mode") == "full"
        ]
        self.assertTrue(full, self.run_.stdout[-1500:])
        responses = [row["ts"] for row in self.journal if row.get("kind") == "response"]
        self.assertLess(full[0]["ts"], responses[-1] / 1000, "the full check waited for the closing drain")

    def test_finish_is_unmentioned_and_unoffered_until_the_final_tenth(self):
        before, after = self.requests[: self.spend_turn + 1], self.requests[self.spend_turn + 1 :]
        self.assertTrue(after, "no request was sent inside the final tenth")
        for request in before:
            with self.subTest(request=request["index"]):
                self.assertEqual(set(offered_tools(request)), START_TOOLS)
                for definition in request["tool_definitions"]:
                    self.assertNotRegex(json.dumps(definition, ensure_ascii=False), STOP_TEXT, definition["name"])
                for message in request["messages"]:
                    if message["role"] != "assistant":
                        self.assertNotRegex(message_text(message), STOP_TEXT, message["role"])
        for request in after:
            with self.subTest(request=request["index"]):
                self.assertIn("finish", offered_tools(request))

    def test_no_tool_errors_log(self):
        self.assertFalse(self.tool_errors_log)


if __name__ == "__main__":
    unittest.main()
