"""Persistent per-run Lean sessions.

Every probe, evaluation and profile used to run a fresh `lake env lean <file>`, which
re-imports the libraries and re-elaborates the unchanged file prefix on each call. A
session keeps Lean's own language server alive for the run. The candidate file is an
open document; a new draft is a `textDocument/didChange` that Lean re-elaborates
incrementally from the first changed line, so only the target theorem is elaborated.

Model tool calls are one-shot processes, so the server is owned by a per-run daemon
(`python -m arena.lean_session serve`) that the runner starts and stops. Compile paths
reach it through a Unix socket named in `ARENA_LEAN_SESSION`. Anything that goes wrong
(no daemon, crash, stale fingerprint, no memory) makes the caller run the cold compile
and report which path ran; a session result is never trusted more than a cold one.

Messages are rendered exactly like the command line renders them, so the diagnostics
parser and every line number downstream are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = "ARENA_LEAN_SESSION"
PROTOCOL = 1
SOCKET_NAME = "lean-session.sock"
INFO_NAME = "lean-session.json"
SESSION_FILES = (SOCKET_NAME, INFO_NAME, "lean-session", "lean-session.waiting")
MAX_SLOTS = 4            # concurrent documents (workers) per toolchain
MAX_WORKERS = 6          # across toolchains
WORKER_GB = 3.0          # planning figure until a real worker has been measured
RESERVE_GB = 5.0         # memory that must stay available after opening another worker
IDLE_SECONDS = 600       # a toolchain nobody asked for in this long is closed
SOCKET_LIMIT = 100       # sun_path is 108 bytes
# The server asks `lake setup-file` for the file's options and imports. Those options (a lakefile's
# `leanOptions`, such as warnings as errors) are not what `lake env lean <file>` compiles with, so
# the session must not receive them: `lake env` supplies LEAN_PATH, and pointing LAKE at nothing
# makes the server treat the file as having no lakefile.
NO_LAKE = "/nonexistent/arena-no-lake"
WAITING_NAME = "lean-session.waiting"  # touched when a request was refused a worker for memory; see memory_pressure()
WAITING_SECONDS = 120.0


def _log(message: str) -> None:
    """One timestamped line on stderr, which `start_daemon` points at lean-session.log: the only record of why
    a probe went cold (worker refused, evicted, timed out) once the run is over."""
    try:
        print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


def memory_pressure(directory: Path, within: float = WAITING_SECONDS) -> bool:
    """True when this run's session refused a worker for memory in the last `within` seconds. Background work of the
    same run (route extraction) yields to it: its cold Lean process is what the session was short of."""
    try:
        return time.time() - (directory / WAITING_NAME).stat().st_mtime < within
    except OSError:
        return False


# -- fingerprint ------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def code_sha() -> str:
    """Hash of the code that decides what text is compiled and how it is read back, as this
    process loaded it: a daemon started before an edit and a client started after it disagree."""
    digest = hashlib.sha256()
    for name in ("engine.py", "lean_session.py"):
        digest.update((Path(__file__).with_name(name)).read_bytes())
    return digest.hexdigest()[:16]


def fingerprint(project: Path) -> dict:
    """What a session's elaborated state depends on besides the file text."""
    def read(name: str) -> str:
        try:
            return (project / name).read_text()
        except OSError:
            return ""

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, text=True, capture_output=True).stdout.strip()
    return {"toolchain": read("lean-toolchain").strip(), "pin": head,
            "manifest": hashlib.sha256(read("lake-manifest.json").encode()).hexdigest()[:16],
            "code": code_sha()}


# -- rendering ---------------------------------------------------------------------------------


def _codepoint_column(line: str, utf16: int) -> int:
    seen = columns = 0
    for char in line:
        if seen >= utf16:
            break
        seen += 2 if ord(char) > 0xFFFF else 1
        columns += 1
    return columns


