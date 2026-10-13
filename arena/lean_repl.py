"""Lean REPL builds, process wrappers, and the shared whole-proof process pool."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext, suppress
from dataclasses import dataclass, field
from pathlib import Path

from arena import engine, lean_session

ROOT = Path(__file__).resolve().parents[1]


def _adoption_record() -> bool:
    try:
        return bool(json.loads((ROOT / "benchmark/derived/repl-compare.json").read_text()).get("adopt"))
    except (OSError, ValueError):
        return False


REPL_ENABLED = _adoption_record()
REPL_MAX_PROCESSES = 5
REPL_MAX_GB = 4.0


class ReplError(RuntimeError):
    pass


def repl_dir(toolchain: str) -> Path:
    return ROOT / "runs/cache/repl" / toolchain


def pickle_dir(toolchain: str) -> Path:
    return ROOT / "runs/cache/repl/pickles" / toolchain


def build(toolchain: str, log: Callable[[str], None] = print) -> Path:
    """Build the matching upstream tag, recording unsupported toolchains instead of raising."""
    directory = repl_dir(toolchain)
    metadata = directory / "build.json"
    directory.mkdir(parents=True, exist_ok=True)
    tag = toolchain
    override = False
    started = time.monotonic()
    try:
        if toolchain == "v4.29.1":
            tag, override = "v4.29.0", True
        if not (directory / ".git").exists():
            clone_dir = directory.with_name(directory.name + ".clone")
            shutil.rmtree(clone_dir, ignore_errors=True)
            done = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    tag,
                    "https://github.com/leanprover-community/repl",
                    str(clone_dir),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if done.returncode:
                raise ReplError(done.stderr.strip() or done.stdout.strip())
            shutil.rmtree(directory, ignore_errors=True)
            clone_dir.rename(directory)
        if override:
            (directory / "lean-toolchain").write_text(f"leanprover/lean4:{toolchain}\n")
        done = subprocess.run(["lake", "build"], cwd=directory, capture_output=True, text=True, timeout=1800)
        binary = directory / ".lake/build/bin/repl"
        if done.returncode or not binary.is_file():
            raise ReplError(done.stderr[-2000:].strip() or done.stdout[-2000:].strip() or "repl binary missing")
        result = {
            "tag": tag,
            "toolchain": toolchain,
            "built_with_override": override,
            "ok": True,
            "seconds": round(time.monotonic() - started, 3),
        }
        metadata.write_text(json.dumps(result, indent=2) + "\n")
        log(f"{toolchain}: ok ({result['seconds']}s)")
        return binary
    except (OSError, subprocess.SubprocessError, ReplError) as error:
        metadata.write_text(
            json.dumps(
                {
                    "tag": tag,
                    "toolchain": toolchain,
                    "built_with_override": override,
                    "ok": False,
                    "error": str(error),
                    "seconds": round(time.monotonic() - started, 3),
                },
                indent=2,
            )
            + "\n"
        )
        log(f"{toolchain}: failed ({error})")
        return directory / ".lake/build/bin/repl"


def smoke(toolchain: str, project: Path | None = None) -> dict:
    """Compare the reference Core proof against the LSP lane for the legacy v4.29.1 tag."""
    row = engine.problem("Core.InitsUpdatesComm")
    version, commit = next(pair for pair in engine.versions(row) if pair[0] == toolchain)
    project = project or engine.workspace(row, version, commit)
    built = engine.candidate_file(row, row["src"], version, commit)
    header, body = built["text"][: built["head"]], built["text"][built["head"] :]
    started = time.monotonic()
    direct = engine.run_lean(row, project, built["text"], timeout=600, prefix_end=built["head"], lane="background")
    process = ReplProcess(project, toolchain)
    try:
        process.start()
        opened = process.run(header, timeout=lean_session.OPEN_TIMEOUT)
        checked = process.run(body, int(opened.get("env", 0)), 600)
        repl_pass = not any(message.get("severity") == "error" for message in checked.get("messages", []))
        lsp_pass = direct is not None and direct[0] == 0
        return {"ok": repl_pass == lsp_pass and repl_pass, "seconds": round(time.monotonic() - started, 3)}
    finally:
        process.stop()


def header_snapshot_trial(project: Path, header: str, timeout: float = 180) -> dict:
    """Measure v4.32 incremental header save/load and compare diagnostics to a plain compile."""
    direct = engine._lean_command(str(project))
    if direct is None:
        return {"available": False, "reason": "Lean command unavailable"}
    binary, env = direct
    try:
        help_text = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "reason": str(error)}
    if "--incr-header-save=file" not in help_text or "--incr-load=file" not in help_text:
        return {"available": False, "reason": "not available"}
    with tempfile.TemporaryDirectory(prefix="arena-header-snapshot-") as scratch:
        source = Path(scratch) / "Header.lean"
        snapshot = Path(scratch) / "header.snap"
        source.write_text(header, encoding="utf-8")

        def run(*flags: str) -> tuple[float, str]:
            started = time.monotonic()
            done = subprocess.run(
                [binary, *flags, str(source)],
                cwd=project,
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if done.returncode:
                raise ReplError(done.stderr.strip() or done.stdout.strip())
            return time.monotonic() - started, (done.stdout + done.stderr).strip()

        try:
            cold, _ = run(f"--incr-header-save={snapshot}")
            loaded, loaded_output = run(f"--incr-load={snapshot}")
            _plain, plain_output = run()
        except (OSError, subprocess.SubprocessError, ReplError) as error:
            return {"available": True, "error": str(error)}
        return {
            "available": True,
            "cold_import_s": round(cold, 3),
            "load_s": round(loaded, 3),
            "diagnostics_equal": loaded_output == plain_output,
        }


def compare_engines(engine_choice: str = "both", timeout: float = 180) -> dict:
    """Compare the same 20 drafts through a private LSP session and the REPL pool."""
    import tempfile

    from arena.cli import lean_bench, lean_load

    names = [
        *lean_bench.BENCHMARK_ROWS[:3],
        "Binius.BinaryBasefold.fold_advances_evaluation_poly",
    ]
    benchmark_rows = {
        json.loads(line)["name"]: json.loads(line) for line in engine.BENCHMARK.read_text(encoding="utf-8").splitlines()
    }
    phys_name = next((row["name"] for row in benchmark_rows.values() if row["source"].lower() == "physlib"), None)
    if phys_name:
        names.append(phys_name)
    rows = {}
    adopts_by_toolchain: dict[str, list[bool]] = {}
    for name in names:
        row = benchmark_rows.get(name)
        if row is None:
            continue
        versions = engine.versions(row)
        selected = versions
        rows[name] = {}
        for toolchain, commit in selected:
            binary = repl_dir(toolchain) / ".lake/build/bin/repl"
            metadata_path = repl_dir(toolchain) / "build.json"
            try:
                supported = binary.is_file() and bool(json.loads(metadata_path.read_text()).get("ok"))
            except (OSError, ValueError):
                supported = False
            if engine_choice != "lsp" and not supported:
                rows[name][toolchain] = {"unsupported": True}
                adopts_by_toolchain.setdefault(toolchain, []).append(False)
                continue
            project = engine.workspace(row, toolchain, commit)
            with tempfile.TemporaryDirectory(prefix="arena-repl-bench-") as scratch:
                session = lean_session.Session(
                    Path(scratch), budget=lean_session.WorkerBudget(Path(scratch) / "tokens")
                )
                pool = ReplPool(
                    pss_fn=lambda pid: lean_session.pid_pss_gb(pid) or 0.0,
                    opening=session.budget.opening,
                )
                lsp_records, repl_records = [], []
                disagreements, heartbeat_diffs = 0, []
                drafts = [(kind, serial) for serial, (kind, _measured) in enumerate(lean_bench.plan_checks(5))]
                additional_start = len(drafts)
                drafts.extend(
                    (kind, serial + additional_start)
                    for serial, kind in enumerate(("reference", "edit", "error", "sorry") * 5)
                )
                for kind, serial in drafts:
                    if kind.startswith("splice_"):
                        proof = lean_bench.make_splice(row, kind.removeprefix("splice_"), serial) or row["src"]
                    else:
                        proof = lean_load.make_proof(kind, row, serial, timeout)
                    built = engine.candidate_file(row, proof, toolchain, commit)
                    wrapped = built["text"][: built["head"]] + engine.HEARTBEAT_WRAPPER + built["text"][built["head"] :]
                    header = wrapped[: built["head"]]
                    body = wrapped[built["head"] :]
                    request = {
                        "protocol": lean_session.PROTOCOL,
                        "project": str(project),
                        "fingerprint": lean_session.fingerprint(project),
                        "display": engine.source_path(row),
                        "text": wrapped,
                        "header_end": len(header),
                        "timeout": timeout,
                        "lane": "background",
                    }
                    started = time.monotonic()
                    lsp = session.check(request)
                    lsp_records.append(
                        {
                            "seconds": lsp.get("seconds", time.monotonic() - started),
                            "passed": lsp.get("returncode") == 0,
                            "heartbeats": _heartbeat(lsp.get("output", "")),
                        }
                    )
                    if engine_choice != "lsp":
                        repl = pool.check(project, toolchain, header, body, engine.source_path(row), timeout)
                        repl_records.append(
                            {
                                "seconds": repl["seconds"],
                                "passed": repl["returncode"] == 0,
                                "heartbeats": _heartbeat(repl["output"]),
                                "pss_gb": repl["pss_gb"],
                                "header_seconds": repl["header_seconds"],
                                "unpickled": repl["unpickled"],
                                "pickle_bytes": repl["pickle_bytes"],
                            }
                        )
                        disagreements += lsp_records[-1]["passed"] != repl_records[-1]["passed"]
                        if lsp_records[-1]["heartbeats"] and repl_records[-1]["heartbeats"]:
                            a, b = lsp_records[-1]["heartbeats"], repl_records[-1]["heartbeats"]
                            heartbeat_diffs.append(abs(a - b) / max(a, b, 1))
                if engine_choice != "lsp":
                    pool.close_project(project)
                    reload_check = pool.check(project, toolchain, header, body, engine.source_path(row), timeout)
                    pss = max((item["pss_gb"] for item in repl_records), default=0)
                    entry = session.entries.get(str(project.resolve()))
                    lsp_pss = lean_session.pid_pss_gb(entry.server.pgid) if entry and entry.server.pgid else 0.0
                    lsp_times = [item["seconds"] for item in lsp_records]
                    repl_times = [item["seconds"] for item in repl_records]
                    adopted = (
                        disagreements == 0
                        and max(heartbeat_diffs, default=1) <= 0.05
                        and (lean_load.percentile(repl_times, 50) or 0.0)
                        <= (lean_load.percentile(lsp_times, 50) or 0.0) * 1.10
                        and (
                            reload_check["header_seconds"] <= repl_records[0]["header_seconds"] / 2
                            or pss < (lsp_pss or 0.0)
                        )
                    )
                    rows[name][toolchain] = {
                        "header_cold_s": repl_records[0]["header_seconds"],
                        "header_unpickle_s": reload_check["header_seconds"],
                        "check_p50": {
                            "lsp": lean_load.percentile(lsp_times, 50),
                            "repl": lean_load.percentile(repl_times, 50),
                        },
                        "check_p95": {
                            "lsp": lean_load.percentile(lsp_times, 95),
                            "repl": lean_load.percentile(repl_times, 95),
                        },
                        "pss_gb": {"lsp": lsp_pss, "repl": pss},
                        "pickle_bytes": repl_records[-1]["pickle_bytes"],
                        "disagreements": disagreements,
                        "max_heartbeat_difference": max(heartbeat_diffs, default=None),
                        "adopt": adopted,
                    }
                    adopts_by_toolchain.setdefault(toolchain, []).append(adopted)
                else:
                    lsp_times = [item["seconds"] for item in lsp_records]
                    rows[name][toolchain] = {
                        "check_p50": {"lsp": lean_load.percentile(lsp_times, 50)},
                        "check_p95": {"lsp": lean_load.percentile(lsp_times, 95)},
                        "adopt": False,
                    }
                pool.close()
                session.shutdown()
    toolchains = {toolchain: all(decisions) for toolchain, decisions in adopts_by_toolchain.items()}
    result = {"rows": rows, "toolchains": toolchains, "adopt": bool(toolchains) and all(toolchains.values())}
    output = ROOT / "benchmark/derived/repl-compare.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def _heartbeat(output: str) -> int | None:
    import re

    match = re.search(r"ARENA_HEARTBEATS (\d+)", output)
    return int(match.group(1)) if match else None


class ReplProcess:
    """Persistent JSON-line REPL process. A timed-out command invalidates the process."""

    def __init__(self, project: Path, toolchain: str, binary: Path | None = None):
        self.project, self.toolchain = project, toolchain
        self.binary = binary or repl_dir(toolchain) / ".lake/build/bin/repl"
        self.process: subprocess.Popen | None = None
        self.replies: queue.Queue = queue.Queue()
        self.pgid: int | None = None

    def start(self) -> None:
        if not self.binary.is_file():
            raise ReplError(f"REPL is not built for {self.toolchain}")
        direct = engine._lean_command(str(self.project))
        env = {**os.environ, **(direct[1] if direct else {})}
        self.process = subprocess.Popen(
            ["lake", "env", str(self.binary)],
            cwd=self.project,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        self.pgid = self.process.pid
        self.pss_fn: Callable[[int], float] = lambda _pid: 0.0
        self.over_limit = False
        threading.Thread(target=self._read, daemon=True, name="lean-repl-reader").start()

    def _observe_memory(self) -> None:
        if self.pgid is not None and self.pss_fn(self.pgid) > REPL_MAX_GB:
            self.over_limit = True

    def _read(self) -> None:
        assert self.process and self.process.stdout
        decoder = json.JSONDecoder()
        pending = ""
        for line in self.process.stdout:
            pending += line
            try:
                reply, end = decoder.raw_decode(pending.lstrip())
            except json.JSONDecodeError:
                continue
            if isinstance(reply, dict):
                self.replies.put(reply)
            else:
                self.replies.put(ReplError(f"invalid REPL reply: {pending[:200]!r}"))
            pending = pending.lstrip()[end:]
            if pending.strip():
                try:
                    reply, end = decoder.raw_decode(pending)
                    self.replies.put(reply)
                    pending = pending[end:]
                except json.JSONDecodeError:
                    pass
        self.replies.put(ReplError("REPL process exited"))

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def run(self, cmd: str, env: int | None = None, timeout: float = 180) -> dict:
        if not self.alive() or self.process is None or self.process.stdin is None:
            raise ReplError("REPL process is not running")
        request = {"cmd": cmd}
        if env is not None:
            request["env"] = env
        try:
            self.process.stdin.write(json.dumps(request) + "\n\n")
            self.process.stdin.flush()
            reply = self.replies.get(timeout=timeout)
            self._observe_memory()
        except (OSError, queue.Empty) as error:
            self.stop()
            raise ReplError("REPL command timed out" if isinstance(error, queue.Empty) else str(error)) from None
        if isinstance(reply, ReplError):
            raise reply
        return reply

    def pickle(self, env: int, path: Path, timeout: float = 180) -> dict:
        return self._request({"pickleTo": str(path), "env": env}, timeout)

    def unpickle(self, path: Path, timeout: float = 180) -> int:
        reply = self._request({"unpickleEnvFrom": str(path)}, timeout)
        return int(reply["env"])

    def _request(self, payload: dict, timeout: float) -> dict:
        if not self.alive() or self.process is None or self.process.stdin is None:
            raise ReplError("REPL process is not running")
        try:
            self.process.stdin.write(json.dumps(payload) + "\n\n")
            self.process.stdin.flush()
            reply = self.replies.get(timeout=timeout)
            self._observe_memory()
        except (OSError, queue.Empty) as error:
            self.stop()
            raise ReplError("REPL command timed out" if isinstance(error, queue.Empty) else str(error)) from None
        if isinstance(reply, ReplError):
            raise reply
        return reply

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, 15)
                process.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, 9)
            process.communicate()


def render_repl(messages: list[dict], header: str, display: str) -> tuple[int, str]:
    """Render REPL diagnostics in the same format as `lean_session.render`."""
    offset = header.count("\n")
    errors = False
    output = []
    for message in messages:
        severity = message.get("severity", "info")
        data = str(message.get("data", ""))
        if severity == "info":
            output.append(data)
            continue
        pos = message.get("pos") or {}
        line, column = int(pos.get("line", 1)) + offset, int(pos.get("column", 0))
        label = "error" if severity == "error" else "warning"
        errors |= severity == "error"
        output.append(f"{display}:{line}:{column}: {label}: {data}")
    return int(errors), "\n".join(output).strip()


@dataclass
class _Pooled:
    process: ReplProcess
    env: int
    project: str
    header: str
    used: float
    busy: bool = True
    command_lock: threading.Lock = field(default_factory=threading.Lock)
    header_seconds: float = 0.0
    unpickled: bool = False


class ReplPool:
    """Bounded LRU of imported-header environments shared by whole-proof checks."""

    def __init__(
        self,
        factory: Callable = ReplProcess,
        pss_fn: Callable | None = None,
        opening: Callable | None = None,
    ):
        self.factory, self.pss_fn = factory, pss_fn or (lambda _pid: 0.0)
        self.opening = opening or (lambda _need_gb, _timeout: nullcontext(0.0))
        self.items: dict[tuple[str, str], _Pooled] = {}
        self.lock = threading.RLock()

    @staticmethod
    def _hash(header: str) -> str:
        return hashlib.sha256(header.encode()).hexdigest()[:16]

    def _new(self, project: Path, toolchain: str, header: str, verification: tuple[str, str] | None = None) -> _Pooled:
        key = (str(project.resolve()), self._hash(header))
        if len(self.items) >= REPL_MAX_PROCESSES:
            idle = [(item.used, old_key, item) for old_key, item in self.items.items() if not item.busy]
            if not idle:
                raise ReplError("all REPL processes are busy")
            _, old_key, old = min(idle)
            old.process.stop()
            del self.items[old_key]
        process = self.factory(project, toolchain)
        started = time.monotonic()
        process.start()
        process.pss_fn = self.pss_fn
        pool = _Pooled(process, 0, str(project.resolve()), header, time.monotonic())
        pickle = pickle_dir(toolchain) / f"{key[1]}.olean"
        bad = pickle.with_suffix(".nopickle")
        if pickle.is_file() and not bad.exists():
            try:
                with self.opening(REPL_MAX_GB, lean_session.OPEN_TIMEOUT):
                    pool.env = process.unpickle(pickle)
                pool.unpickled = True
            except ReplError:
                bad.touch()
                with self.opening(REPL_MAX_GB, lean_session.OPEN_TIMEOUT):
                    reply = process.run(header, timeout=lean_session.OPEN_TIMEOUT)
                pool.env = int(reply.get("env", 0))
        if pool.unpickled and verification and not pickle.with_suffix(".verified").exists():
            try:
                verified = self._verify_pickle(process, pickle, header, pool.env, verification)
            except (ReplError, OSError, KeyError, ValueError):
                verified = False
            if not verified:
                bad.touch()
                pool.unpickled = False
            else:
                pickle.with_suffix(".verified").touch()
        if not pool.unpickled:
            with self.opening(REPL_MAX_GB, lean_session.OPEN_TIMEOUT):
                reply = process.run(header, timeout=lean_session.OPEN_TIMEOUT)
            pool.env = int(reply.get("env", 0))
            if not bad.exists():
                pickle.parent.mkdir(parents=True, exist_ok=True)
                process.pickle(pool.env, pickle, lean_session.OPEN_TIMEOUT)
        pool.header_seconds = round(time.monotonic() - started, 3)
        self.items[key] = pool
        return pool

    @staticmethod
    def _result(reply: dict) -> tuple[bool, list[dict]]:
        messages = reply.get("messages", [])
        passed = not any(message.get("severity") == "error" for message in messages)
        return passed, messages

    def _verify_pickle(
        self, process: ReplProcess, pickle: Path, header: str, loaded_env: int, drafts: tuple[str, str]
    ) -> bool:
        for index, body in enumerate(drafts):
            with self.opening(REPL_MAX_GB, lean_session.OPEN_TIMEOUT):
                fresh_env = int(process.run(header, timeout=lean_session.OPEN_TIMEOUT).get("env", 0))
            fresh_result = self._result(process.run(body, fresh_env, lean_session.OPEN_TIMEOUT))
            if index == 0:
                unpickled_env = loaded_env
            else:
                with self.opening(REPL_MAX_GB, lean_session.OPEN_TIMEOUT):
                    unpickled_env = process.unpickle(pickle)
            loaded_result = self._result(process.run(body, unpickled_env, lean_session.OPEN_TIMEOUT))
            if fresh_result != loaded_result:
                return False
        return True

    @staticmethod
    def verification_drafts(row_name: str) -> tuple[str, str] | None:
        """Return the reference and a failing whole-proof body for a benchmark row."""
        try:
            row = engine.problem(row_name)
        except (KeyError, ValueError, OSError):
            return None
        statement = row.get("statement", "")
        source = row.get("src", "")
        if not statement or not source.startswith(statement):
            return None
        return source, statement + " := by\n  exact arena_pickle_missing_name"

    def check(
        self,
        project: Path,
        toolchain: str,
        header: str,
        body: str,
        display: str,
        timeout: float,
        verification: tuple[str, str] | None = None,
    ) -> dict:
        key = (str(project.resolve()), self._hash(header))
        with self.lock:
            pool = self.items.get(key)
            if pool is None or not pool.process.alive():
                pool = self._new(project, toolchain, header, verification)
            pool.busy = True
        started = time.monotonic()
        try:
            with pool.command_lock:
                reply = pool.process.run(body, pool.env, timeout)
            messages = reply.get("messages", [])
            returncode, output = render_repl(messages, header, display)
            pss = self.pss_fn(pool.process.pgid) if pool.process.pgid is not None else 0.0
            return {
                "ok": True,
                "returncode": returncode,
                "output": output,
                "seconds": round(time.monotonic() - started, 3),
                "messages": messages,
                "pss_gb": pss,
                "env": reply.get("env", pool.env),
                "header_seconds": pool.header_seconds,
                "unpickled": pool.unpickled,
                "pickle_bytes": (
                    (pickle_dir(toolchain) / f"{key[1]}.olean").stat().st_size
                    if (pickle_dir(toolchain) / f"{key[1]}.olean").exists()
                    else None
                ),
            }
        except ReplError:
            with self.lock:
                pool.process.stop()
                self.items.pop(key, None)
            raise
        finally:
            with self.lock:
                pool.busy = False
                pool.used = time.monotonic()
                if (
                    not pool.process.alive()
                    or getattr(pool.process, "over_limit", False)
                    or (pool.process.pgid is not None and self.pss_fn(pool.process.pgid) > REPL_MAX_GB)
                ):
                    pool.process.stop()
                    self.items.pop(key, None)

    def close_project(self, project: Path | str) -> None:
        name = str(Path(project).resolve())
        with self.lock:
            for key, item in list(self.items.items()):
                if item.project == name:
                    item.process.stop()
                    del self.items[key]

    def close(self) -> None:
        with self.lock:
            items, self.items = list(self.items.values()), {}
        for item in items:
            item.process.stop()
