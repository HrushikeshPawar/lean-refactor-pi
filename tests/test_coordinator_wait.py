"""Private run-coordinator transport, without a provider or Lean process."""

import json
import os
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from arena import coordinator, orchestration
from tests.test_orchestration import _HeldChild, _seed_parent


@pytest.fixture(autouse=True)
def _stub_worker_packet():
    # The fixture theorem "demo" is not a catalogued problem; its packet render has its own test in test_text.
    with patch.object(orchestration, "_worker_packet", return_value="WORKER PACKET"):
        yield


def test_protocol_process_waits_for_owned_worker():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        _seed_parent(directory)
        child = _HeldChild()
        receipt = orchestration.delegate(
            directory, operation_id="coordinator-worker", run_id="run-1", actor_id="sol",
            session_id="sol-session", task="try a route", scope="proof", anchor={"node": "n1"},
            open_child=lambda _launch: child,
        )
        activation = receipt["activation_id"]
        try:
            with patch.object(orchestration, "reconcile", return_value={"status": "running", "generation": "fixture"}), coordinator.Coordinator(directory) as owner:
                registered = threading.Event()
                original_wait = orchestration._interest.wait

                def registered_wait(*args, **kwargs):
                    registered.set()
                    return original_wait(*args, **kwargs)

                with patch.object(orchestration._interest, "wait", registered_wait):
                    code = """
import importlib.util, json, sys
from pathlib import Path
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location('wait_protocol_test', 'arena/cli/protocol.py')
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)
protocol.run_dir = lambda _run_id: Path(sys.argv[1])
args = SimpleNamespace(action='await_results',run_id='run-1',request_file=None)
print(json.dumps(protocol.run(args)))
"""
                    process = subprocess.Popen(
                        ["uv", "run", "--no-sync", "python", "-c", code, str(directory)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, start_new_session=True,
                    )
                    try:
                        assert registered.wait(2), "remote wait did not register with the run owner"
                        assert process.poll() is None, "client ignored the locally owned live worker"
                        command = json.loads(bytes(child.written).split(b"\n")[0])["id"]
                        child._chunks.put(json.dumps({"type": "response", "id": command,
                                                       "command": "prompt", "success": True,
                                                       "data": {"disposition": "handled"}}).encode() + b"\n")
                        stdout, stderr = process.communicate(timeout=3)
                        assert process.returncode == 0, stderr
                        result = json.loads(stdout)
                        assert result["wake_reason"] == "settled"
                        assert result["events"][0]["activation_id"] == activation
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.communicate(timeout=2)
                orchestration.join_activation(activation, timeout=1)
                for _ in range(3):
                    no_work = coordinator.await_results(directory, actor_id="sol")
                    if no_work["wake_reason"] == "no_pending_work":
                        break
                assert no_work["wake_reason"] == "no_pending_work"
                next_child = _HeldChild()
                next_job = orchestration.delegate(
                    directory, operation_id="coordinator-cancel-wait", run_id="run-1", actor_id="sol",
                    session_id="sol-session", task="independent route", scope="proof", anchor={"node": "n1"},
                    open_child=lambda _launch: next_child,
                )
                registered.clear()
                try:
                    with patch.object(orchestration._interest, "wait", registered_wait):
                        pending = subprocess.Popen(
                            ["uv", "run", "--no-sync", "python", "-c", code, str(directory)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
                        )
                        try:
                            assert registered.wait(2)
                            os.killpg(pending.pid, signal.SIGKILL)
                            pending.communicate(timeout=2)
                            owner.close()
                            owner.close()
                            assert not owner._clients, "disconnected request retained a wait handler"
                        finally:
                            if pending.poll() is None:
                                os.killpg(pending.pid, signal.SIGKILL)
                                pending.communicate(timeout=2)
                finally:
                    next_child.shutdown()
                    orchestration.join_activation(next_job["activation_id"], timeout=1)
            assert coordinator.await_results(directory, actor_id="sol")["reason"] == "coordinator_unavailable"
        finally:
            child.shutdown()
            orchestration.join_activation(activation, timeout=1)


def test_v8_management_bridge():
    import importlib

    protocol = importlib.import_module("arena.cli.protocol")

    opens = []

    def open_child(_launch):
        child = _HeldChild()
        opens.append(child)
        return child

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        _seed_parent(directory)
        request = directory / "request.json"
        body = {"task": "try a route", "scope": "proof", "at": {"node": "n1"}, "actor_id": "worker"}
        try:
            with (
                patch.object(orchestration, "reconcile", return_value={"status": "running", "generation": "fixture"}),
                coordinator.Coordinator(directory, open_child=open_child),
                patch.object(protocol, "run_dir", lambda _run_id: directory),
                patch.dict(os.environ, {"ARENA_ACTOR_ID": "sol", "ARENA_SESSION_ID": "sol-session", "ARENA_TOOL_CALL_ID": "call-1"}),
            ):
                request.write_text(json.dumps(body))
                first = protocol.run(SimpleNamespace(action="delegate", run_id="run-1", request_file=request))
                second = protocol.run(SimpleNamespace(action="delegate", run_id="run-1", request_file=request))
                request.write_text(json.dumps({**body, "task": "different route"}))
                conflict = protocol.run(SimpleNamespace(action="delegate", run_id="run-1", request_file=request))
                request.write_text(json.dumps({"task": "missing anchor", "scope": "proof"}))
                missing = protocol.run(SimpleNamespace(action="delegate", run_id="run-1", request_file=request))
                listed = protocol.run(SimpleNamespace(action="jobs", run_id="run-1", request_file=None))
                request.write_text(json.dumps({"cursor": "9"}))
                cursed = protocol.run(SimpleNamespace(action="jobs", run_id="run-1", request_file=request))
                os.environ["ARENA_TOOL_CALL_ID"] = "call-cancel"
                request.write_text(json.dumps({"job_id": first.get("job_id"), "actor_id": "worker"}))
                cancelled = protocol.run(SimpleNamespace(action="cancel", run_id="run-1", request_file=request))
                forged = coordinator.submit(directory, {
                    "action": "delegate", "actor_id": "worker", "session_id": "worker", "operation_id": "forged",
                    "run_id": "run-1", "task": "steal", "scope": "proof", "at": {"node": "n1"},
                })
        finally:
            for child in opens:
                child.shutdown()
            if opens:
                orchestration.join_activation(first.get("activation_id"), timeout=1)
    catalog = json.loads((Path(__file__).parents[1] / "agent-text" / "tool-schemas.json").read_text())
    worker_tools = [name for name in catalog["roles"]["worker"] if catalog["tools"][name].get("handler")]
    sol_tools = [name for name in catalog["roles"]["sol"] if catalog["tools"][name].get("handler")]
    assert first["ok"] is True
    assert second["job_id"] == first["job_id"]
    assert second["activation_id"] == first["activation_id"]
    assert len(opens) == 1
    assert conflict["category"] == "operation_conflict"
    assert missing["category"] == "invalid_input"
    assert len(opens) == 1
    assert listed["ok"] is True
    assert first["job_id"] in [job["job_id"] for job in listed["jobs"]]
    assert cursed["category"] == "invalid_input"
    assert cancelled["ok"] is True
    assert forged["category"] == "invalid_input"
    assert forged["reason"] == "actor"
    assert not any(name in worker_tools for name in ("delegate", "jobs", "cancel"))
    assert {"delegate", "jobs", "cancel"} <= set(sol_tools)