def render(diagnostics: list[dict], text: str, display: str) -> tuple[int, str]:
    """Language-server diagnostics -> (exit code, text) as `lean <file>` prints them.

    The command line prints an information message as bare text and warnings and errors
    as `file:line:column: severity: text` with a 1-based line and a code-point column.
    """
    lines = text.split("\n")
    out: list[str] = []
    failed = False
    for item in diagnostics:
        severity = item.get("severity", 1)
        message = item["message"]
        if severity in (1, 2):
            start = item["range"]["start"]
            line = lines[start["line"]] if start["line"] < len(lines) else ""
            label = "error" if severity == 1 else "warning"
            message = f"{display}:{start['line'] + 1}:{_codepoint_column(line, start['character'])}: {label}: {message}"
            failed = failed or severity == 1
        if not message or not message.endswith("\n"):
            message += "\n"
        out.append(message)
    return (1 if failed else 0), "".join(out).strip()


# -- language-server client --------------------------------------------------------------------


class SessionError(RuntimeError):
    """The session cannot answer; the caller falls back to a cold compile."""


class _Doc:
    def __init__(self, uri: str):
        self.uri = uri
        self.version = 0
        self.text: str | None = None
        self.result: dict | None = None
        self.diagnostics: dict | None = None
        self.lock = threading.Lock()
        self.busy = False
        self.used = time.monotonic()


