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

from arena import orchestration

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
            if (not isinstance(request, dict) or request.get("action") != "await_results"
                    or request.get("generation") != self._generation
                    or not isinstance(request.get("actor_id"), str)):
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

    def __enter__(self) -> Coordinator:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.close()


def await_results(directory: Path, *, actor_id: str, cursor=None, job_ids=None) -> dict:
    """Call the run owner. Missing ownership never falls back to local worker tables."""
    try:
        endpoint = json.loads((directory / "coordinator.json").read_text())
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(endpoint["address"])
            request = {"action": "await_results", "generation": endpoint["generation"],
                       "actor_id": actor_id, "cursor": cursor, "job_ids": job_ids}
            connection.sendall(json.dumps(request).encode() + b"\n")
            with connection.makefile("rb") as stream:
                response = stream.readline()
            if not response:
                return _failure("coordinator_closed")
            return json.loads(response)
    except (OSError, ValueError, KeyError):
        return _failure("coordinator_unavailable")
