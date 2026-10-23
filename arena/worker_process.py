"""Owned RPC pipes and Linux process-group identity at the operating-system boundary."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from pathlib import Path


class ProcessInspector:
    def __init__(self, proc: Path = Path("/proc"), *, killpg=os.killpg):
        self.proc = proc
        self.killpg = killpg
        self._validated: dict[int, dict] = {}
        self._boot_id = None

    def _stat(self, pid: int) -> dict:
        raw = (self.proc / str(pid) / "stat").read_text()
        fields = raw[raw.rindex(")") + 2:].split()
        if self._boot_id is None:
            try:
                self._boot_id = (self.proc / "sys/kernel/random/boot_id").read_text().strip()
            except OSError as error:
                raise ValueError("boot identity unavailable") from error
            if not self._boot_id:
                raise ValueError("missing boot identity")
        return {"pid": pid, "pgid": int(fields[2]), "start_id": f"{self._boot_id}:{fields[19]}", "state": fields[0]}

    def __call__(self, pid: int) -> dict | None:
        try:
            stat = self._stat(pid)
            environ = (self.proc / str(pid) / "environ").read_bytes()
            env = dict(part.split(b"=", 1) for part in environ.split(b"\0") if b"=" in part)
            return {
                **stat, "alive": stat["state"] not in ("Z", "X"),
                "run_id": env.get(b"ARENA_RUN_ID", b"").decode(),
                "generation": env.get(b"ARENA_GENERATION", b"").decode(),
                "session_id": env.get(b"ARENA_SESSION_ID", b"").decode(),
            }
        except FileNotFoundError:
            return {"alive": False}
        except (OSError, ValueError, UnicodeError, IndexError):
            return None

    def owned_group(self, owned: dict) -> dict | None:
        """A missing leader alone does not establish absence of its descendants."""
        reading = self(owned["pid"])
        if reading is None:
            return None
        try:
            members = []
            for path in self.proc.iterdir():
                if not path.name.isdecimal():
                    continue
                try:
                    stat = self._stat(int(path.name))
                except FileNotFoundError:
                    continue
                if stat["pgid"] == owned["pgid"] and stat["state"] not in ("Z", "X"):
                    members.append(stat)
        except (OSError, ValueError, IndexError):
            return None
        result = {**reading, "group_alive": bool(members)}
        if not members:
            if reading.get("alive") and all(
                reading.get(key) == owned.get(key) for key in ("start_id", "run_id", "generation")
            ):
                return None
            return result
        matched = all(reading.get(key) == owned.get(key) for key in ("pid", "pgid", "start_id", "run_id", "generation"))
        if not reading.get("alive") or not matched:
            return result
        for member in members:
            identity = self(member["pid"])
            if identity is None:
                return None
            if not identity.get("alive"):
                continue
            if any(identity.get(key) != owned.get(key) for key in ("run_id", "generation")):
                return None
            session = owned.get("session_id") or Path(owned["session_path"]).name
            if identity.get("session_id") != session:
                return None
        self._validated[owned["pgid"]] = dict(owned)
        return result

    def signal(self, pgid: int) -> None:
        owned = self._validated.get(pgid)
        if owned is None:
            raise RuntimeError("process group was not positively identified")
        reading = self.owned_group(owned)
        if reading is None:
            raise RuntimeError("process group ownership became unknown")
        if not reading.get("group_alive"):
            return
        if not reading.get("alive") or any(
            reading.get(key) != owned.get(key) for key in ("pid", "pgid", "start_id", "run_id", "generation")
        ):
            raise RuntimeError("process ownership changed before signal")
        with contextlib.suppress(ProcessLookupError):
            self.killpg(pgid, signal.SIGTERM)


class RpcChild:
    def __init__(self, launch: dict, *, spawn=subprocess.Popen, inspect=None):
        self.inspect = inspect or ProcessInspector()
        self.launch = launch
        self._stdout_drained = False
        env = {**os.environ, **launch["env"]}
        directory = Path(env["ARENA_RUN_DIR"])
        try:
            log = (directory / f"worker-{env['ARENA_ACTIVATION_ID']}.stderr.log").open("ab")
        except OSError as error:
            error.not_spawned = True
            raise
        try:
            try:
                self.process = spawn(
                    launch["argv"], cwd=directory / "scratch" / "project", env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                    start_new_session=True, bufsize=0,
                )
            except OSError as error:
                if spawn is subprocess.Popen:
                    error.not_spawned = True
                raise
        finally:
            log.close()
        self.identity = self.inspect(self.process.pid)
        if not self.identity or not self.identity.get("alive"):
            raise RuntimeError("spawned child identity is unavailable")
        self.identity = {
            **self.identity, "run_id": env["ARENA_RUN_ID"], "generation": env["ARENA_GENERATION"],
            "session_id": env["ARENA_SESSION_ID"], "session_path": launch["session_dir"],
        }

    def subscribe(self) -> None:
        if self.process.stdout is None or self.process.stdin is None:
            raise RuntimeError("RPC pipes unavailable")

    def process_identity(self) -> dict:
        return dict(self.identity)

    def read(self, size: int = 65536) -> bytes:
        if self._stdout_drained:
            return b""
        chunk = self.process.stdout.read(size)
        if not chunk:
            self._stdout_drained = True
            self.process.stdout.close()
        return chunk

    def write(self, data: bytes) -> int:
        return self.process.stdin.write(data)

    def flush(self) -> None:
        self.process.stdin.flush()

    def shutdown(self) -> None:
        reading = self.inspect.owned_group(self.identity)
        if reading is None:
            raise RuntimeError("owned group status unknown")
        if reading.get("group_alive"):
            self.inspect.signal(self.identity["pgid"])

    def confirmed_absent(self) -> bool:
        self.process.poll()
        reading = self.inspect.owned_group(self.identity)
        absent = reading is not None and reading.get("group_alive") is False
        if absent and self.process.stdin is not None:
            self.process.stdin.close()
        return absent


def open_child(launch: dict) -> RpcChild:
    return RpcChild(launch)
