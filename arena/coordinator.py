"""Run-owned local transport for management that needs live worker ownership."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import select
import shutil
import socket
import tempfile
import threading
import uuid
from pathlib import Path

from arena import orchestration, text

_MAX_REQUEST = 65536


def _failure(reason: str) -> dict:
    return {"ok": False, "category": "recovery_required", "reason": reason, "retryable": True}


class Coordinator:
    """Host waits beside the runner's orchestration state, never in a tool process."""

    def __init__(self, directory: Path, *, inspect=None, signal=None, open_child=None):
        from arena.worker_process import ProcessInspector
        from arena.worker_process import open_child as spawn_child

        self.directory = directory.resolve()
        self._inspect = inspect if inspect is not None else ProcessInspector()
        self._signal = signal if signal is not None else self._inspect.signal
        self._open_child = open_child if open_child is not None else spawn_child
        self._guard = threading.Lock()
        self._clients: dict[socket.socket, tuple[threading.Event, threading.Thread]] = {}
        self._closed = threading.Event()
        self._generation = uuid.uuid4().hex
        self._owner = None
        self._socket = None
        self._temporary = None
        self._thread = None

    @property
    def generation(self) -> str:
        return self._generation

    def start(self) -> Coordinator:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._owner = (self.directory / "coordinator.lock").open("a")
        try:
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            recovered = orchestration.reconcile(
                self.directory, inspect=self._inspect, signal=self._signal, open_child=self._open_child,
            )
            if recovered.get("status") != "running" or not recovered.get("generation"):
                raise RuntimeError("recovery_required: owned workers or requests remain unreconciled")
            self._generation = recovered["generation"]
            self._temporary = Path(tempfile.mkdtemp(prefix="arena-control-"))
            address = str(self._temporary / "control.sock")
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.bind(address)
            os.chmod(address, 0o600)
            self._socket.listen()
            endpoint = self.directory / "coordinator.json"
            temporary = self.directory / f".coordinator-{self._generation}.json"
            temporary.write_text(json.dumps({"address": address, "generation": self._generation}))
            temporary.chmod(0o600)
            temporary.replace(endpoint)
            self._thread = threading.Thread(target=self._accept, daemon=True)
            self._thread.start()
            return self
        except BaseException:
            self.close()
            raise

    def _accept(self) -> None:
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            cancelled = threading.Event()
            thread = threading.Thread(target=self._serve, args=(connection, cancelled), daemon=True)
            with self._guard:
                if self._closed.is_set():
                    connection.close()
                    return
                self._clients[connection] = (cancelled, thread)
                thread.start()

    def _serve(self, connection: socket.socket, cancelled: threading.Event) -> None:
        monitor = None
        try:
            request_bytes = bytearray()
            while b"\n" not in request_bytes:
                chunk = connection.recv(min(4096, _MAX_REQUEST + 1 - len(request_bytes)))
                if not chunk:
                    return
                request_bytes.extend(chunk)
                if len(request_bytes) > _MAX_REQUEST:
                    raise ValueError("request too large")
            request = json.loads(bytes(request_bytes).split(b"\n", 1)[0])
            if (not isinstance(request, dict) or request.get("generation") != self._generation
                    or not isinstance(request.get("actor_id"), str)):
                raise ValueError("invalid management request")
            action = request.get("action")
            if action in ("delegate", "cancel"):
                try:
                    result = self._delegate(request) if action == "delegate" else self._cancel(request)
                except Exception as error:  # The receipt may be committed; a same-id retry returns it.
                    result = {**_failure(type(error).__name__), "operation_id": request.get("operation_id")}
                connection.sendall(json.dumps(result).encode() + b"\n")
                return
            if action == "best_moved":
                connection.sendall(json.dumps(orchestration.announce_best(self.directory)).encode() + b"\n")
                return
            if action != "await_results":
                raise ValueError("invalid management request")

            def disconnected() -> None:
                with contextlib.suppress(OSError, ValueError):
                    select.select([connection], [], [])
                cancelled.set()
                orchestration.wake_waiters()

            monitor = threading.Thread(target=disconnected, daemon=True)
            monitor.start()
            result = orchestration.await_results(
                self.directory, actor_id=request["actor_id"], cursor=request.get("cursor"),
                job_ids=request.get("job_ids"), cancel_event=cancelled,
            )
            connection.sendall(json.dumps(result).encode() + b"\n")
        except (OSError, ValueError) as error:
            with contextlib.suppress(OSError):
                connection.sendall(json.dumps(_failure(str(error))).encode() + b"\n")
        finally:
            cancelled.set()
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            if monitor is not None:
                monitor.join(timeout=1)
            with self._guard:
                self._clients.pop(connection, None)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()
        with self._guard:
            clients = list(self._clients.items())
        for connection, (cancelled, _) in clients:
            cancelled.set()
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
        if clients:
            orchestration.wake_waiters()
        for _, (_, thread) in clients:
            thread.join(timeout=1)
        if self._thread is not None:
            self._thread.join(timeout=1)
        endpoint = self.directory / "coordinator.json"
        try:
            if json.loads(endpoint.read_text()).get("generation") == self._generation:
                endpoint.unlink()
        except (FileNotFoundError, ValueError):
            pass
        if self._temporary is not None:
            shutil.rmtree(self._temporary, ignore_errors=True)
        if self._owner is not None:
            self._owner.close()

    def _delegate(self, request: dict) -> dict:
        if request.get("actor_id") != "sol":
            return _hinted("actor", request.get("operation_id"), "replies/delegate.actor")
        rejected = _rejected_delegate(request)
        if rejected is not None:
            return rejected
        return orchestration.delegate(
            self.directory,
            operation_id=str(request.get("operation_id") or ""),
            run_id=str(request.get("run_id") or ""),
            actor_id="sol",
            session_id=str(request.get("session_id") or ""),
            task=request["task"],
            open_child=self._open_child,
            scope=request.get("scope"),
            anchor=request.get("at"),
            job_id=request.get("job_id"),
        )

    def _cancel(self, request: dict) -> dict:
        operation_id = request.get("operation_id")
        if request.get("actor_id") != "sol":
            return _hinted("actor", operation_id, "replies/cancel.actor")
        job_id = request.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            return _hinted("job_id", operation_id, "replies/cancel.job_id")
        return orchestration.cancel(
            self.directory,
            operation_id=str(request.get("operation_id") or ""),
            run_id=str(request.get("run_id") or ""),
            actor_id="sol",
            session_id=str(request.get("session_id") or ""),
            job_id=job_id,
        )

    def __enter__(self) -> Coordinator:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()


