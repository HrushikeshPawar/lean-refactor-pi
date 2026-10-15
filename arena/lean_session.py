"""Persistent per-run Lean sessions.

Every probe, evaluation and profile used to run a fresh `lake env lean <file>`, which
re-imports the libraries and re-elaborates the unchanged file prefix on each call. A
session keeps Lean's own language server alive for the run. The candidate file is an
open document; a new draft is a `textDocument/didChange` that Lean re-elaborates
incrementally from the first changed line, so only the target theorem is elaborated.

Model tool calls are one-shot processes, so the servers are owned by one service per machine
(`python -m arena.lean_session serve`), started on demand by `ensure_service`. A run leases the
toolchains it uses; a toolchain closes when no lease or hold has named it for RELEASE_GRACE_S, so
the next run of the same row finds it warm. Compile paths reach the service through the Unix
socket named in `ARENA_LEAN_SESSION`. Anything that goes wrong (no service, crash, stale
fingerprint, no memory) makes the caller run the cold compile and report which path ran; a session
result is never trusted more than a cold one.

Messages are rendered exactly like the command line renders them, so the diagnostics
parser and every line number downstream are unchanged.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from functools import lru_cache
from pathlib import Path
from typing import IO, cast

ROOT = Path(__file__).resolve().parents[1]
ENV = "ARENA_LEAN_SESSION"
PROTOCOL = 2
SOCKET_NAME = "service.sock"
INFO_NAME = "service.json"
LOG_NAME = "service.log"
LOCK_NAME = "start.lock"
SERVICE_DIR_ENV = "ARENA_LEAN_SERVICE_DIR"
RUN_ID_ENV = "ARENA_LEAN_RUN_ID"
SESSION_FILES = ("lean-session.sock", "lean-session.json", "lean-session", "lean-session.waiting")
PRIMARY_MIN_WORKERS = 2
PRIMARY_MAX_WORKERS = 3
OTHER_WORKERS = 1
TRY_MAX_SNIPPETS = 8
BACKGROUND_TOKENS = (
    64  # token files kept past the machine limit for the background workers (one per toolchain a live session checks)
)
MODEL_QUEUE_TIMEOUT = float(
    os.environ.get("ARENA_LEAN_QUEUE_TIMEOUT", "900")
)  # a model request may wait this long for a free worker; not charged to its check timeout
QUEUE_LOG_S = 30  # waits for a worker longer than this are logged
OPEN_TIMEOUT = 900  # a fresh worker's header (imports) may take this long; not charged to a request's timeout
MACHINE_MAX_WORKERS = int(
    os.environ.get("ARENA_MACHINE_MAX_WORKERS", "8")
)  # model workers across every daemon on the machine (background workers are extra)
TOKEN_DIR_NAME = "arena-lean-workers"
OPENING_NAME = (
    "opening.lock"  # held by whichever worker on the machine is loading its imports (see WorkerBudget.opening)
)
WORKER_GB = 3.0  # planning figure until a real worker has been measured
RESERVE_GB = 5.0  # memory that must stay available after opening another worker
ADHOC_IDLE_S = 600  # a project no lease or hold ever named closes after this long without a request
RELEASE_GRACE_S = float(
    os.environ.get("ARENA_LEAN_RELEASE_GRACE_S", "120")
)  # a project stays warm this long after its last lease or hold ends, for the row's next run
SERVICE_LINGER_S = 600  # the service exits after this long with no projects, leases or holds
SOCKET_LIMIT = 100  # sun_path is 108 bytes
# The server asks `lake setup-file` for the file's options and imports. Those options (a lakefile's
# `leanOptions`, such as warnings as errors) are not what `lake env lean <file>` compiles with, so
# the session must not receive them: `lake env` supplies LEAN_PATH, and pointing LAKE at nothing
# makes the server treat the file as having no lakefile.
NO_LAKE = "/nonexistent/arena-no-lake"
WAITING_NAME = "lean-session.waiting"  # touched when a request was refused a worker for memory; see memory_pressure()
WAITING_SECONDS = 120.0
PSS_LOG_S = 60
PSS_LOG_MAX_BYTES = 5 * 1024 * 1024


def service_dir() -> Path:
    """Return the machine-wide service directory."""
    if value := os.environ.get(SERVICE_DIR_ENV):
        return Path(value)
    if value := os.environ.get("XDG_RUNTIME_DIR"):
        return Path(value) / "arena-lean-service"
    return Path("/tmp") / f"arena-lean-service-{os.getuid()}"


def reorder_lean_path(lean_path: str, project: Path) -> str:
    """Put the project's own build folder first. `lake env` lists every dependency before it, so each of the
    thousands of project modules is first looked up (and missed) in all of them: on a FUSE drive that is 128 s
    against 35 s. Order of the others is kept; duplicates are dropped."""
    own = str(project / ".lake" / "build" / "lib" / "lean")
    parts = [part for part in lean_path.split(os.pathsep) if part]
    first = [part for part in parts if os.path.normpath(part) == os.path.normpath(own)][:1]
    seen = set(first)
    rest = []
    for part in parts:
        if part not in seen and not (first and os.path.normpath(part) == os.path.normpath(own)):
            seen.add(part)
            rest.append(part)
    return os.pathsep.join(first + rest)


@lru_cache(maxsize=16)
def server_lean_path(project: str) -> str | None:
    """The reordered LEAN_PATH the language server should run with (computed once per project), or None when
    `lake env printenv LEAN_PATH` fails: the server then runs with lake's own order."""
    try:
        done = subprocess.run(
            ["lake", "env", "printenv", "LEAN_PATH"], cwd=project, capture_output=True, text=True, timeout=120
        )
        value = done.stdout.strip()
        if done.returncode != 0 or not value:
            return None
        return reorder_lean_path(value, Path(project))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _log(message: str) -> None:
    """One timestamped line on stderr, captured in service.log as the record of why
    a probe went cold (worker refused, evicted, timed out) once the run is over."""
    with suppress(OSError, ValueError):
        print(f"{time.strftime('%H:%M:%S')} {message}", file=sys.stderr, flush=True)


def memory_pressure(within: float = WAITING_SECONDS) -> bool:
    """True when this run's session refused a worker for memory in the last `within` seconds. Background work of the
    same run (route extraction) yields to it: its cold Lean process is what the session was short of."""
    try:
        return time.time() - (service_dir() / WAITING_NAME).stat().st_mtime < within
    except OSError:
        return False


# -- machine-wide worker budget ---------------------------------------------------------------


class _Token:
    """A held flock on one token file. Closing the file (or the process dying) frees it."""

    def __init__(self, fd: int, name: str):
        self.fd, self.name = fd, name

    def release(self) -> None:
        fd, self.fd = self.fd, -1
        if fd >= 0:
            with suppress(OSError):
                os.close(fd)  # closing the descriptor drops the flock

    def __del__(self) -> None:
        self.release()


