from types import SimpleNamespace
from unittest import mock

from arena import campaign


def _node(i, route, score):
    return SimpleNamespace(proof_id=f"p{i}", route=route, score=score)


def _run(after_scores, routes_after):
    nodes = [_node(0, "r1", 0.5), _node(1, "r2", 0.7)]
    nodes += [_node(10 + i, r, s) for i, (r, s) in enumerate(zip(routes_after, after_scores, strict=True))]
    history = [{"kind": "route", "proof_id": n.proof_id} for n in nodes[:2]]
    history.append({"kind": "stall"})
    history += [{"kind": "route", "proof_id": n.proof_id} for n in nodes[2:]]
    graph = SimpleNamespace(nodes=nodes)
    with (
        mock.patch.object(campaign, "run_dir", lambda _: None),
        mock.patch.object(campaign, "events", lambda _: history),
        mock.patch.object(campaign, "_proof_reader", lambda _: None),
        mock.patch.object(campaign.Graph, "from_history", lambda *_: graph),
    ):
        return campaign.stall_due("x"), campaign.route_tally("x")


def test_stall_due_after_n_same_route_tries_without_new_best():
    n = campaign.STALL_RESTART_TRIES
    due, tally = _run([0.6] * n, ["r2"] * n)
    assert due and "r2:" in tally
    assert _run([0.6] * (n - 1), ["r2"] * (n - 1))[0] is False
    assert _run([0.6] * (n - 1) + [0.8], ["r2"] * n)[0] is False
    assert _run([0.6] * n, ["r2"] * (n - 1) + ["r3"])[0] is False