class LeanServer:
    """One `lake env lean --server` for one pinned project, with one worker per open document."""

    def __init__(self, project: Path, log: Path):
        self.project = project
        self.log = log
        self.process: subprocess.Popen | None = None
        self.pending: dict[int, dict] = {}
        self.docs: dict[str, _Doc] = {}
        self.next_id = 1
        self.write_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.dead: str | None = None
        self.started = 0.0

    # lifecycle
    def start(self, timeout: float = 120) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        errors = self.log.open("ab")
        self.process = subprocess.Popen(
            ["lake", "env", "env", f"LAKE={NO_LAKE}", "lean", "--server"], cwd=self.project, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
        errors.close()
        threading.Thread(target=self._read, daemon=True, name="lean-reader").start()
        reply = self._request("initialize", {
            "processId": os.getpid(), "rootUri": self.project.as_uri(),
            "capabilities": {"textDocument": {}},
            "initializationOptions": {}}, timeout)
        if "error" in reply:
            raise SessionError(f"Lean server rejected initialize: {reply['error']}")
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        self.started = time.monotonic()

    @property
    def pgid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None and self.dead is None

    def stop(self) -> None:
        process, self.process = self.process, None
        self.dead = self.dead or "stopped"
        self._wake_all()
        if process is None:
            return
        tree = process_tree(process.pid)
        try:
            process.stdin.close()
        except OSError:
            pass
        for number in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, number)
            except (ProcessLookupError, PermissionError):
                break
            try:
                process.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        for pid in tree + process_tree(process.pid):  # workers have groups of their own
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    # wire
    def _send(self, message: dict) -> None:
        data = json.dumps(message).encode()
        process = self.process
        if process is None or process.stdin is None:
            raise SessionError("Lean server is not running")
        try:
            with self.write_lock:
                process.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
                process.stdin.flush()
        except (OSError, ValueError) as error:
            raise SessionError(f"Lean server connection lost: {error}") from None

    def _request(self, method: str, params: dict, timeout: float) -> dict:
        with self.state_lock:
            if self.dead:
                raise SessionError(f"Lean server is {self.dead}")
            number = self.next_id
            self.next_id += 1
            waiter = self.pending[number] = {"event": threading.Event(), "reply": None}
        self._send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
        if not waiter["event"].wait(timeout):
            self.pending.pop(number, None)
            raise TimeoutError(method)
        if waiter["reply"] is None:
            raise SessionError(f"Lean server is {self.dead or 'gone'}")
        return waiter["reply"]

    def _wake_all(self) -> None:
        for waiter in list(self.pending.values()):
            waiter["event"].set()

    def _read(self) -> None:
        process = self.process
        stream = process.stdout if process else None
        try:
            while stream is not None:
                length = None
                while True:
                    header = stream.readline()
                    if not header:
                        raise EOFError
                    header = header.strip()
                    if not header:
                        break
                    if header.lower().startswith(b"content-length:"):
                        length = int(header.split(b":")[1])
                if length is None:
                    continue
                self._dispatch(json.loads(stream.read(length)))
        except (EOFError, OSError, ValueError):
            pass
        finally:
            self.dead = self.dead or "crashed"
            self._wake_all()
            if process is not None:
                try:
                    process.wait(timeout=10)  # reap it so a crashed server is not left as a zombie
                except subprocess.TimeoutExpired:
                    pass

    def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        if method is not None and "id" in message:
            # The server asks the client to refresh editor state; acknowledge so it stops asking.
            try:
                self._send({"jsonrpc": "2.0", "id": message["id"], "result": None})
            except SessionError:
                pass
        elif method == "textDocument/publishDiagnostics":
            params = message["params"]
            doc = self.docs.get(params["uri"])
            if doc is not None:
                doc.diagnostics = params
        elif method is None and "id" in message:
            waiter = self.pending.pop(message["id"], None)
            if waiter is not None:
                waiter["reply"] = message
                waiter["event"].set()

    # documents
    def doc(self, uri: str) -> _Doc:
        with self.state_lock:
            return self.docs.setdefault(uri, _Doc(uri))

    def check(self, doc: _Doc, text: str, timeout: float) -> dict:
        """Make `doc` hold `text`; return its diagnostics once Lean has elaborated all of it.

        The caller holds the document exclusively. A timeout closes the document, which
        stops the elaboration and its worker, and reports `{"timeout": True}`.
        """
        if text == doc.text and doc.result is not None:
            return {**doc.result, "unchanged": True}
        before = doc.text
        started = time.monotonic()
        doc.version += 1
        version = doc.version
        doc.diagnostics = None
        if before is None:
            self._send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": doc.uri, "languageId": "lean4", "version": version, "text": text}}})
        else:
            self._send({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                "textDocument": {"uri": doc.uri, "version": version}, "contentChanges": [{"text": text}]}})
        doc.text = text
        doc.result = None
        try:
            reply = self._request("textDocument/waitForDiagnostics", {"uri": doc.uri, "version": version}, timeout)
        except TimeoutError:
            self.close_doc(doc)
            return {"timeout": True}
        if "error" in reply:
            self.close_doc(doc)
            raise SessionError(f"waitForDiagnostics failed: {reply['error'].get('message', reply['error'])[:200]}")
        deadline = time.monotonic() + 10
        while (doc.diagnostics is None or doc.diagnostics.get("version") != version) and time.monotonic() < deadline:
            if self.dead:
                raise SessionError(f"Lean server is {self.dead}")
            time.sleep(0.01)
        published = doc.diagnostics
        if published is None or published.get("version") != version:
            self.close_doc(doc)
            raise SessionError("Lean server published no diagnostics for the new text")
        result = {"diagnostics": published["diagnostics"], "seconds": round(time.monotonic() - started, 3),
                  "changed_from_line": _first_difference(before, text)}
        doc.result = result
        return result

    def close_doc(self, doc: _Doc) -> None:
        if doc.text is not None:
            try:
                self._send({"jsonrpc": "2.0", "method": "textDocument/didClose",
                            "params": {"textDocument": {"uri": doc.uri}}})
            except SessionError:
                pass
        doc.text = None
        doc.result = None
        doc.version += 1  # a reopened document must not reuse a version the server has seen


def _first_difference(before: str | None, after: str) -> int | None:
    """1-based line where `after` first differs from `before`; None when there was no earlier text."""
    if before is None:
        return None
    limit = min(len(before), len(after))
    at = next((i for i in range(limit) if before[i] != after[i]), limit)
    return after.count("\n", 0, at) + 1


# -- daemon --------------------------------------------------------------------------------------


def _available_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        pass
    return None