class WorkerBudget:
    """At most `limit` Lean workers across every session daemon on the machine.

    One token file per worker, each held with `flock` for as long as the worker exists. The kernel drops
    the lock when the holder exits, so a crashed daemon frees its tokens by itself."""

    def __init__(self, directory: Path | None = None, limit: int | None = None):
        if directory is None:
            env = os.environ.get("ARENA_LEAN_TOKEN_DIR")
            directory = Path(env) if env else Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / TOKEN_DIR_NAME
        self.directory = directory
        self.limit = MACHINE_MAX_WORKERS if limit is None else limit

    def acquire(self, background: bool = False) -> _Token | None:
        """A token, or None when every one is held. An unusable directory enforces nothing (a no-op token).
        Background workers draw from a reserved range past `limit`, so a session's guaranteed background worker
        is never crowded out by model workers."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return _Token(-1, "unshared")
        numbers = range(self.limit, self.limit + BACKGROUND_TOKENS) if background else range(self.limit)
        for number in numbers:
            path = self.directory / f"worker-{number}.lock"
            try:
                fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
            except OSError:
                return _Token(-1, "unshared")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                continue
            return _Token(fd, path.name)
        return None

    def available(self, background: bool = False) -> bool:
        token = self.acquire(background)
        if token is None:
            return False
        token.release()
        return True

    @contextmanager
    def opening(self, need_gb: float, timeout: float) -> Generator[float]:
        """Hold the machine-wide right to load one worker's imports, once `need_gb` fits above RESERVE_GB; yields the
        seconds spent waiting. A worker still loading has not reached its size, so memory read at open time cannot be
        trusted while another one loads: three runs warming at once each saw 24 GB free and filled swap together."""
        deadline = time.monotonic() + timeout
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.directory / OPENING_NAME, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError:
            fd = -1  # an unusable directory gates nothing but memory
        try:
            while fd >= 0:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise SessionError(f"another Lean worker was still loading after {timeout:.0f} s") from None
                    time.sleep(0.2)
            while (free := _available_gb()) is not None and free - need_gb < RESERVE_GB:
                if time.monotonic() >= deadline:
                    raise SessionError(f"no memory to load a Lean worker ({free:.1f} GB available)")
                time.sleep(1.0)
            yield timeout - (deadline - time.monotonic())
        finally:
            if fd >= 0:
                os.close(fd)  # drops the flock


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
    return {
        "toolchain": read("lean-toolchain").strip(),
        "pin": head,
        "manifest": hashlib.sha256(read("lake-manifest.json").encode()).hexdigest()[:16],
        "code": code_sha(),
    }


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
        self.progress_line: int | None = None
        self.lock = threading.Lock()
        self.busy = False
        self.used = time.monotonic()
        self.lane = "model"
        self.header: str | None = None  # the text of the imports and prefix this document was opened with
        self.display: str | None = None
        self.stale = False  # its file prefix changed while it was busy: closed when released
        self.token: _Token | None = None


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
        self.open_gate: Callable[[float], AbstractContextManager[float]] | None = None

    # lifecycle
    def command(self) -> list[str]:
        path = server_lean_path(str(self.project))
        override = [f"LEAN_PATH={path}"] if path else []  # env's later assignment overrides lake's order
        return ["lake", "env", "env", f"LAKE={NO_LAKE}", *override, "lean", "--server"]

    def start(self, timeout: float = 120) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        errors = self.log.open("ab")
        self.process = subprocess.Popen(
            self.command(),
            cwd=self.project,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            start_new_session=True,
        )
        errors.close()
        threading.Thread(target=self._read, daemon=True, name="lean-reader").start()
        reply = self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": self.project.as_uri(),
                "capabilities": {"textDocument": {}},
                "initializationOptions": {},
            },
            timeout,
        )
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
        with suppress(OSError):
            if process.stdin is not None:
                process.stdin.close()
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
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)

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
            waiter: dict[str, object] = {"event": threading.Event(), "reply": None}
            self.pending[number] = waiter
        self._send({"jsonrpc": "2.0", "id": number, "method": method, "params": params})
        event = waiter["event"]
        if not event.wait(timeout):
            self.pending.pop(number, None)
            raise TimeoutError(method)
        reply = waiter["reply"]
        if not isinstance(reply, dict):
            raise SessionError(f"Lean server is {self.dead or 'gone'}")
        return reply

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
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=10)  # reap it so a crashed server is not left as a zombie

    def _dispatch(self, message: dict) -> None:
        method = message.get("method")
        if method is not None and "id" in message:
            # The server asks the client to refresh editor state; acknowledge so it stops asking.
            with suppress(SessionError):
                self._send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        elif method == "textDocument/publishDiagnostics":
            params = message["params"]
            doc = self.docs.get(params["uri"])
            if doc is not None:
                doc.diagnostics = params
        elif method == "$/lean/fileProgress":
            params = message.get("params", {})
            doc = self.docs.get(params.get("textDocument", {}).get("uri"))
            if doc is not None:
                lines = [item.get("range", {}).get("start", {}).get("line") for item in params.get("processing", [])]
                lines = [line for line in lines if isinstance(line, int)]
                if lines:
                    doc.progress_line = max(lines) if doc.progress_line is None else max(doc.progress_line, *lines)
        elif method is None and "id" in message:
            waiter = self.pending.pop(message["id"], None)
            if waiter is not None:
                waiter["reply"] = message
                waiter["event"].set()

    # documents
    def doc(self, uri: str) -> _Doc:
        with self.state_lock:
            return self.docs.setdefault(uri, _Doc(uri))

    def _send_text(self, doc: _Doc, text: str) -> int:
        """Open or change the document to `text` under a fresh version; returns that version."""
        doc.version += 1
        version = doc.version
        doc.diagnostics = None
        doc.progress_line = None
        if doc.text is None:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didOpen",
                    "params": {
                        "textDocument": {"uri": doc.uri, "languageId": "lean4", "version": version, "text": text}
                    },
                }
            )
        else:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/didChange",
                    "params": {
                        "textDocument": {"uri": doc.uri, "version": version},
                        "contentChanges": [{"text": text}],
                    },
                }
            )
        doc.text = text
        doc.result = None
        return version

    def open_header(self, doc: _Doc, header: str, timeout: float = OPEN_TIMEOUT) -> float:
        """Load only the header (imports and the pinned prefix) into `doc` and wait for it; returns the seconds
        that took. On any failure the document is closed and SessionError raised: the worker is not usable."""
        started = time.monotonic()
        with self.open_gate(timeout) if self.open_gate else nullcontext(0.0) as waited:
            left = max(1.0, timeout - waited)
            version = self._send_text(doc, header)
            doc.header = header
            try:
                reply = self._request("textDocument/waitForDiagnostics", {"uri": doc.uri, "version": version}, left)
            except TimeoutError:
                self.close_doc(doc)
                raise SessionError(f"the file header did not load within {timeout:.0f} s") from None
            except SessionError:
                self.close_doc(doc)
                raise
        if "error" in reply:
            self.close_doc(doc)
            raise SessionError(f"waitForDiagnostics failed: {reply['error'].get('message', reply['error'])[:200]}")
        return round(time.monotonic() - started, 3)

    def check(
        self,
        doc: _Doc,
        text: str,
        timeout: float,
        header_end: int | None = None,
        open_timeout: float = OPEN_TIMEOUT,
        run_id: str | None = None,
    ) -> dict:
        """Make `doc` hold `text`; return its diagnostics once Lean has elaborated all of it.

        The caller holds the document exclusively. With `header_end`, a fresh document is first opened with
        only `text[:header_end]` (waited for up to `open_timeout`, which is not charged to `timeout`), so the
        imports are loaded before the request's clock starts. A timeout does not close a document whose
        header is known: it is changed back to the header, which cancels the proof's elaboration and keeps
        the imports loaded (`warm_kept`). Anything else closes the document, which ends its worker.
        """
        header = text[:header_end] if header_end else None
        if header is not None and doc.text is not None and doc.header is not None and doc.header != header:
            self.close_doc(doc)  # the file above the target changed: nothing loaded can be reused
        if text == doc.text and doc.result is not None:
            return {**{k: v for k, v in doc.result.items() if k != "header_seconds"}, "unchanged": True}
        before = doc.text
        header_seconds = None
        if doc.text is None and header is not None:
            header_seconds = self.open_header(doc, header, open_timeout)
            before = None  # to the caller this is a fresh worker
            _log(f"header open run={run_id or 'ad-hoc'} {Path(doc.uri).name}: {header_seconds:.1f} s")
        started = time.monotonic()
        version = self._send_text(doc, text)
        try:
            reply = self._request("textDocument/waitForDiagnostics", {"uri": doc.uri, "version": version}, timeout)
        except TimeoutError:
            partial = doc.diagnostics
            timed_out = {
                "timeout": True,
                "partial": partial.get("diagnostics", []) if partial and partial.get("version") == version else [],
                "progress_line": doc.progress_line,
            }
            if header_seconds is not None:
                timed_out["header_seconds"] = header_seconds
            if header is not None and doc.header == header:
                try:  # a newer version cancels the elaboration of the old one; the imports stay loaded
                    self._send_text(doc, header)
                    timed_out["warm_kept"] = True
                    _log(f"timeout kept {Path(doc.uri).name} warm after {timeout:.1f} s")
                    return timed_out
                except SessionError:
                    pass
            self.close_doc(doc)
            return timed_out
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
        result = {
            "diagnostics": published["diagnostics"],
            "seconds": round(time.monotonic() - started, 3),
            "changed_from_line": _first_difference(before, text),
        }
        if header_seconds is not None:
            result["header_seconds"] = header_seconds
        if header is not None:
            doc.header = header
        doc.result = result
        return result

    def close_doc(self, doc: _Doc) -> None:
        if doc.text is not None:
            with suppress(SessionError):
                self._send(
                    {"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {"textDocument": {"uri": doc.uri}}}
                )
        doc.text = None
        doc.result = None
        doc.header = None
        doc.version += 1  # a reopened document must not reuse a version the server has seen


def _first_difference(before: str | None, after: str) -> int | None:
    """1-based line where `after` first differs from `before`; None when there was no earlier text."""
    if before is None:
        return None
    limit = min(len(before), len(after))
    at = next((i for i in range(limit) if before[i] != after[i]), limit)
    return after.count("\n", 0, at) + 1


def _utf16_column(line_text: str, column: int) -> int:
    return len(line_text[:column].encode("utf-16-le")) // 2


def _position(text: str, line: int, column: int) -> dict:
    lines = text.splitlines()
    source = lines[line] if 0 <= line < len(lines) else ""
    return {"line": line, "character": _utf16_column(source, column)}


def _replace_hole(text: str, hole: dict, snippet: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = hole["line"], hole["end_line"]
    before = "".join(lines[:start]) + lines[start][: hole["column"]]
    after = lines[end][hole["end_column"] :]
    return before + snippet + after


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


def pid_pss_gb(pid: int) -> float | None:
    """Proportional memory of one process, or None when its smaps data is unavailable."""
    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        return None
    return None


def tree_pss_gb(root: int | None, pss_reader: Callable[[int], float | None] = pid_pss_gb) -> float:
    """Proportional memory of a process tree (the server and its workers)."""
    return sum(value for pid in process_tree(root) if (value := pss_reader(pid)) is not None)


def worker_pss(root_pid: int | None) -> dict[int, float]:
    """PSS in GB for each Lean worker below a server process."""
    result = {}
    for pid in process_tree(root_pid):
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "lean" in command and "--worker" in command:
            value = pid_pss_gb(pid)
            if value is not None:
                result[pid] = value
    return result


def worker_document(pid: int) -> str | None:
    """The document URI a `lean --worker` process serves: Lean passes it as the worker's last argument."""
    try:
        words = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return None
    words = [word for word in words if word]
    return words[-1] if "--worker" in words[:-1] else None


