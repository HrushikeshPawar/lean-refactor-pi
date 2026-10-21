from types import SimpleNamespace
from unittest import mock

from arena import campaign


def _node(i, route, score):
    return SimpleNamespace(proof_id=f"p{i}", route=route, score=score)


def _tally(after_scores, routes_after):
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
        mock.patch.object(campaign, "committed_operation_ids", lambda _: set()),
        mock.patch.object(campaign.Graph, "from_history", lambda *_a, **_k: graph),
    ):
        return campaign.route_tally("x")


def test_route_tally_is_information_after_enough_same_route_variants():
    t = campaign.ROUTE_TALLY_MIN
    assert "r2:" in _tally([0.6] * t, ["r2"] * t)
    assert _tally([0.6] * (t - 1), ["r2"] * (t - 1)) is None