def process_tree(root: int | None) -> list[int]:
    """`root` and every process below it. The server starts each worker in a process group of its own,
    so a group is not enough to find them."""
    if root is None:
        return []
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent, []).append(int(entry.name))
    found, queue = [], [root]
    while queue:
        pid = queue.pop()
        if pid in found:
            continue
        found.append(pid)
        queue.extend(children.get(pid, []))
    return [pid for pid in found if Path(f"/proc/{pid}").exists()]


def tree_pss_gb(root: int | None) -> float:
    """Proportional memory of a process tree (the server and its workers)."""
    total = 0
    for pid in process_tree(root):
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except (OSError, ValueError):
            continue
    return total / 1024 / 1024


def running(pid: int) -> bool:
    """Alive and not a zombie."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


class _Entry:
    """A toolchain's server and its document slots."""

    def __init__(self, project: Path, key: dict, server: LeanServer):
        self.project = project
        self.key = key
        self.server = server
        self.slots: list[_Doc] = []
        self.condition = threading.Condition()
        self.used = time.monotonic()
        self.worker_gb = WORKER_GB
        self.last_text: str | None = None
        self.growing = False
        self.prefixes: dict[str, str] = {}  # file -> hash of the text before the target declaration


class Session:
    def __init__(self, directory: Path, max_slots: int = MAX_SLOTS):
        self.directory = directory
        self.logs = directory / "lean-session"
        self.max_slots = max_slots
        self.entries: dict[str, _Entry] = {}
        self.lock = threading.Lock()
        self.counter = 0
        self.closing = False
        self.primary: str | None = None  # the first toolchain asked for: the one the model works on

    # slots
    def _entry(self, project: Path, key: dict) -> _Entry:
        with self.lock:
            entry = self.entries.get(str(project))
            if entry is not None and (not entry.server.alive() or entry.key != key):
                reason = "crashed" if not entry.server.alive() else "changed"
                old = self.entries.pop(str(project))
                old.server.stop()
                _log(f"server {project.name} restarted: {reason}")
                if reason == "changed":
                    changed = sorted(k for k in key if key[k] != old.key.get(k))
                    raise SessionError("stale session: " + ", ".join(changed) + " changed; restarting it")
                entry = None
            if entry is None:
                server = LeanServer(project, self.logs / f"{project.name}.log")
                server.start()
                _log(f"server {project.name} started")
                entry = self.entries[str(project)] = _Entry(project, key, server)
                self.primary = self.primary or str(project)
            entry.used = time.monotonic()
            return entry

    def _guard_prefix(self, entry: _Entry, request: dict) -> None:
        """The file above the target declaration is pinned for the whole run. Lean would re-elaborate
        a changed prefix correctly, but a changed prefix means something else is wrong, so the
        session refuses to vouch for it and the caller compiles cold."""
        sha, display = request.get("prefix_sha"), request["display"]
        if not sha:
            return
        known = entry.prefixes.setdefault(display, sha)
        if known != sha:
            with self.lock:
                self.entries.pop(str(entry.project), None)
            entry.server.stop()
            _log(f"server {entry.project.name} restarted: file prefix changed")
            raise SessionError("stale session: the file prefix changed; restarting it")

    def _workers(self) -> int:
        return sum(len([s for s in e.slots if s.text is not None]) for e in self.entries.values())

    def _may_open(self, entry: _Entry) -> str | None:
        """None when another worker fits; otherwise why not."""
        if len(entry.slots) >= self.max_slots:
            return "slots"
        if self._workers() >= MAX_WORKERS:
            return "workers"
        free = _available_gb()
        if free is not None and free - entry.worker_gb < RESERVE_GB:
            return f"memory ({free:.1f} GB available)"
        return None

    def _acquire(self, entry: _Entry, timeout: float) -> _Doc:
        deadline = time.monotonic() + timeout
        with entry.condition:
            while True:
                if not entry.server.alive():
                    raise SessionError("Lean server crashed")
                idle = [slot for slot in entry.slots if not slot.busy]
                if idle:
                    slot = max(idle, key=lambda s: s.used)  # the most recently used worker is warmest
                    slot.busy = True
                    return slot
                with self.lock:
                    blocked = self._may_open(entry)
                    if blocked is None:
                        self.counter += 1
                        slot = entry.server.doc((entry.project / "ArenaScratch" / f"Session{self.counter}.lean").as_uri())
                        slot.busy = True
                        entry.slots.append(slot)
                        opened = (len(entry.slots), self._workers())
                if blocked is None:
                    _log(f"worker open {entry.project.name} slot {opened[0]}, {opened[1]} workers total")
                    return slot
                if blocked != "slots" and not entry.slots and not self._evict_idle(entry):
                    self._refused(entry, blocked)
                    raise SessionError(f"no room for a Lean worker: {blocked}")
                if blocked != "slots" and not entry.slots:
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    _log(f"timeout {entry.project.name}: every worker busy for {timeout:.0f} s")
                    raise SessionError("every Lean worker was busy for too long")
                entry.condition.wait(min(left, 1.0))

    def _refused(self, entry: _Entry, blocked: str) -> None:
        _log(f"refused {entry.project.name}: no room for a Lean worker: {blocked}; {self._workers()} workers open")
        if blocked.startswith("memory"):
            try:
                (self.directory / WAITING_NAME).touch()
            except OSError:
                pass

    def _evict_idle(self, keep: _Entry) -> bool:
        """Close the longest-idle worker of another toolchain to make room; False if none is idle."""
        with self.lock:
            idle = [(slot.used, other, slot) for other in self.entries.values() if other is not keep
                    for slot in other.slots if not slot.busy and slot.text is not None]
            if not idle:
                return False
            _, other, slot = min(idle, key=lambda item: item[0])
            # Lock order is entry then session everywhere else, so only try here.
            if not other.condition.acquire(blocking=False):
                return False
            try:
                if slot.busy:
                    return False
                other.server.close_doc(slot)
                other.slots.remove(slot)
                _log(f"worker evicted from {other.project.name} to make room for {keep.project.name}")
            finally:
                other.condition.release()
            return True

    def _grow(self, entry: _Entry) -> None:
        """Open the model toolchain's remaining documents in the background.

        A batch of drafts needs one warm document each; opening them while the model is thinking
        means the first batch is as fast as the later ones. Memory decides how many fit."""
        with entry.condition:
            if entry.growing or self.closing or len(entry.slots) >= self.max_slots or entry.last_text is None:
                return
            entry.growing = True
        threading.Thread(target=self._grow_all, args=(entry,), daemon=True, name="lean-grow").start()

    def _grow_all(self, entry: _Entry) -> None:
        workers: list[threading.Thread] = []
        try:
            while not self.closing:
                with entry.condition:
                    if not entry.server.alive():
                        break
                    with self.lock:
                        if self._may_open(entry) is not None:
                            break
                        self.counter += 1
                        slot = entry.server.doc((entry.project / "ArenaScratch" / f"Session{self.counter}.lean").as_uri())
                        slot.busy = True
                        entry.slots.append(slot)
                        text = entry.last_text
                        _log(f"worker open {entry.project.name} slot {len(entry.slots)} (pre-warm)")
                worker = threading.Thread(target=self._warm, args=(entry, slot, text), daemon=True, name="lean-warm")
                worker.start()
                workers.append(worker)
            for worker in workers:
                worker.join()
        finally:
            entry.growing = False

    def _warm(self, entry: _Entry, slot: _Doc, text: str) -> None:
        try:
            entry.server.check(slot, text, 600)
        except (SessionError, OSError):
            pass
        finally:
            self._release(entry, slot)

    def _release(self, entry: _Entry, slot: _Doc) -> None:
        with entry.condition:
            slot.busy = False
            slot.used = time.monotonic()
            entry.condition.notify()

    # request
    def check(self, request: dict) -> dict:
        if request.get("protocol") != PROTOCOL:
            return {"ok": False, "reason": "protocol mismatch"}
        project = Path(request["project"]).resolve()
        key = request["fingerprint"]
        if key.get("code") != code_sha():
            return {"ok": False, "stale": True, "reason": "stale session: the evaluator changed since the run started"}
        timeout = float(request.get("timeout", 180))
        try:
            entry = self._entry(project, key)
            self._guard_prefix(entry, request)
            slot = self._acquire(entry, timeout)
        except SessionError as error:
            return {"ok": False, "stale": str(error).startswith("stale"), "reason": str(error)}
        except OSError as error:
            return {"ok": False, "reason": f"cannot start Lean: {error}"}
        try:
            fresh = slot.text is None
            outcome = entry.server.check(slot, request["text"], timeout)
        except SessionError as error:
            return {"ok": False, "reason": str(error)}
        finally:
            self._release(entry, slot)
        if outcome.get("timeout"):
            _log(f"timeout {entry.project.name}: check ran past {timeout:.0f} s")
            return {"ok": True, "timeout": True}
        returncode, text = render(outcome["diagnostics"], request["text"], request["display"])
        self._measure(entry)
        entry.last_text = request["text"]
        if str(project) == self.primary:
            self._grow(entry)
        return {"ok": True, "returncode": returncode, "output": text,
                "seconds": outcome["seconds"], "new_worker": fresh,
                "changed_from_line": outcome.get("changed_from_line"),
                "unchanged": bool(outcome.get("unchanged")),
                "messages": len(outcome["diagnostics"])}

    def _measure(self, entry: _Entry) -> None:
        opened = len([s for s in entry.slots if s.text is not None])
        if opened and entry.worker_gb == WORKER_GB:
            used = tree_pss_gb(entry.server.pgid)
            if used:
                entry.worker_gb = max(0.5, used / opened)

    def status(self) -> dict:
        with self.lock:
            return {"pid": os.getpid(), "protocol": PROTOCOL, "code": code_sha(), "servers": [
                {"project": str(e.project), "workers": len([s for s in e.slots if s.text is not None]),
                 "busy": len([s for s in e.slots if s.busy]), "gb": round(tree_pss_gb(e.server.pgid), 2),
                 "pgid": e.server.pgid, "pids": process_tree(e.server.pgid)} for e in self.entries.values()]}

    def reap_idle(self) -> None:
        with self.lock:
            now = time.monotonic()
            for name, entry in list(self.entries.items()):
                if name != self.primary and now - entry.used > IDLE_SECONDS and not any(s.busy for s in entry.slots):
                    self.entries.pop(name).server.stop()
                    _log(f"server {Path(name).name} closed: idle {IDLE_SECONDS} s")

    def pgids(self) -> list[int]:
        return [e.server.pgid for e in self.entries.values() if e.server.pgid]

    def pids(self) -> list[int]:
        """Every Lean process the session owns: servers and their workers."""
        return sorted({pid for e in list(self.entries.values()) for pid in process_tree(e.server.pgid)})

    def shutdown(self) -> None:
        self.closing = True
        _log("session shutdown")
        with self.lock:
            entries, self.entries = list(self.entries.values()), {}
        for entry in entries:
            entry.server.stop()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = json.loads(self.rfile.readline())
        except ValueError:
            return
        session: Session = self.server.session  # type: ignore[attr-defined]
        op = request.get("op")
        try:
            if op == "check":
                reply = session.check(request)
            elif op == "status":
                reply = {"ok": True, **session.status()}
            elif op == "shutdown":
                reply = {"ok": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                reply = {"ok": False, "reason": f"unknown operation {op!r}"}
        except Exception as error:  # a bug here must degrade to the cold path, never to a wrong answer
            reply = {"ok": False, "reason": f"session error: {type(error).__name__}: {error}"[:300]}
        try:
            self.wfile.write(json.dumps(reply).encode() + b"\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def socket_path(directory: Path) -> Path:
    """The socket in the run directory; a short path under the user's runtime dir if that is too long."""
    preferred = directory / SOCKET_NAME
    if len(str(preferred)) <= SOCKET_LIMIT:
        return preferred
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    return base / f"arena-lean-{hashlib.sha256(str(directory).encode()).hexdigest()[:16]}.sock"


def serve(directory: Path, parent: int | None, max_slots: int) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    path = socket_path(directory)
    path.unlink(missing_ok=True)
    session = Session(directory, max_slots)
    server = _Server(str(path), _Handler)
    server.session = session  # type: ignore[attr-defined]
    info = directory / INFO_NAME

    def write_info() -> None:
        info.write_text(json.dumps({"pid": os.getpid(), "socket": str(path), "code": code_sha(),
                                    "parent": parent, "pgids": session.pgids(), "pids": session.pids()}) + "\n")

    def stop(*_args) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, stop)

    def watch() -> None:
        last = None
        while not session.closing:
            if parent is not None:
                try:
                    os.kill(parent, 0)
                except ProcessLookupError:
                    stop()
                    return
                except PermissionError:
                    pass
            session.reap_idle()
            if (session.pgids(), session.pids()) != last:
                last = (session.pgids(), session.pids())
                try:
                    write_info()
                except OSError:
                    pass
            time.sleep(1.0)

    _log(f"session up (pid {os.getpid()}, max slots {max_slots}, reserve {RESERVE_GB} GB)")
    write_info()
    threading.Thread(target=watch, daemon=True, name="watch").start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        session.shutdown()
        server.server_close()
        for leftover in (path, info):
            leftover.unlink(missing_ok=True)
    return 0


# -- client --------------------------------------------------------------------------------------


def request(payload: dict, timeout: float, path: str | None = None) -> dict | None:
    """One round trip to the daemon; None when there is no daemon or it cannot be reached."""
    path = path or os.environ.get(ENV)
    if not path:
        return None
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(timeout)
            connection.connect(path)
            connection.sendall(json.dumps(payload).encode() + b"\n")
            reader = connection.makefile("rb")
            line = reader.readline()
        return json.loads(line) if line else {"ok": False, "reason": "session closed the connection"}
    except (OSError, ValueError) as error:
        return {"ok": False, "reason": f"session unreachable: {type(error).__name__}"}


def configured() -> bool:
    return bool(os.environ.get(ENV))


def start_daemon(directory: Path, parent: int | None = None, max_slots: int = MAX_SLOTS,
                 wait: float = 15.0) -> subprocess.Popen:
    """Start the run's daemon in its own session and wait for its socket. Used by the runner."""
    directory.mkdir(parents=True, exist_ok=True)
    path = socket_path(directory)
    path.unlink(missing_ok=True)
    log = (directory / "lean-session.log").open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "arena.lean_session", "serve", "--run-dir", str(directory),
         "--parent-pid", str(parent if parent is not None else os.getpid()), "--max-slots", str(max_slots)],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SessionError("Lean session daemon exited at start-up; see lean-session.log")
        if path.exists() and request({"op": "status"}, 2, str(path)).get("ok"):
            return process
        time.sleep(0.05)
    stop_daemon(directory, process)
    raise SessionError("Lean session daemon did not become ready")


def stop_daemon(directory: Path, process: subprocess.Popen | None, grace: float = 20.0) -> None:
    """Stop the daemon and every Lean process it started, however they are doing."""
    pgids: list[int] = []
    pids: list[int] = []
    info = directory / INFO_NAME
    try:
        recorded = json.loads(info.read_text())
        pgids = [int(g) for g in recorded.get("pgids", [])]
        pids = [int(p) for p in recorded.get("pids", [])]
    except (OSError, ValueError):
        pass
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for pgid in pgids:  # only matters if the daemon died without cleaning up
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for pid in pids:
        try:  # a recorded pid may have been reused by now; only ever kill Lean
            if "lean" in Path(f"/proc/{pid}/cmdline").read_text().split("\0")[0]:
                os.kill(pid, signal.SIGKILL)
        except (OSError, IndexError):
            pass
    socket_path(directory).unlink(missing_ok=True)
    info.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("serve")
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--parent-pid", type=int)
    run.add_argument("--max-slots", type=int, default=MAX_SLOTS)
    args = parser.parse_args()
    return serve(args.run_dir, args.parent_pid, args.max_slots)


if __name__ == "__main__":
    raise SystemExit(main())