def external_lean_pss(own_pids: set[int]) -> dict[int, float]:
    """PSS for Lean processes not owned by this service."""
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in own_pids:
            continue
        try:
            command = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if command == "lean":
            value = pid_pss_gb(int(entry.name))
            if value is not None:
                result[int(entry.name)] = value
    return result


def _mem_snapshot() -> tuple[float | None, float | None]:
    available = _available_gb()
    swap = None
    try:
        values = {
            line.split(":", 1)[0]: int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith(("SwapTotal:", "SwapFree:"))
        }
        if "SwapTotal" in values and "SwapFree" in values:
            swap = (values["SwapTotal"] - values["SwapFree"]) / 1024 / 1024
    except (OSError, ValueError, IndexError):
        pass
    return available, swap


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
        self.prefixes: dict[tuple[str | None, str], str] = {}  # (run, file) -> hash of the text before the target
        self.unreferenced_since: float | None = None  # when the last lease or hold naming it ended
        self.last_header_end: int | None = None
        self.was_referenced = False
        self.queues: dict[str, list[object]] = {
            "model": [],
            "background": [],
        }  # waiters per lane, first come first served

    def lane_slots(self, lane: str) -> list[_Doc]:
        return [slot for slot in self.slots if slot.lane == lane]


class Session:
    def __init__(
        self,
        directory: Path,
        budget: WorkerBudget | None = None,
        *,
        mem_fn=None,
        pss_fn=None,
        external_fn=None,
        document_fn=None,
    ):
        self.directory = directory
        self.budget = budget if budget is not None else WorkerBudget()
        self._reserved: _Token | None = None  # a token _may_open took for the slot its caller is about to create
        self.logs = directory / "lean-session"
        self.leases: dict[str, dict] = {}
        self.holds: dict[str, dict] = {}
        self.entries: dict[str, _Entry] = {}
        self._starting: dict[str, threading.Lock] = {}  # one server start per project at a time
        self.lock = threading.Lock()
        self.counter = 0
        self.closing = False
        self.last_active = time.monotonic()
        self.mem_fn = mem_fn or _mem_snapshot
        self.pss_fn = pss_fn or worker_pss
        self.external_fn = external_fn or external_lean_pss
        self.document_fn = document_fn or worker_document
        from arena.lean_repl import ReplPool, process_gb

        self.repl = ReplPool(pss_fn=process_gb, opening=self.budget.opening)
        self.last_pss_log = time.monotonic()

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        return running(pid)

    @staticmethod
    def _name(project: Path | str) -> str:
        return str(Path(project).resolve())

    def _referenced_locked(self, name: str) -> bool:
        return any(name == lease["primary"] or name in lease["others"] for lease in self.leases.values()) or any(
            name in hold["projects"] for hold in self.holds.values()
        )

    def _referenced(self, project: Path | str) -> bool:
        name = self._name(project)
        with self.lock:
            return self._referenced_locked(name)

    def _is_primary(self, project: Path | str) -> bool:
        name = self._name(project)
        with self.lock:
            return any(name == lease["primary"] for lease in self.leases.values())

    def _is_adhoc(self, entry: _Entry) -> bool:
        return not entry.was_referenced

    def _is_held(self, project: Path | str) -> bool:
        name = self._name(project)
        with self.lock:
            return any(name in hold["projects"] for hold in self.holds.values())

    def _lane(self, project: Path, entry: _Entry, requested: str) -> str:
        if requested == "background":
            return "background"
        name = self._name(project)
        with self.lock:
            only_other = (
                any(name in lease["others"] and name != lease["primary"] for lease in self.leases.values())
                and not any(name == lease["primary"] for lease in self.leases.values())
                and not any(name in hold["projects"] for hold in self.holds.values())
            )
        return "background" if only_other and not self._is_adhoc(entry) else "model"

    def _claim(self, names: list[str]) -> None:
        """A new lease or hold stops its projects' grace countdown; they are never ad hoc again. Caller holds the lock."""
        for name in names:
            if entry := self.entries.get(name):
                entry.was_referenced = True
                entry.unreferenced_since = None

    def _unclaim(self, names: list[str]) -> list[str]:
        """Start the grace countdown of every open project nothing references any more. Caller holds the lock."""
        now, closing = time.monotonic(), []
        for name in names:
            entry = self.entries.get(name)
            if entry is not None and not self._referenced_locked(name):
                if entry.unreferenced_since is None:
                    entry.unreferenced_since = now
                closing.append(name)
        return closing

    def lease(self, request: dict) -> dict:
        pid = int(request.get("pid", 0))
        run_id = str(request.get("run_id", ""))
        if not run_id or not self._pid_alive(pid):
            return {"ok": False, "reason": "lease pid is not alive"}
        primary = self._name(request["primary"])
        others = [self._name(project) for project in request.get("others", [])]
        with self.lock:
            self.leases[run_id] = {"pid": pid, "primary": primary, "others": others}
            self._claim([primary, *others])
        return {"ok": True}

    def hold(self, request: dict) -> dict:
        pid = int(request.get("pid", 0))
        if not self._pid_alive(pid):
            return {"ok": False, "reason": "hold pid is not alive"}
        owner = str(request["owner"])
        projects = [self._name(project) for project in request["projects"]]
        with self.lock:
            previous = self.holds.get(owner, {}).get("projects", [])
            self.holds[owner] = {"pid": pid, "projects": projects}
            self._claim(projects)
            self._unclaim(previous)
        return {"ok": True}

    def release(self, run_id: str) -> dict:
        """Drop a lease. Projects nothing else references close after RELEASE_GRACE_S (`closing`)."""
        with self.lock:
            lease = self.leases.pop(run_id, None)
            closing = self._unclaim([lease["primary"], *lease["others"]]) if lease else []
            unreferenced = [name for name in closing if not self._referenced_locked(name)]
        for name in unreferenced:
            self.repl.close_project(name)
        return {"ok": True, "closing": closing}

    def unhold(self, owner: str) -> dict:
        with self.lock:
            hold = self.holds.pop(owner, None)
            if hold:
                self._unclaim(hold["projects"])
                unreferenced = [name for name in hold["projects"] if not self._referenced_locked(name)]
            else:
                unreferenced = []
        for name in unreferenced:
            self.repl.close_project(name)
        return {"ok": True}

    def _close_unreferenced(self, entry: _Entry) -> None:
        with entry.condition:
            if any(slot.busy for slot in entry.slots):
                return
            with self.lock:
                name = str(entry.project)
                if self._referenced_locked(name) or self.entries.get(name) is not entry:
                    return
                self.entries.pop(name)
            self._stop_entry(entry)  # under the condition, as before: no waiter takes a slot of a closing entry
        self.repl.close_project(entry.project)
        _log(f"closed: no run or queued row needs it ({entry.project.name})")

    def reap_dead(self) -> None:
        """Drop leases and holds whose process is gone; their projects start the grace countdown."""
        with self.lock:
            dead = [lease for lease in self.leases.values() if not self._pid_alive(lease["pid"])]
            dead += [hold for hold in self.holds.values() if not self._pid_alive(hold["pid"])]
            self.leases = {key: value for key, value in self.leases.items() if self._pid_alive(value["pid"])}
            self.holds = {key: value for key, value in self.holds.items() if self._pid_alive(value["pid"])}
            for item in dead:
                self._unclaim([item["primary"], *item["others"]] if "primary" in item else item["projects"])

    # slots
    def _entry(self, project: Path, key: dict) -> _Entry:
        name = str(project)
        with self.lock:
            starting = self._starting.setdefault(name, threading.Lock())
        # Starting a server takes seconds: hold only this project's start lock, so status and other
        # projects are never kept waiting behind it.
        with starting:
            with self.lock:
                entry = self.entries.get(name)
                reason = None
                if entry is not None and (not entry.server.alive() or entry.key != key):
                    reason = "crashed" if not entry.server.alive() else "changed"
                    self.entries.pop(name)
            if entry is not None and reason is not None:
                self._stop_entry(entry)
                _log(f"server {project.name} restarted: {reason}")
                if reason == "changed":
                    changed = sorted(k for k in key if key[k] != entry.key.get(k))
                    raise SessionError("stale session: " + ", ".join(changed) + " changed; restarting it")
                entry = None
            if entry is None:
                server = LeanServer(project, self.logs / f"{project.name}.log")
                server.start()
                _log(f"server {project.name} started")
                entry = _Entry(project, key, server)
                server.open_gate = lambda timeout, entry=entry: self.budget.opening(entry.worker_gb, timeout)
                with self.lock:
                    if self.closing:
                        server.stop()
                        raise SessionError("session closing")
                    entry.was_referenced = self._referenced_locked(name)
                    self.entries[name] = entry
            entry.used = time.monotonic()
            return entry

    def _guard_prefix(self, entry: _Entry, request: dict) -> None:
        """The file above the target declaration is pinned for the whole run. Lean would re-elaborate
        a changed prefix correctly, but a changed prefix means something else is wrong, so the
        session refuses to vouch for it and the caller compiles cold."""
        sha, display = request.get("prefix_sha"), request["display"]
        if not sha:
            return
        pin = (request.get("run_id"), display)  # runs share the service; each run pins its own prefix
        known = entry.prefixes.setdefault(pin, sha)
        if known != sha:
            with entry.condition:
                entry.prefixes.pop(pin, None)  # the next request pins the prefix afresh
                for slot in list(entry.slots):
                    if slot.display != display:
                        continue
                    if slot.busy:
                        slot.stale = True
                        continue
                    with suppress(SessionError, OSError):
                        entry.server.close_doc(slot)
                    entry.slots.remove(slot)
                    self._free(slot)
            _log(f"documents for {display} closed: file prefix changed")
            raise SessionError("stale session: the file prefix changed")

    def _stop_entry(self, entry: _Entry) -> None:
        for slot in entry.slots:
            if slot.text is not None:
                with suppress(SessionError, OSError):
                    entry.server.close_doc(slot)
        entry.server.stop()
        for slot in entry.slots:
            self._free(slot)

    @staticmethod
    def _free(slot: _Doc) -> None:
        token, slot.token = slot.token, None
        if token is not None:
            token.release()

    def _workers(self) -> int:
        return sum(len([s for s in e.slots if s.text is not None]) for e in self.entries.values())

    def _slots_total(self) -> int:
        return sum(len(e.slots) for e in self.entries.values())

    def _may_open(self, entry: _Entry, lane: str = "model", reserve: bool = False) -> str | None:
        """None when another worker fits; otherwise why not."""
        background = lane == "background"
        if background:
            if len(entry.lane_slots("background")) >= OTHER_WORKERS:
                return "slots"
        else:
            name = str(entry.project)
            primary = any(name == lease["primary"] for lease in self.leases.values())
            held = any(name in hold["projects"] for hold in self.holds.values())
            limit = PRIMARY_MAX_WORKERS if primary or held or self._is_adhoc(entry) else PRIMARY_MIN_WORKERS
            if len(entry.lane_slots("model")) >= limit:
                return "slots"
        free, _ = self.mem_fn()
        if free is not None and free - entry.worker_gb < RESERVE_GB:
            return f"memory ({free:.1f} GB available)"
        if reserve:
            token = self.budget.acquire(background)
            if token is None:
                return f"machine workers ({self.budget.limit} open across runs)"
            self._reserved = token
        elif not self.budget.available(background):
            return f"machine workers ({self.budget.limit} open across runs)"
        return None

    def _new_slot(self, entry: _Entry, lane: str) -> tuple[_Doc | None, str | None]:
        """A new busy slot in `lane`, or (None, why not). Caller holds `entry.condition` and `self.lock`."""
        blocked = self._may_open(entry, lane, reserve=True)
        if blocked is not None:
            return None, blocked
        self.counter += 1
        slot = entry.server.doc((entry.project / "ArenaScratch" / f"Session{self.counter}.lean").as_uri())
        slot.busy = True
        slot.lane = lane
        slot.token, self._reserved = self._reserved, None
        entry.slots.append(slot)
        return slot, None

    def _acquire(self, entry: _Entry, timeout: float, lane: str = "model", header: str | None = None) -> _Doc:
        """A worker of `lane`, waiting up to `timeout` seconds for one (first come, first served). Waiting in line
        is not part of any check's own timeout."""
        started = time.monotonic()
        deadline = started + timeout
        ticket = object()
        with entry.condition:
            queue = entry.queues[lane]
            queue.append(ticket)
            try:
                while True:
                    if not entry.server.alive():
                        raise SessionError("Lean server crashed")
                    mine = entry.lane_slots(lane)
                    if queue[0] is ticket:
                        idle = [slot for slot in mine if not slot.busy]
                        if idle:
                            matching = [slot for slot in idle if header is not None and slot.header == header]
                            slot = max(matching or idle, key=lambda s: s.used)
                            slot.busy = True
                            self._waited(entry, lane, started)
                            return slot
                        with self.lock:
                            slot, blocked = self._new_slot(entry, lane)
                            if slot is not None:
                                opened = (len(entry.lane_slots(lane)), self._workers())
                        if slot is not None:
                            _log(
                                f"worker open {entry.project.name} slot {opened[0]}, {opened[1]} workers total"
                                + (f" ({lane} lane)" if lane != "model" else "")
                            )
                            self._waited(entry, lane, started)
                            return slot
                        if blocked != "slots" and not mine:
                            if self._evict_background(entry) or self._evict_unleased(entry):
                                continue
                            assert blocked is not None
                            self._refused(entry, blocked)
                            raise SessionError(f"no room for a Lean worker: {blocked}")
                    if self.closing:
                        raise SessionError("session closing")
                    left = deadline - time.monotonic()
                    if left <= 0:
                        _log(f"timeout {entry.project.name}: no {lane} worker free within {timeout:.0f} s")
                        raise SessionError(
                            "every Lean worker was busy for too long"
                            if lane == "model"
                            else "the background Lean worker was busy for too long"
                        )
                    entry.condition.wait(min(left, 1.0))
            finally:
                queue.remove(ticket)
                entry.condition.notify_all()

    @staticmethod
    def _waited(entry: _Entry, lane: str, started: float) -> None:
        waited = time.monotonic() - started
        if waited > QUEUE_LOG_S:
            _log(f"{entry.project.name}: waited {waited:.0f} s for a {lane} worker")

    def _refused(self, entry: _Entry, blocked: str) -> None:
        _log(f"refused {entry.project.name}: no room for a Lean worker: {blocked}; {self._workers()} workers open")
        if blocked.startswith("memory"):
            with suppress(OSError):
                (self.directory / WAITING_NAME).touch()  # this session's own directory, never another's

    def _evict_background(self, keep: _Entry) -> bool:
        """Close the longest-idle background worker of another project, never a busy or model worker."""
        with self.lock:
            idle = [
                (slot.used, other, slot)
                for other in self.entries.values()
                if other is not keep
                for slot in other.slots
                if not slot.busy and slot.text is not None and slot.lane == "background"
            ]
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
                self._free(slot)
                _log(f"background worker evicted from {other.project.name} to make room for {keep.project.name}")
            finally:
                other.condition.release()
            return True

    def _evict_unleased(self, keep: _Entry) -> bool:
        """Close the longest-idle model worker of a project no running run uses as its primary toolchain (a pre-warm
        or hold for a row that has not started), so a starting run is never refused while such workers sit idle."""
        with self.lock:
            primaries = {lease["primary"] for lease in self.leases.values()}
            idle = [
                (slot.used, other, slot)
                for other in self.entries.values()
                if other is not keep and str(other.project) not in primaries
                for slot in other.slots
                if not slot.busy and slot.text is not None
            ]
            if not idle:
                return False
            _, other, slot = min(idle, key=lambda item: item[0])
            if not other.condition.acquire(blocking=False):
                return False
            try:
                if slot.busy:
                    return False
                other.server.close_doc(slot)
                other.slots.remove(slot)
                self._free(slot)
                _log(f"idle worker evicted from {other.project.name} to make room for {keep.project.name}")
            finally:
                other.condition.release()
            return True

    def _grow(self, entry: _Entry) -> None:
        """Open the model toolchain's remaining documents in the background.

        A batch of drafts needs one warm document each; opening them while the model is thinking
        means the first batch is as fast as the later ones. Memory decides how many fit."""
        with entry.condition:
            if (
                entry.growing
                or self.closing
                or len(entry.lane_slots("model")) >= PRIMARY_MAX_WORKERS
                or entry.last_text is None
            ):
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
                        slot, _blocked = self._new_slot(entry, "model")
                        if slot is None:
                            break
                        text, header_end = entry.last_text, entry.last_header_end
                        _log(f"worker open {entry.project.name} slot {len(entry.lane_slots('model'))} (pre-warm)")
                worker = threading.Thread(
                    target=self._warm, args=(entry, slot, text, header_end), daemon=True, name="lean-warm"
                )
                worker.start()
                workers.append(worker)
            for worker in workers:
                worker.join()
        finally:
            entry.growing = False

    def _warm(self, entry: _Entry, slot: _Doc, text: str, header_end: int | None = None) -> None:
        try:
            if header_end:
                entry.server.open_header(slot, text[:header_end])
            else:
                entry.server.check(slot, text, 600)
        except (SessionError, OSError):
            pass
        finally:
            self._release(entry, slot)

    def _release(self, entry: _Entry, slot: _Doc) -> None:
        with entry.condition:
            slot.busy = False
            slot.used = time.monotonic()
            if slot.stale:
                with suppress(SessionError, OSError):
                    entry.server.close_doc(slot)
                if slot in entry.slots:
                    entry.slots.remove(slot)
                self._free(slot)
            entry.condition.notify_all()

    # request
    def check(self, request: dict, then: Callable[[_Entry, _Doc], dict] | None = None) -> dict:
        """One check. `then` runs on the same worker while it is still held, after a check that did not time out;
        its fields are added to the reply."""
        if request.get("protocol") != PROTOCOL:
            return {"ok": False, "reason": "protocol mismatch"}
        project = Path(request["project"]).resolve()
        key = request["fingerprint"]
        if key.get("code") != code_sha():
            return {"ok": False, "stale": True, "reason": "stale session: the evaluator changed since the run started"}
        timeout = float(request.get("timeout", 180))
        lane = "background" if request.get("lane") == "background" else "model"
        if request.get("lane") == "batch":
            return self._batch_check(request, project, timeout)
        header_end = request.get("header_end")
        header_end = header_end if isinstance(header_end, int) and 0 < header_end <= len(request["text"]) else None
        try:
            entry = self._entry(project, key)
            self._guard_prefix(entry, request)
            lane = self._lane(project, entry, lane)
            # The wait for a worker has its own limit; the check's timeout starts once the worker is held.
            queue = MODEL_QUEUE_TIMEOUT if lane == "model" else timeout + OPEN_TIMEOUT
            slot = self._acquire(entry, queue, lane, request["text"][:header_end] if header_end else None)
        except SessionError as error:
            return {"ok": False, "stale": str(error).startswith("stale"), "reason": str(error)}
        except OSError as error:
            return {"ok": False, "reason": f"cannot start Lean: {error}"}
        try:
            fresh = slot.text is None
            slot.display = request["display"]
            outcome = entry.server.check(slot, request["text"], timeout, header_end, run_id=request.get("run_id"))
            extra = then(entry, slot) if then is not None and not outcome.get("timeout") else {}
        except SessionError as error:
            return {"ok": False, "reason": str(error)}
        finally:
            self._release(entry, slot)
        if outcome.get("timeout"):
            _log(
                f"timeout {entry.project.name}: check ran past {timeout:.1f} s ({lane} lane"
                + (", worker kept warm)" if outcome.get("warm_kept") else ", worker closed)")
            )
            return {
                "ok": True,
                "timeout": True,
                "warm_kept": bool(outcome.get("warm_kept")),
                "header_seconds": outcome.get("header_seconds"),
                "partial": outcome.get("partial", []),
                "progress_line": outcome.get("progress_line"),
                "partial_output": render(outcome.get("partial", []), request["text"], request["display"])[1],
                "lane": lane,
            }
        returncode, text = render(outcome["diagnostics"], request["text"], request["display"])
        self._measure(entry)
        if lane == "model":
            entry.last_text = request["text"]
            entry.last_header_end = header_end
            if self._is_primary(project) or self._is_held(project) or self._is_adhoc(entry):
                self._grow(entry)
        return {
            "ok": True,
            "returncode": returncode,
            "output": text,
            "seconds": outcome["seconds"],
            "new_worker": fresh,
            "header_seconds": outcome.get("header_seconds"),
            "lane": lane,
            "changed_from_line": outcome.get("changed_from_line"),
            "unchanged": bool(outcome.get("unchanged")),
            "messages": len(outcome["diagnostics"]),
            **extra,
        }

    def _batch_check(self, request: dict, project: Path, timeout: float) -> dict:
        """Use the REPL only for supported, unmeasured whole-proof checks; preserve LSP as fallback."""
        from arena import lean_repl

        header_end = request.get("header_end")
        header = (
            request["text"][:header_end]
            if isinstance(header_end, int) and 0 < header_end <= len(request["text"])
            else ""
        )
        toolchain = str(request.get("toolchain", ""))
        metadata = lean_repl.repl_dir(toolchain) / "build.json" if toolchain else None
        supported = metadata is not None and metadata.is_file()
        if supported:
            try:
                supported = bool(json.loads(metadata.read_text()).get("ok"))
            except (OSError, ValueError):
                supported = False
        if (
            lean_repl.REPL_ENABLED
            and supported
            and header
            and not request.get("measure")
            and not request.get("per_tactic")
        ):
            try:
                result = self.repl.check(
                    project,
                    toolchain,
                    header,
                    request["text"][header_end:],
                    request["display"],
                    timeout,
                    verification=lean_repl.ReplPool.verification_drafts(str(request.get("row", ""))),
                )
                return {**result, "engine": "repl", "lane": "batch"}
            except (lean_repl.ReplError, SessionError, OSError, ValueError) as error:
                fallback = {"fallback": "repl"}
                _log(f"REPL batch fallback for {project.name}: {error}")
            else:
                fallback = {}
        else:
            fallback = {}
        reply = self.check({**request, "lane": "background"})
        return {**reply, "engine": "lsp", "lane": "background", **fallback}

    def goal(self, request: dict) -> dict:
        """The check's reply plus the goals at a position, asked on the worker that just checked the text."""
        timeout = float(request.get("timeout", 180))

        def ask(entry: _Entry, slot: _Doc) -> dict:
            position = _position(request["text"], request["position"]["line"], request["position"]["column"])
            params = {"textDocument": {"uri": slot.uri}, "position": position}
            try:
                plain = entry.server._request("$/lean/plainGoal", params, timeout).get("result") or {}
                term = entry.server._request("$/lean/plainTermGoal", params, timeout).get("result") or {}
            except TimeoutError:
                return {"timeout": True, "warm_kept": True, "goals": [], "rendered": None, "term_goal": None}
            return {"goals": plain.get("goals") or [], "rendered": plain.get("rendered"), "term_goal": term.get("goal")}

        return self.check(request, then=ask)

    def try_snippets(self, request: dict) -> dict:
        if request.get("protocol") != PROTOCOL:
            return {"ok": False, "reason": "protocol mismatch"}
        if request.get("fingerprint", {}).get("code") != code_sha():
            return {"ok": False, "stale": True, "reason": "stale session: the evaluator changed since the run started"}
        snippets = request.get("snippets") or []
        if not isinstance(snippets, list) or not 1 <= len(snippets) <= TRY_MAX_SNIPPETS:
            return {"ok": False, "reason": f"try accepts 1 to {TRY_MAX_SNIPPETS} snippets"}
        project = Path(request["project"]).resolve()
        lane = "background" if request.get("lane") == "background" else "model"
        try:
            entry = self._entry(project, request["fingerprint"])
            self._guard_prefix(entry, request)
            lane = self._lane(project, entry, lane)
            hole = request["hole"]
            header_end = request.get("header_end")
            header = request["text"][:header_end] if isinstance(header_end, int) else None
            slot = self._acquire(entry, MODEL_QUEUE_TIMEOUT, lane, header)
        except (SessionError, OSError) as error:
            return {"ok": False, "stale": str(error).startswith("stale"), "reason": str(error)}
        results = []
        fresh = slot.text is None
        header_seconds = None
        try:
            hole = request["hole"]
            for snippet in snippets:
                variant = _replace_hole(request["text"], hole, snippet)
                started = time.monotonic()
                outcome = entry.server.check(slot, variant, float(request.get("timeout", 180)), header_end)
                if outcome.get("timeout"):
                    header_seconds = header_seconds or outcome.get("header_seconds")
                    results.append({"timeout": True, "seconds": round(time.monotonic() - started, 3)})
                    continue
                header_seconds = header_seconds or outcome.get("header_seconds")
                code, output = render(outcome["diagnostics"], variant, request["display"])
                end_text = (
                    "".join(variant.splitlines(keepends=True)[: hole["line"]])
                    + variant.splitlines(keepends=True)[hole["line"]][: hole["column"]]
                    + snippet
                )
                position = _position(end_text, hole["line"] + snippet.count("\n"), len(snippet.rsplit("\n", 1)[-1]))
                try:
                    reply = (
                        entry.server._request(
                            "$/lean/plainGoal",
                            {"textDocument": {"uri": slot.uri}, "position": position},
                            float(request.get("timeout", 180)),
                        ).get("result")
                        or {}
                    )
                    goals_after = reply.get("rendered") if reply.get("goals") else None
                except TimeoutError:
                    results.append({"timeout": True, "seconds": round(time.monotonic() - started, 3)})
                    continue
                results.append(
                    {
                        "returncode": code,
                        "output": output,
                        "goals_after": goals_after,
                        "seconds": round(time.monotonic() - started, 3),
                        "timeout": False,
                    }
                )
            self._measure(entry)
            return {"ok": True, "results": results, "lane": lane, "new_worker": fresh, "header_seconds": header_seconds}
        except (SessionError, OSError) as error:
            return {"ok": False, "stale": str(error).startswith("stale"), "reason": str(error)}
        finally:
            self._release(entry, slot)

    def _warm_unwaited(self, request: dict) -> None:
        """A warm-up nobody waits for: its reply is dropped, so a failure goes to the service log."""
        reply = self.warm(request)
        if not reply.get("ok") or reply.get("failed"):
            _log(
                f"background warm-up {Path(request['project']).name} failed: "
                f"{reply.get('reason') or '; '.join(map(str, reply.get('failed') or []))}"
            )

    def warm(self, request: dict) -> dict:
        """Open up to `slots` model-lane workers on one project, each loaded with the header only, in parallel.
        With `"lane": "background"` it warms that toolchain's background worker (one) instead."""
        if request.get("protocol") != PROTOCOL:
            return {"ok": False, "reason": "protocol mismatch"}
        if request.get("wait", True) is False:
            threading.Thread(
                target=self._warm_unwaited, args=({**request, "wait": True},), daemon=True, name="lean-background-warm"
            ).start()
            return {"ok": True, "started": True}
        project = Path(request["project"]).resolve()
        key = request["fingerprint"]
        if key.get("code") != code_sha():
            return {"ok": False, "stale": True, "reason": "stale session: the evaluator changed since the run started"}
        text, header_end = request["text"], request.get("header_end")
        if not isinstance(header_end, int) or not 0 < header_end <= len(text):
            return {"ok": False, "reason": "warm needs a header_end inside the text"}
        header = text[:header_end]
        timeout = float(request.get("timeout", OPEN_TIMEOUT))
        try:
            entry = self._entry(project, key)
            self._guard_prefix(entry, request)
        except SessionError as error:
            return {"ok": False, "stale": str(error).startswith("stale"), "reason": str(error)}
        except OSError as error:
            return {"ok": False, "reason": f"cannot start Lean: {error}"}
        lane = self._lane(project, entry, request.get("lane", "model"))
        allowed = OTHER_WORKERS if lane == "background" else PRIMARY_MAX_WORKERS
        wanted = max(0, min(int(request.get("slots", 1)), allowed))
        if lane == "model":
            entry.last_text, entry.last_header_end = text, header_end
        seconds: list[float] = []
        failed: list[str] = []
        lock = threading.Lock()
        threads: list[threading.Thread] = []
        ready = 0

        def open_one(slot: _Doc, number: int) -> None:
            started = time.monotonic()
            try:
                took = entry.server.open_header(slot, header, timeout)
                _log(f"header open run={request.get('run_id') or 'ad-hoc'} {Path(slot.uri).name}: {took:.1f} s")
                _log(f"warm {project.name} slot {number} ready in {took:.1f} s")
                with lock:
                    seconds.append(took)
            except (SessionError, OSError) as error:
                _log(f"warm {project.name} slot {number} failed after {time.monotonic() - started:.1f} s: {error}")
                with lock:
                    failed.append(str(error)[:200])
                with entry.condition:
                    if slot in entry.slots:
                        entry.slots.remove(slot)
                    self._free(slot)
            finally:
                self._release(entry, slot)

        with entry.condition:
            ready = len([s for s in entry.lane_slots(lane) if s.text is not None])
            while len(entry.lane_slots(lane)) < wanted:
                with self.lock:
                    slot, blocked = self._new_slot(entry, lane)
                if slot is None:
                    if blocked is not None and blocked != "slots":
                        self._refused(entry, blocked)
                        failed.append(f"no room for a Lean worker: {blocked}")
                    break
                number = len(entry.lane_slots(lane))
                _log(f"warm {project.name} slot {number} opening" + (" (background lane)" if lane != "model" else ""))
                slot.header = header
                slot.display = request.get("display")
                thread = threading.Thread(target=open_one, args=(slot, number), daemon=True, name="lean-warm-op")
                threads.append(thread)
                thread.start()
        for thread in threads:
            thread.join()
        return {
            "ok": True,
            "workers": ready + len(seconds),
            "seconds": sorted(seconds),
            "failed": failed,
            "allowed": allowed,
        }

    def _measure(self, entry: _Entry) -> None:
        opened = len([s for s in entry.slots if s.text is not None])
        if opened and entry.worker_gb == WORKER_GB:
            used = sum(self.pss_fn(entry.server.pgid).values())
            if used:
                entry.worker_gb = max(0.5, used / opened)

    def status(self) -> dict:
        with self.lock:
            leases = {key: dict(value) for key, value in self.leases.items()}
            holds = {key: dict(value) for key, value in self.holds.items()}
            entries = list(self.entries.values())
        # /proc is read outside the lock, once per server: a status call must stay quick while the service is busy
        trees = {id(entry): process_tree(entry.server.pgid) for entry in entries}
        available, swap = self.mem_fn()
        external = self.external_fn({pid for tree in trees.values() for pid in tree})
        servers = []
        for entry in entries:
            readings = self.pss_fn(entry.server.pgid)
            lanes = {slot.uri: slot.lane for slot in list(entry.slots) if slot.text is not None}
            workers = [
                {"pid": pid, "gb": round(gb, 3), "lane": lanes.get(self.document_fn(pid) or "")}
                for pid, gb in sorted(readings.items())
            ]
            servers.append(
                {
                    "project": str(entry.project),
                    "workers": workers,
                    "busy": len([s for s in entry.slots if s.busy]),
                    "gb": round(sum(readings.values()), 2),
                    "pgid": entry.server.pgid,
                    "pids": trees[id(entry)],
                    "closes_in_s": None
                    if entry.unreferenced_since is None
                    else max(0, round(RELEASE_GRACE_S - (time.monotonic() - entry.unreferenced_since))),
                }
            )
        return {
            "pid": os.getpid(),
            "protocol": PROTOCOL,
            "code": code_sha(),
            "leases": leases,
            "holds": holds,
            "servers": servers,
            "repls": [
                {
                    "project": item.project,
                    "pid": item.process.pgid,
                    "gb": round(self.repl.pss_fn(item.process.pgid), 3) if item.process.pgid else 0.0,
                    "busy": item.busy,
                }
                for item in list(self.repl.items.values())
            ],
            "mem_available_gb": available,
            "swap_used_gb": swap,
            "external_lean_gb": round(sum(external.values()), 3),
        }

    def log_pss(self) -> None:
        now = time.monotonic()
        if now - self.last_pss_log < PSS_LOG_S:
            return
        self.last_pss_log = now
        status = self.status()
        if not status["servers"] or not any(server["workers"] for server in status["servers"]):
            return
        path = self.directory / "pss.jsonl"
        with suppress(OSError):
            if path.exists() and path.stat().st_size > PSS_LOG_MAX_BYTES:
                os.replace(path, path.with_name("pss.jsonl.1"))
            row = {key: status[key] for key in ("mem_available_gb", "swap_used_gb", "external_lean_gb", "servers")}
            row["ts"] = time.time()
            with path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            _log(f"Lean PSS: external {row['external_lean_gb']:.2f} GB; available {row['mem_available_gb']} GB")

    def reap_idle(self) -> None:
        """Close a project RELEASE_GRACE_S after its last lease or hold ended, or an ad hoc one after ADHOC_IDLE_S
        without a request. A busy project closes on the first tick after its request ends."""
        self.reap_dead()
        now = time.monotonic()
        with self.lock:
            entries = list(self.entries.values())
        for entry in entries:
            if entry.was_referenced:
                due = entry.unreferenced_since is not None and now - entry.unreferenced_since >= RELEASE_GRACE_S
            else:
                due = now - entry.used >= ADHOC_IDLE_S
            if due:
                self._close_unreferenced(entry)

    def should_exit(self) -> bool:
        with self.lock:
            empty = not self.entries and not self.leases and not self.holds
            if not empty:
                self.last_active = time.monotonic()
            return empty and time.monotonic() - self.last_active >= SERVICE_LINGER_S

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
            self._stop_entry(entry)
        self.repl.close()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = json.loads(self.rfile.readline())
        except ValueError:
            return
        session = cast(_Server, self.server).session
        session.last_active = time.monotonic()  # any client keeps a lingering service from exiting under it
        op = request.get("op")
        try:
            if op == "check":
                reply = session.check(request)
            elif op == "goal":
                reply = session.goal(request)
            elif op == "try":
                reply = session.try_snippets(request)
            elif op == "warm":
                reply = session.warm(request)
            elif op == "status":
                reply = {"ok": True, **session.status()}
            elif op == "lease":
                reply = session.lease(request)
            elif op == "release":
                reply = session.release(str(request.get("run_id", "")))
            elif op == "hold":
                reply = session.hold(request)
            elif op == "unhold":
                reply = session.unhold(str(request.get("owner", "")))
            elif op == "shutdown":
                reply = {"ok": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                reply = {"ok": False, "reason": f"unknown operation {op!r}"}
        except Exception as error:  # a bug here must degrade to the cold path, never to a wrong answer
            reply = {"ok": False, "reason": f"session error: {type(error).__name__}: {error}"[:300]}
        with suppress(OSError):
            self.wfile.write(json.dumps(reply).encode() + b"\n")


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True
    session: Session


def socket_path(directory: Path | None = None) -> Path:
    path = (directory or service_dir()) / SOCKET_NAME
    if len(os.fsencode(path)) > SOCKET_LIMIT:
        raise SessionError(f"Lean service socket path exceeds {SOCKET_LIMIT} bytes: {path}")
    return path


def _probe(path: Path, timeout: float) -> dict | str:
    """The service's status reply, "absent" when nothing listens on the socket, or "busy" when something
    listens but gives no answer in time (a busy service must never be mistaken for a dead one)."""
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(timeout)
            connection.connect(str(path))
            connection.sendall(json.dumps({"op": "status", "protocol": PROTOCOL}).encode() + b"\n")
            line = connection.makefile("rb").readline()
    except (FileNotFoundError, ConnectionRefusedError):
        return "absent"
    except OSError:
        return "busy"
    try:
        reply = json.loads(line) if line else None
    except ValueError:
        return "busy"
    return reply if isinstance(reply, dict) and reply.get("ok") else "busy"


def _take_start_lock(directory: Path, blocking: bool = True) -> IO[str] | None:
    """The service directory's start lock, held until the returned file is closed (None: someone else holds it).
    A client holds it while it finds or starts the service, and a service while it exits."""
    lock = (directory / LOCK_NAME).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        lock.close()
        return None
    return lock


def ensure_service(directory: Path | None = None, wait: float = 15.0) -> str:
    directory = directory or service_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = socket_path(directory)
    with cast(IO[str], _take_start_lock(directory)):
        deadline = time.monotonic() + wait
        status = _probe(path, 2.0)
        while status == "busy" and time.monotonic() < deadline:
            time.sleep(0.2)
            status = _probe(path, 2.0)
        if status == "busy":
            raise SessionError(f"the Lean service does not answer; see {directory / LOG_NAME}")
        if isinstance(status, dict):
            if status.get("protocol") == PROTOCOL and status.get("code") == code_sha():
                return str(path)
            if status.get("leases") or status.get("holds"):
                raise SessionError("the Lean service runs older code with live runs")
            request({"op": "shutdown", "protocol": PROTOCOL}, 2, str(path))
            stop_by = time.monotonic() + 20
            while _probe(path, 1.0) != "absent" and time.monotonic() < stop_by:
                time.sleep(0.05)
            if _probe(path, 1.0) != "absent":
                raise SessionError("old Lean service did not stop")
        path.unlink(missing_ok=True)  # nothing listens on it
        log = (directory / LOG_NAME).open("ab")
        try:
            subprocess.Popen(
                [sys.executable, "-m", "arena.lean_session", "serve", "--service-dir", str(directory)],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            status = _probe(path, 0.5)
            if isinstance(status, dict) and status.get("code") == code_sha():
                return str(path)
            time.sleep(0.05)
        raise SessionError(f"Lean service did not become ready; see {directory / LOG_NAME}")


def serve(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    path = socket_path(directory)
    if isinstance(_probe(path, 2.0), dict):
        raise SessionError(f"a Lean service already answers on {path}")
    path.unlink(missing_ok=True)
    session = Session(directory)
    server = _Server(str(path), _Handler)
    server.session = session
    own_socket = path.stat().st_ino
    info = directory / INFO_NAME
    started = time.time()
    exiting: list[IO[str]] = []  # the start lock, held from the linger decision until the socket is gone

    def write_info() -> None:
        temporary = info.with_name(f"{INFO_NAME}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "socket": str(path),
                    "code": code_sha(),
                    "protocol": PROTOCOL,
                    "pgids": session.pgids(),
                    "pids": session.pids(),
                    "started": started,
                }
            )
            + "\n"
        )
        os.replace(temporary, info)  # readers never see a half-written file

    def stop(*_args) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, stop)

    def socket_gone() -> bool:
        """True once this service's socket (or its directory) is deleted or replaced: no client can reach it again,
        and the linger exit below could never take the start lock in a deleted directory."""
        try:
            return path.stat().st_ino != own_socket
        except OSError:
            return True

    def watch() -> None:
        while not session.closing:
            if socket_gone():
                _log(f"service socket {path} is gone; exiting")
                stop()
                return
            session.reap_idle()
            session.log_pss()
            with suppress(OSError):
                write_info()
            if session.should_exit():
                # Exit only while no client is starting or finding the service (they hold the start lock).
                gate = _take_start_lock(directory, blocking=False)
                if gate is not None and session.should_exit():
                    exiting.append(gate)
                    stop()
                    return
                if gate is not None:
                    gate.close()
            time.sleep(1.0)

    write_info()
    _log(f"service up (pid {os.getpid()}, protocol {PROTOCOL})")
    threading.Thread(target=watch, daemon=True, name="watch").start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        session.shutdown()
        server.server_close()
        with suppress(OSError):
            if path.stat().st_ino == own_socket:  # never remove a newer service's socket
                path.unlink()
        with suppress(OSError, ValueError):
            if json.loads(info.read_text()).get("pid") == os.getpid():
                info.unlink()
        for gate in exiting:
            gate.close()
    return 0