def _hinted(reason: str, operation_id, hint: str) -> dict:
    return {"ok": False, "category": "invalid_input", "reason": reason,
            "hint": text.render(hint), "operation_id": operation_id}


def _delegate_invalid(reason: str, operation_id, hint: str | None = None) -> dict:
    """A rejected delegate body, with the one-line fix the model needs."""
    return {"ok": False, "category": "invalid_input", "reason": reason,
            "hint": text.render(f"replies/delegate.{hint or reason}"), "operation_id": operation_id}


def _rejected_delegate(request: dict) -> dict | None:
    """Reject a delegate body before the coordinator opens a worker."""
    operation_id = request.get("operation_id")
    task = request.get("task")
    if not isinstance(task, str) or not task:
        return _delegate_invalid("task", operation_id)
    job_id = request.get("job_id")
    scope = request.get("scope")
    anchor = request.get("at")
    if job_id is not None:
        if not isinstance(job_id, str) or not job_id or scope is not None or anchor is not None:
            return _delegate_invalid("follow-up", operation_id, "follow_up")
        return None
    if scope not in ("proof", "step") or not isinstance(anchor, dict) or not isinstance(anchor.get("node"), str) or not anchor.get("node"):
        return _delegate_invalid("scope", operation_id)
    steps = anchor.get("steps")
    hole = anchor.get("hole")
    has_steps = isinstance(steps, list) and len(steps) == 2 and all(type(item) is int for item in steps)
    has_hole = isinstance(hole, str) and bool(hole)
    if scope == "step" and has_steps == has_hole:
        return _delegate_invalid("anchor", operation_id, "anchor_step")
    if scope == "proof" and ("steps" in anchor or "hole" in anchor):
        return _delegate_invalid("anchor", operation_id, "anchor_proof")
    return None


def submit(directory: Path, request: dict, timeout: float | None = None) -> dict:
    """Send one management request to the live coordinator. The caller does not open workers."""
    try:
        endpoint = json.loads((directory / "coordinator.json").read_text())
        payload = {**request, "generation": endpoint["generation"]}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(endpoint["address"])
            connection.sendall(json.dumps(payload).encode() + b"\n")
            with connection.makefile("rb") as stream:
                response = stream.readline()
            if not response:
                return _failure("coordinator_closed")
            return json.loads(response)
    except (OSError, ValueError, KeyError):
        return _failure("coordinator_unavailable")


def await_results(directory: Path, *, actor_id: str, cursor=None, job_ids=None) -> dict:
    """Call the run owner. Missing ownership never falls back to local worker tables."""
    return submit(directory, {"action": "await_results", "actor_id": actor_id, "cursor": cursor, "job_ids": job_ids})


def announce_best(directory: Path) -> None:
    """Tell the coordinator the graph may have a new best, so it can steer its active workers. Best effort."""
    submit(directory, {"action": "best_moved", "actor_id": "harness"}, timeout=10)
