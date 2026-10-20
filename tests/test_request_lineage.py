"""Offline request replacement and original-stop preservation."""

from arena import run_control


def test_unsent_lineage_preserves_transport_history_and_stop(tmp_path):
    identity = {"run_id": "r", "actor_id": "sol", "session_id": "s"}
    directory = tmp_path / "sent"
    run_control.prepare_request(directory, {**identity, "request_id": "old"})
    run_control.begin_dispatch(directory, {**identity, "request_id": "old", "attempt_id": "sent"}, lambda: None)
    with run_control.control_lock(directory):
        run_control._append_control(directory, {"kind": "run_stop", "reason": "operator_interrupt"})
    refused = run_control.begin_dispatch(
        directory, {**identity, "request_id": "old", "attempt_id": "refused"}, lambda: None,
    )
    assert refused["sent"] == "unsent"
    assert not run_control.prepare_request(directory, {
        **identity, "request_id": "unsafe", "lineage_of": "old",
    })["ok"]
    run_control.settle_usage(directory, {
        **identity, "settlement_id": "late", "covered_request_ids": ["old"],
        "state": "known", "amount": "3", "usage": {"cost": {"total": "3"}},
    })
    state = run_control.read_state(directory)
    assert state["total"] == "3"
    assert state["stop_reason"] == "operator_interrupt"
    assert state["stops"] == ["operator_interrupt"]

    directory = tmp_path / "never-sent"
    run_control.prepare_request(directory, {**identity, "request_id": "old"})
    assert not run_control.prepare_request(directory, {
        **identity, "actor_id": "worker", "request_id": "foreign", "lineage_of": "old",
    })["ok"]
    child = {**identity, "request_id": "new", "lineage_of": "old"}
    assert run_control.prepare_request(directory, child)["ok"]
    assert run_control.prepare_request(directory, child)["reused"]
    late_parent = run_control.begin_dispatch(
        directory, {**identity, "request_id": "old", "attempt_id": "too-late"},
        lambda: (_ for _ in ()).throw(AssertionError("superseded request sent")),
    )
    assert late_parent["reason"] == "request_replaced"