def _is_service(pid: int, directory: Path) -> bool:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    words = [word.decode(errors="replace") for word in cmdline]
    return "arena.lean_session" in words and str(directory) in words


def stop_service(directory: Path | None = None, grace: float = 20.0) -> None:
    """Ask the service to shut down; if it does not, kill the pid recorded in service.json (after checking it is
    this directory's service), then any Lean process it recorded that outlived it."""
    directory = directory or service_dir()
    path, info_path = socket_path(directory), directory / INFO_NAME
    try:
        info = json.loads(info_path.read_text())
    except (OSError, ValueError):
        info = {}
    if _probe(path, 2.0) != "absent":
        request({"op": "shutdown", "protocol": PROTOCOL}, 2, str(path))
        deadline = time.monotonic() + grace
        while _probe(path, 1.0) != "absent" and time.monotonic() < deadline:
            time.sleep(0.05)
    pid = info.get("pid")
    if isinstance(pid, int) and running(pid) and _is_service(pid, directory):
        for number, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, number)
            deadline = time.monotonic() + wait
            while running(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            if not running(pid):
                break
    for lean in info.get("pids", []):
        with suppress(OSError):
            if Path(f"/proc/{lean}/comm").read_text().strip() in ("lean", "lake"):
                os.kill(int(lean), signal.SIGKILL)
    if not (isinstance(pid, int) and running(pid)):
        if _probe(path, 1.0) == "absent":
            path.unlink(missing_ok=True)
        info_path.unlink(missing_ok=True)


# -- client --------------------------------------------------------------------------------------


def request(payload: dict, timeout: float, path: str | None = None) -> dict | None:
    """One round trip to the service; None when no socket is configured."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("serve")
    run.add_argument("--service-dir", type=Path, required=True)
    args = parser.parse_args()
    return serve(args.service_dir)


if __name__ == "__main__":
    raise SystemExit(main())
