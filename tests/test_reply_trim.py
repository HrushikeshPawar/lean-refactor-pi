from types import SimpleNamespace

from arena import campaign, reply, text, tools

GOALS = "\n".join(f"case c{i}\nh : Nat\n⊢ G{i}" for i in range(5))


def test_goal_blocks_split_one_goal_per_target():
    blocks = reply.goal_blocks(GOALS)
    assert len(blocks) == 5 and blocks[2].startswith("case c2") and blocks[2].endswith("⊢ G2")


def _lines(monkeypatch, errors):
    monkeypatch.setattr(tools, "all_errors", lambda *a: (errors, False))
    monkeypatch.setattr(reply, "deduplicate_diagnostics", lambda _r, _n, e: e)
    monkeypatch.setattr(tools, "_statement_context", lambda _p: set())
    monkeypatch.setattr(tools, "_binder_hypotheses", lambda *_a: set())
    node = SimpleNamespace(proof_text="theorem t : True := by\n  simp", id="n1")
    return tools._error_lines("T", "run", node, None, {})[0]


def test_failure_reply_puts_syntax_error_first_caps_and_dedupes_goals(monkeypatch):
    errors = [
        {"id": "e1", "line": 2, "message": "unsolved goals\n" + GOALS, "goal": GOALS},
        {"id": "e2", "line": 3, "message": "unsolved goals\n" + GOALS + " ", "goal": GOALS},
        {"id": "e3", "line": 4, "message": "unexpected identifier", "goal": None},
    ]
    body = "\n".join(_lines(monkeypatch, errors))
    assert body.index("e3 line 4") < body.index("e1 line 2")
    assert "G2" in body and "G3" not in body
    assert "+2 more goals." in body
    assert body.count("⊢ G0") == 1
    assert "Same goals as e1." in body


def _attach(monkeypatch, best):
    state = {}
    monkeypatch.setattr(reply, "_load", lambda _r: state)
    monkeypatch.setattr(reply, "_write_actor", lambda *a: None)
    monkeypatch.setattr(reply, "current_actor", lambda: "sol")
    monkeypatch.setattr(campaign, "state", lambda _r: {"updates": []})
    data = {"best": {"node": best, "score": 1.0, "tokens": 5, "heartbeats": 6}, "archive": [], "recent": [{"node": "n9"}]}
    monkeypatch.setattr(campaign, "map_view", lambda _r, _focus=None: data)
    return state, lambda: reply.attach_context("run", {}, include_map=True)


def _map(result: dict) -> list[str]:
    """The search map lines a reply carries in its context (none when it carries no map section)."""
    head = text.render("replies/tools.section_map")
    return next((section for section in result["context"]["sections"] if section[:1] == [head]), [])


def test_compile_reply_carries_the_map_only_for_a_new_best(monkeypatch):
    state, call = _attach(monkeypatch, "n3")
    first = call()
    assert _map(first) and text.render("replies/tools.map_shapes").split("\n")[0] not in "\n".join(_map(first))
    assert "Latest nodes" not in "\n".join(_map(first))
    assert not _map(call())
    monkeypatch.setattr(campaign, "map_view", lambda _r, _focus=None: {"best": {"node": "n4"}, "archive": [], "recent": []})
    assert _map(call())


def test_salvage_bookkeeping_updates_are_not_delivered(monkeypatch):
    state, _ = _attach(monkeypatch, "n3")
    monkeypatch.setattr(
        campaign,
        "state",
        lambda _r: {"updates": [{"seq": 1, "text": "n5: compiling part", "quiet": True}, {"seq": 2, "text": "n6 checked"}]},
    )
    monkeypatch.setattr(reply, "_commit_delivery", lambda *a: {"operation_id": "o", "event_ids": ["1", "2"]})
    monkeypatch.setattr(reply, "node_authors", lambda _r: {})
    result = reply.attach_context("run", {})
    shown = "\n".join(line for section in result["context"]["sections"] for line in section)
    assert "n6 checked" in shown and "compiling part" not in shown


def test_text_only_nudge_says_not_to_paste_proofs():
    nudge = text.render("messages/continuation.turn_ended_with_text", facts="")
    assert "made no tool call" in nudge and "paste proofs" in nudge
    assert "not tried remain" in nudge and "hill climbing" in nudge
