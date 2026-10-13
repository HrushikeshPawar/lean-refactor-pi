"""Injectable scheduling helpers for campaigns."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import statistics
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from arena.engine import ROOT

LOCK_PATH = ROOT / "runs" / "campaign.lock"
PREWARM_LEAD_S = 720


class CampaignLocked(RuntimeError):
    """Raised when another campaign owns the machine-wide campaign lock."""


class CampaignLock:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or LOCK_PATH)
        self.file = None

    def acquire(self, info: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o666)
        self.file = os.fdopen(descriptor, "r+")
        try:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.file.seek(0)
            try:
                holder = json.loads(self.file.readline())
            except (json.JSONDecodeError, OSError):
                holder = {}
            self.file.close()
            self.file = None
            raise CampaignLocked(
                f"campaign lock held by pid {holder.get('pid', '?')}, prefix {holder.get('prefix', '?')}, "
                f"started {holder.get('started', '?')}"
            ) from error
        recorded = {
            "pid": os.getpid(),
            "prefix": info["prefix"],
            "started": info.get("started") or datetime.now().astimezone().isoformat(),
            "argv": info.get("argv", []),
        }
        data = (json.dumps(recorded) + "\n").encode()
        os.pwrite(self.file.fileno(), data, 0)
        os.ftruncate(self.file.fileno(), len(data))
        self.file.flush()
        return recorded

    def release(self) -> None:
        if self.file is not None:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


def holder(path: Path | None = None) -> dict | None:
    try:
        with Path(path or LOCK_PATH).open("r") as file:
            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                file.seek(0)
                try:
                    return json.loads(file.readline())
                except json.JSONDecodeError:
                    return {"pid": "?", "prefix": "?", "started": "?"}
            finally:
                with suppress(OSError):
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    except OSError:
        return None
    return None


def plan_order(rows: list[str], group_of: Callable[[str], object]) -> list[str]:
    groups: dict[object, list[str]] = {}
    for row in rows:
        groups.setdefault(group_of(row), []).append(row)
    return [row for group in groups.values() for row in group]


def row_group(row: dict) -> tuple:
    return row["source"], tuple(version for pair in row["version_info"] for version in pair)


def row_projects(row: dict, *, workspace_fn=None) -> list[Path]:
    if workspace_fn is None:
        from arena import engine

        workspace_fn = engine.workspace
    projects = []
    for version, commit in ((v, c) for pair in row["version_info"] for v, c in pair.items()):
        try:
            project = workspace_fn(row, version, commit)
        except (FileNotFoundError, ValueError):
            continue
        if project is not None and project not in projects:
            projects.append(project)
    return projects


class HoldKeeper:
    def __init__(self, owner: str, pid: int, request_fn: Callable, *, log=print):
        self.owner, self.pid, self.request_fn, self.log = owner, pid, request_fn, log
        self.projects: dict[str, list[Path]] = {}
        self.unfinished: set[str] = set()
        self.failed = False
        self.lock = threading.Lock()

    def start(self, rows: list[tuple[str, list[Path]]]) -> None:
        with self.lock:
            self.projects = dict(rows)
            self.unfinished = set(self.projects)
            self._send("hold")

    def row_finished(self, row: str) -> None:
        with self.lock:
            self.unfinished.discard(row)
            self._send("hold")

    def _send(self, op: str) -> None:
        if self.failed:
            return
        try:
            result = self.request_fn(
                {
                    "op": op,
                    "owner": self.owner,
                    "pid": self.pid,
                    "projects": sorted({str(path) for row in self.unfinished for path in self.projects[row]}),
                },
                5.0,
            )
            if result is None or not result.get("ok", True):
                raise ConnectionError("Lean service rejected hold")
        except Exception as error:
            self.failed = True
            self.log(f"Lean service holds unavailable ({error}); continuing with cold fallback")

    def close(self) -> None:
        with self.lock:
            try:
                self.request_fn({"op": "unhold", "owner": self.owner, "pid": self.pid}, 5.0)
            except Exception as error:
                if not self.failed:
                    self.log(f"Lean service unhold failed: {error}")


class Prewarm:
    def __init__(
        self,
        rows: list[str],
        specs_per_row: int,
        lead_s: float = PREWARM_LEAD_S,
        now_fn=time.monotonic,
        warm_fn=lambda _row: None,
        *,
        log=print,
    ):
        self.rows, self.specs_per_row = rows, specs_per_row
        self.lead_s, self.now_fn, self.warm_fn = lead_s, now_fn, warm_fn
        self.log = log
        self.started_at: dict[str, float] = {}
        self.spec_rows: dict[str, str] = {}
        self.finished_times: dict[str, list[float]] = {row: [] for row in rows}
        self.finished_counts: dict[str, int] = dict.fromkeys(rows, 0)
        self.warmed: set[str] = set()
        self.no_estimate_logged: set[str] = set()
        self.lock = threading.Lock()

    def started(self, spec: dict) -> None:
        with self.lock:
            self.spec_rows[spec["run_id"]] = spec["row"]
            self.started_at[spec["run_id"]] = self.now_fn()

    def finished(self, spec: dict, seconds: float) -> None:
        with self.lock:
            self.started_at.pop(spec["run_id"], None)
            self.finished_times[spec["row"]].append(seconds)
            self.finished_counts[spec["row"]] += 1

    def due(self, now: float) -> str | None:
        with self.lock:
            current_index = next(
                (i for i, row in enumerate(self.rows) if self.finished_counts[row] < self.specs_per_row), None
            )
            if current_index is None or current_index + 1 >= len(self.rows):
                return None
            current = self.rows[current_index]
            active = [at for run_id, at in self.started_at.items() if self.spec_rows.get(run_id) == current]
            if self.finished_counts[current] + len(active) < self.specs_per_row:
                return None
            previous = [t for row in self.rows[: current_index + 1] for t in self.finished_times[row]]
            own = self.finished_times[current]
            estimate_pool = own or previous
            if not estimate_pool:
                next_row = self.rows[current_index + 1]
                if next_row not in self.no_estimate_logged:
                    self.no_estimate_logged.add(next_row)
                    self.log(f"pre-warm {next_row}: no runtime estimate yet")
                return None
            estimate = statistics.median(estimate_pool)
            if not active:
                return None
            elapsed = now - min(active)
            next_row = self.rows[current_index + 1]
            if next_row not in self.warmed and estimate - elapsed <= self.lead_s:
                self.warmed.add(next_row)
                return next_row
        return None


class ResourceSampler:
    def __init__(self, interval=30.0, *, mem_fn=None, load_fn=None, swap_fn=None, disk_fn=None, now_fn=time.monotonic):
        self.interval = interval
        self.mem_fn = mem_fn or mem_available_default
        self.load_fn = load_fn or load1_default
        self.swap_fn = swap_fn or swap_used_default
        self.disk_fn = disk_fn or disk_free_default
        self.now_fn = now_fn
        self.min_mem_available_gb = None
        self.max_load1 = None
        self.max_swap_used_gb = None
        self.min_disk_free_gb = None
        self.samples = 0
        self.max_concurrent_runs = 0
        self.current_runs = 0
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

    def sample(self) -> None:
        mem, load, swap, disk = self.mem_fn(), self.load_fn(), self.swap_fn(), self.disk_fn()
        with self.lock:
            self.min_mem_available_gb = (
                mem if self.min_mem_available_gb is None else min(self.min_mem_available_gb, mem)
            )
            self.max_load1 = load if self.max_load1 is None else max(self.max_load1, load)
            self.max_swap_used_gb = swap if self.max_swap_used_gb is None else max(self.max_swap_used_gb, swap)
            self.min_disk_free_gb = disk if self.min_disk_free_gb is None else min(self.min_disk_free_gb, disk)
            self.samples += 1

    def start(self) -> None:
        self.sample()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.sample()

    def stop(self) -> dict:
        self.stop_event.set()
        if self.thread:
            self.thread.join()
        with self.lock:
            return {
                "min_mem_available_gb": self.min_mem_available_gb,
                "max_load1": self.max_load1,
                "max_swap_used_gb": self.max_swap_used_gb,
                "min_disk_free_gb": self.min_disk_free_gb,
                "max_concurrent_runs": self.max_concurrent_runs,
                "samples": self.samples,
            }

    def run_started(self) -> None:
        with self.lock:
            self.current_runs += 1
            self.max_concurrent_runs = max(self.max_concurrent_runs, self.current_runs)

    def run_finished(self) -> None:
        with self.lock:
            self.current_runs -= 1


def mem_available_default() -> float:
    values = _meminfo()
    return values["MemAvailable"] / 1024**2


def mem_total_default() -> float:
    return _meminfo()["MemTotal"] / 1024**2


def swap_used_default() -> float:
    values = _meminfo()
    return (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) / 1024**2


def _meminfo() -> dict[str, int]:
    return {
        line.split(":", 1)[0]: int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if ":" in line
    }


def load1_default() -> float:
    return float(Path("/proc/loadavg").read_text().split()[0])


def disk_free_default() -> float:
    return shutil.disk_usage(ROOT).free / 1024**3
