"""Recovery startup and owned-process boundaries without live process inspection."""

import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from arena import coordinator, pi_rpc, run_control, worker_process
from arena.worker_process import ProcessInspector, RpcChild


def test_startup_reconciles_before_endpoint(tmp_path):
    inspect = object()
    signal = object()
    spawn = object()

    def recover(directory, **adapters):
        assert directory == tmp_path
        assert not (directory / "coordinator.json").exists()
        assert adapters == {"inspect": inspect, "signal": signal, "open_child": spawn}
        return {"status": "running", "generation": "current"}

    with (
        patch.object(coordinator.orchestration, "reconcile", side_effect=recover),
        patch.object(coordinator.socket, "socket"),
        patch.object(coordinator.threading, "Thread"),
        patch.object(coordinator.os, "chmod"),
        coordinator.Coordinator(tmp_path, inspect=inspect, signal=signal, open_child=spawn) as owner,
    ):
        assert owner.generation == "current"
        assert json.loads((tmp_path / "coordinator.json").read_text())["generation"] == "current"
    assert not (tmp_path / "coordinator.json").exists()
    with (
        patch.object(coordinator.orchestration, "reconcile", return_value={"status": "recovering"}),
        pytest.raises(RuntimeError, match="recovery_required"),
    ):
        coordinator.Coordinator(tmp_path, inspect=inspect, signal=signal, open_child=spawn).start()
    assert not (tmp_path / "coordinator.json").exists()


def test_process_identity_and_group_signal(tmp_path):
    boot = tmp_path / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("boot-id")

    def process(pid, *, start="123", pgid=101, run="run", generation="g", session="s", state="S"):
        path = tmp_path / str(pid)
        path.mkdir(exist_ok=True)
        fields = [state, "1", str(pgid)] + ["0"] * 16 + [start]
        (path / "stat").write_text(f"{pid} (command with spaces) " + " ".join(fields))
        env = {"ARENA_RUN_ID": run, "ARENA_GENERATION": generation, "ARENA_SESSION_ID": session}
        (path / "environ").write_bytes(b"\0".join(f"{key}={value}".encode() for key, value in env.items()))

    process(101)
    process(102, start="124")
    sent = []
    inspector = ProcessInspector(tmp_path, killpg=lambda *args: sent.append(args))
    owned = {"pid": 101, "pgid": 101, "start_id": "boot-id:123", "run_id": "run", "generation": "g", "session_path": "/saved/s"}
    assert inspector.owned_group(owned)["group_alive"] is True
    inspector.signal(101)
    assert len(sent) == 1
    process(101, start="999")
    with pytest.raises(RuntimeError, match="ownership changed"):
        inspector.signal(101)
    assert len(sent) == 1
    process(101)
    process(102, generation="other")
    assert inspector.owned_group(owned) is None
    with pytest.raises(RuntimeError, match="unknown"):
        inspector.signal(101)
    process(101, pgid=999)
    process(102, pgid=999)
    assert inspector.owned_group(owned) is None
    process(101, pgid=999, start="reused")
    assert inspector.owned_group(owned)["group_alive"] is False
    process(102, state="Z")
    assert inspector.owned_group(owned)["group_alive"] is False


def test_fresh_start_establishes_dispatch_generation(tmp_path):
    def unexpected(*args):
        raise AssertionError("an empty run has no process to inspect, signal, or spawn")

    with (
        patch.object(coordinator.socket, "socket"),
        patch.object(coordinator.threading, "Thread"),
        patch.object(coordinator.os, "chmod"),
        coordinator.Coordinator(tmp_path, inspect=unexpected, signal=unexpected, open_child=unexpected) as owner,
    ):
        generations = [row["generation"] for row in run_control._control_rows(tmp_path) if row["kind"] == "run_generation"]
        assert generations[-1] == owner.generation
        endpoint = json.loads((tmp_path / "coordinator.json").read_text())
        assert endpoint["generation"] == owner.generation


def test_rpc_child_launch_uses_current_generation(tmp_path):
    (tmp_path / "run-config.json").write_text(json.dumps({"theorem": "demo"}))
    launch = pi_rpc.worker_launch(
        tmp_path, run_id="run", worker_actor_id="worker", worker_session_id="s", job_id="job",
        activation_id="activation", anchor={"node": "n1"}, generation="g",
    )

    class Inspector:
        group_alive = True

        def __init__(self):
            self.signalled = []

        def __call__(self, pid):
            return {"pid": pid, "pgid": pid, "start_id": "123", "alive": True}

        def owned_group(self, owned):
            assert owned["generation"] == "g"
            return {"group_alive": self.group_alive}

        def signal(self, pgid):
            self.signalled.append(pgid)

    inspector = Inspector()
    process = SimpleNamespace(pid=101, stdin=io.BytesIO(), stdout=io.BytesIO(b"{}\nlate\n"), poll=lambda: 0)

    def spawn(argv, **kwargs):
        assert argv == launch["argv"]
        assert kwargs["env"]["ARENA_GENERATION"] == "g"
        assert kwargs["start_new_session"] is True
        assert kwargs["cwd"] == tmp_path / "scratch" / "project"
        return process

    child = RpcChild(launch, spawn=spawn, inspect=inspector)
    child.subscribe()
    assert child.process_identity()["session_path"] == launch["session_dir"]
    assert child.read(3) == b"{}\n"
    assert child.write(b"prompt\n") == 7
    child.flush()
    child.shutdown()
    assert inspector.signalled == [101]
    assert not child.confirmed_absent()
    inspector.group_alive = False
    assert child.confirmed_absent()
    assert not process.stdout.closed
    assert child.read() == b"late\n"
    assert child.read() == b""
    assert process.stdin.closed and process.stdout.closed

    def failed_spawn(*args, **kwargs):
        raise FileNotFoundError("pi unavailable")

    with pytest.raises(FileNotFoundError) as uncertain:
        RpcChild(launch, spawn=failed_spawn, inspect=inspector)
    assert not getattr(uncertain.value, "not_spawned", False)
    with (
        patch.object(worker_process.subprocess, "Popen", failed_spawn),
        pytest.raises(FileNotFoundError) as never_spawned,
    ):
        RpcChild(launch, spawn=failed_spawn, inspect=inspector)
    assert never_spawned.value.not_spawned


def test_jsonl_cache_sees_appends_and_waits_for_a_complete_line(tmp_path):
    from arena import campaign

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_bytes(b'{"a":1}\n')
    assert campaign.events(tmp_path) == [{"a": 1}]
    with ledger.open("ab") as handle:
        handle.write(b'{"a":2}\n{"a":')
    assert campaign.events(tmp_path) == [{"a": 1}, {"a": 2}]
    with ledger.open("ab") as handle:
        handle.write(b"3}\n")
    assert campaign.events(tmp_path) == [{"a": 1}, {"a": 2}, {"a": 3}]
    ledger.write_bytes(b'{"b":9}\n{"b":8}\n{"b":7}\n')  # rewritten in place: no stale rows
    assert campaign.events(tmp_path) == [{"b": 9}, {"b": 8}, {"b": 7}]
