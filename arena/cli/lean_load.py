#!/usr/bin/env python3
"""Lean session load simulator: more load than Pi produces, no model calls.

Starts K simulated runs against one shared service, warms them
all at once, then drives M model-lane and B background-lane checks per run for --minutes:
sorry probes, the reference proof, tiny edits, proofs with errors, deliberately too-slow proofs
(each followed by a quick probe on the same run to see whether the worker stayed warm), plus
route-extraction-like and other-version compatibility checks on the background lane.

It goes through the real client path (lean_session.ensure_service / request / release and
engine.candidate_file), sampling memory, Lean process counts and mount.ntfs CPU every 5 s.
It exits 0 on PASS and 1 on FAIL; see the criteria in `evaluate`.

    uv run arena lean load-test --rows Core.InitsUpdatesComm --runs 1 --concurrency 1 \
        --background 0 --minutes 2 --max-checks 2 --weights slow=1 --timeout 20      # smoke
    uv run arena lean load-test                                                 # full stress

Session API assumed beyond the current one (guarded; the report says which parts were missing):
  * op "warm": the check payload plus "slots" (as engine.warm_session sends it); ok true means the
    headers are loaded. An "unknown operation" reply degrades to one plain check with a long timeout.
  * "header_end" (offset of the target declaration) and "lane": "model" | "background" on checks.
  * reply fields new_worker, warm_kept, header_seconds, seconds, timeout (all optional).
  * a crash shows in lean-session.log as "restarted: crashed".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from arena.engine import ROOT

KINDS = ("sorry", "reference", "edit", "error", "slow")
DEFAULT_WEIGHTS = {"sorry": 30, "reference": 20, "edit": 25, "error": 15, "slow": 6}
SAMPLE_SECONDS = 5.0
MIN_AVAILABLE_GB = 3.0
PROBE_P95_LIMIT = 10.0
MODEL_P95_LIMIT = 30.0
WARM_BUDGET = 900.0


# -- pure parts ----------------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank-with-interpolation percentile, q in 0..100; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * q / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def parse_weights(text: str | None) -> dict[str, float]:
    """`sorry=3,slow=1` selects and weights kinds; unnamed kinds are off. None gives the defaults."""
    if not text:
        return dict(DEFAULT_WEIGHTS)
    weights: dict[str, float] = {}
    for part in text.split(","):
        name, _, value = part.partition("=")
        name = name.strip()
        if name not in KINDS:
            raise ValueError(f"unknown kind {name!r}; choose from {', '.join(KINDS)}")
        weights[name] = float(value) if value else 1.0
    if not weights or sum(weights.values()) <= 0:
        raise ValueError("weights must select at least one kind")
    return weights


def split_proof(row: dict) -> tuple[str, str]:
    """(statement, reference proof) of a row: the proof text starts with the statement."""
    statement, source = row["statement"], row["src"]
    if not source.startswith(statement):
        raise ValueError("row source does not start with its statement")
    return statement, source


def make_proof(kind: str, row: dict, serial: int, timeout: float) -> str:
    """The proof text (statement included, as the harness takes it) for one workload kind."""
    statement, source = split_proof(row)
    if kind == "reference":
        return source
    if kind == "sorry":
        return statement + " := by\n  sorry"
    if kind == "edit":
        # Trailing comment: the prefix and the proof are untouched, so a warm worker re-elaborates little.
        return source + f"\n  -- load-test edit {serial}"
    if kind == "error":
        return statement + f" := by\n  exact foo_does_not_exist_{serial}"
    if kind == "slow":
        millis = int((timeout + 30 + serial % 7) * 1000)
        return statement + f" := by\n  run_tac do IO.sleep {millis}\n  sorry"
    raise ValueError(f"unknown kind {kind!r}")


def pick_kind(rng: random.Random, weights: dict[str, float]) -> str:
    names = [k for k in KINDS if weights.get(k, 0) > 0]
    return rng.choices(names, weights=[weights[k] for k in names])[0]


def background_plan(versions: list[str], primary: str, rng: random.Random) -> tuple[str, str]:
    """(kind, version) for one background check: route extraction on the primary version, or a
    compatibility check on another listed version."""
    others = [v for v in versions if v != primary]
    if others and rng.random() < 0.6:
        return "compat", rng.choice(others)
    return "route", primary


def summarise(records: list[dict]) -> list[dict]:
    """Rows per kind x lane x version: n, p50, p95, max, timeouts, failures."""
    groups: dict[tuple, list[dict]] = {}
    for record in records:
        groups.setdefault((record["kind"], record["lane"], record["version"]), []).append(record)
    rows = []
    for (kind, lane, version), items in sorted(groups.items()):
        seconds = [r["seconds"] for r in items]
        rows.append(
            {
                "kind": kind,
                "lane": lane,
                "version": version,
                "n": len(items),
                "p50": percentile(seconds, 50),
                "p95": percentile(seconds, 95),
                "max": max(seconds),
                "timeouts": sum(1 for r in items if r.get("timed_out")),
                "failed": sum(1 for r in items if not r.get("ok")),
            }
        )
    return rows


def evaluate(records: list[dict], runs: list[dict], samples: list[dict], orphans: list[int]) -> list[dict]:
    """The six PASS/FAIL criteria. Each result: name, ok, detail."""
    results = []
    unexpected = [r for r in records if r["kind"] != "slow" and (r.get("timed_out") or not r.get("ok"))]
    timeouts = [r for r in unexpected if r.get("timed_out")]
    reasons = sorted({str(r.get("reason") or "failed")[:60] for r in unexpected if not r.get("timed_out")})
    results.append(
        {
            "name": "1 no timeouts or failures except the deliberate slow kind",
            "ok": not unexpected,
            "detail": f"{len(timeouts)} timeouts, {len(unexpected) - len(timeouts)} other failures"
            + (f" ({'; '.join(reasons[:3])})" if reasons else ""),
        }
    )

    probes = [r["seconds"] for r in records if r.get("after_timeout")]
    p95 = percentile(probes, 95)
    slow_timeouts = sum(1 for r in records if r["kind"] == "slow" and r.get("timed_out"))
    results.append(
        {
            "name": f"2 post-timeout probe p95 < {PROBE_P95_LIMIT:.0f} s",
            "ok": bool(probes) and p95 is not None and p95 < PROBE_P95_LIMIT,
            "detail": (f"n={len(probes)}, p95={p95:.1f} s" if probes else "no probes measured")
            + f"; {slow_timeouts} slow checks timed out",
        }
    )

    warm = [r["seconds"] for r in records if r["lane"] == "model" and r["kind"] != "slow" and r.get("post_warm")]
    p95 = percentile(warm, 95)
    results.append(
        {
            "name": f"3 model-lane non-slow p95 < {MODEL_P95_LIMIT:.0f} s after warm-up",
            "ok": bool(warm) and p95 is not None and p95 < MODEL_P95_LIMIT,
            "detail": f"n={len(warm)}, p95={p95:.1f} s" if warm else "no checks measured",
        }
    )

    fresh = [r for r in records if r.get("post_warm") and r.get("new_worker")]
    crashes = sum(run.get("crashes", 0) for run in runs)
    results.append(
        {
            "name": "4 zero fresh worker opens after warm-up (except after a crash)",
            "ok": not fresh or crashes > 0,
            "detail": f"{len(fresh)} fresh opens, {crashes} crashes logged",
        }
    )

    results.append(
        {
            "name": "5 zero orphan Lean/lake processes",
            "ok": not orphans,
            "detail": f"{len(orphans)} orphans" + (f": {orphans}" if orphans else ""),
        }
    )

    available = [s["mem_available_gb"] for s in samples if s.get("mem_available_gb") is not None]
    low = min(available) if available else None
    results.append(
        {
            "name": f"6 MemAvailable never below {MIN_AVAILABLE_GB:.0f} GB",
            "ok": low is not None and low >= MIN_AVAILABLE_GB,
            "detail": f"min {low:.2f} GB" if low is not None else "no samples",
        }
    )
    return results


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def render_report(
    config: dict, results: list[dict], records: list[dict], runs: list[dict], samples: list[dict], orphans: list[int]
) -> str:
    verdict = "PASS" if all(r["ok"] for r in results) else "FAIL"
    lines = [f"# Lean load test: {verdict}", "", "## Criteria", ""]
    lines += [f"- {'PASS' if r['ok'] else 'FAIL'}  {r['name']}: {r['detail']}" for r in results]
    lines += [
        "",
        "## Configuration",
        "",
        "```json",
        json.dumps(config, indent=2, default=str),
        "```",
        "",
        "## Warm-up per run",
        "",
        "| run | warm op | warm-up s | header opens | ok | note |",
        "|---|---|---|---:|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| {run['run']} | {run.get('warm_mode', '-')} | {_fmt(run.get('warm_seconds'))} "
            f"| {run.get('header_opens', 0)} "
            f"| {run.get('warm_ok')} | {run.get('warm_note', '')} |"
        )
    lines += [
        "",
        "## Latency by kind, lane and version (seconds)",
        "",
        "| kind | lane | version | n | p50 | p95 | max | timeouts | failed |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in summarise(records):
        lines.append(
            f"| {row['kind']} | {row['lane']} | {row['version']} | {row['n']} | {_fmt(row['p50'])} "
            f"| {_fmt(row['p95'])} | {_fmt(row['max'])} | {row['timeouts']} | {row['failed']} |"
        )
    probes = [r["seconds"] for r in records if r.get("after_timeout")]
    fresh = [r for r in records if r.get("post_warm") and r.get("new_worker")]
    available = [s["mem_available_gb"] for s in samples if s.get("mem_available_gb") is not None]
    lean = [s["lean_processes"] for s in samples if s.get("lean_processes") is not None]
    cpu = [s["ntfs_cpu_percent"] for s in samples if s.get("ntfs_cpu_percent") is not None]
    lines += [
        "",
        "## Key metrics",
        "",
        f"- post-timeout probes: n={len(probes)}, p50={_fmt(percentile(probes, 50))} s, "
        f"p95={_fmt(percentile(probes, 95))} s, max={_fmt(max(probes) if probes else None)} s",
        f"- fresh worker opens after warm-up: {len(fresh)}",
        f"- min MemAvailable: {_fmt(min(available) if available else None)} GB "
        f"(start {_fmt(available[0] if available else None)} GB)",
        f"- peak Lean/lake processes: {max(lean) if lean else '-'}",
        f"- peak mount.ntfs CPU: {_fmt(max(cpu) if cpu else None)} %",
        f"- orphans: {orphans or 'none'}",
        f"- requests: {len(records)}",
    ]
    return "\n".join(lines) + "\n"


# -- system sampling (read-only) -----------------------------------------------------------------


def mem_available_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (OSError, ValueError):
        pass
    return None


def processes_named(names: tuple[str, ...]) -> dict[int, str]:
    found: dict[int, str] = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            comm = Path(entry.path, "comm").read_text().strip()
        except OSError:
            continue
        if comm in names:
            found[int(entry.name)] = comm
    return found


def cpu_ticks(pid: int) -> int | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])  # utime + stime
    except (OSError, IndexError, ValueError):
        return None


def pgid_of(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[2])
    except (OSError, IndexError, ValueError):
        return None


LEAN_NAMES = ("lean", "lake")


class Sampler(threading.Thread):
    def __init__(self, sessions: dict[int, str], t0: float, sink) -> None:
        super().__init__(daemon=True, name="sampler")
        self.sessions, self.t0, self.sink = sessions, t0, sink
        self.stop_event = threading.Event()
        self.samples: list[dict] = []
        self.seen_pids: set[int] = set()
        self.seen_pgids: set[int] = set()
        self._ticks: dict[int, int] = {}
        self._last = time.monotonic()

    def run(self) -> None:
        from arena import lean_session

        hertz = os.sysconf("SC_CLK_TCK")
        while not self.stop_event.is_set():
            now = time.monotonic()
            ntfs = processes_named(("mount.ntfs", "ntfs-3g"))
            ticks = {pid: cpu_ticks(pid) for pid in ntfs}
            elapsed = max(now - self._last, 1e-6)
            used = sum(max(0, t - self._ticks.get(pid, t)) for pid, t in ticks.items() if t is not None)
            self._ticks = {pid: t for pid, t in ticks.items() if t is not None}
            self._last = now
            sample = {
                "event": "sample",
                "t": round(time.time() - self.t0, 1),
                "mem_available_gb": mem_available_gb(),
                "lean_processes": len(processes_named(LEAN_NAMES)),
                "ntfs_cpu_percent": round(100.0 * used / hertz / elapsed, 1) if ntfs else None,
                "status": {},
            }
            for run, path in list(self.sessions.items()):
                reply = lean_session.request({"op": "status"}, 10, path)
                if reply and reply.get("ok"):
                    sample["status"][run] = {k: v for k, v in reply.items() if k != "ok"}
                    for server in reply.get("servers", []):
                        self.seen_pids.update(int(p) for p in server.get("pids", []))
                        if server.get("pgid"):
                            self.seen_pgids.add(int(server["pgid"]))
            self.samples.append(sample)
            self.sink(sample)
            self.stop_event.wait(SAMPLE_SECONDS)


def find_orphans(recorded_pids: set[int], recorded_pgids: set[int], baseline: set[int]) -> list[int]:
    """Lean/lake processes that belong to the simulated runs (recorded pids, or members of a
    recorded process group) and are still alive. Pre-existing processes are never included."""
    orphans = []
    for pid in processes_named(LEAN_NAMES):
        if pid in baseline:
            continue
        if pid in recorded_pids or pgid_of(pid) in recorded_pgids:
            orphans.append(pid)
    return sorted(orphans)


# -- the simulation -----------------------------------------------------------------------------


class Recorder:
    def __init__(self, path: Path, t0: float) -> None:
        self.t0, self.lock, self.records = t0, threading.Lock(), []
        self.file = path.open("a", encoding="utf-8")

    def write(self, item: dict) -> None:
        with self.lock:
            self.file.write(json.dumps(item, default=str) + "\n")
            self.file.flush()

    def record(self, item: dict) -> None:
        with self.lock:
            self.records.append(item)
        self.write({"event": "request", **item})


class SimRun:
    """One simulated run: a lease on the shared service and its own run directory."""

    def __init__(self, index: int, directory: Path, row: dict, config: dict, recorder: Recorder, t0: float) -> None:
        from arena import engine

        self.index, self.directory, self.row = index, directory, row
        self.config, self.recorder, self.t0 = config, recorder, t0
        self.process = None
        self.socket = ""
        self.run_id = f"lean-load-{os.getpid()}-{index}-{int(t0)}"
        self.owns_service = False
        self.warm_done_at: float | None = None
        self.info: dict = {"run": index}
        self.budget = config["max_checks"]
        self.lock = threading.Lock()
        self.serial = 0
        self.last_timeout_at = 0.0
        self.versions = [v for v, _ in engine.versions(row)]
        self.primary = engine.measure_version(row)
        self.commits = dict(engine.versions(row))
        self.deadline = 0.0

    def start(self) -> None:
        from arena import engine, lean_session

        path = lean_session.socket_path()
        existing = lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 0.5, str(path))
        self.owns_service = not bool(existing and existing.get("ok"))
        self.socket = lean_session.ensure_service()
        reply = lean_session.request(
            {
                "op": "lease",
                "protocol": lean_session.PROTOCOL,
                "run_id": self.run_id,
                "pid": os.getpid(),
                "primary": str(engine.workspace(self.row, *self.primary)),
                "others": [
                    str(engine.workspace(self.row, v, c))
                    for v, c in engine.versions(self.row)
                    if (v, c) != self.primary
                ],
            },
            5,
            self.socket,
        )
        if not reply or not reply.get("ok"):
            raise RuntimeError(f"Lean service refused load-test lease: {(reply or {}).get('reason')}")
        self.process = SimpleNamespace(
            pid=int(json.loads((lean_session.service_dir() / lean_session.INFO_NAME).read_text())["pid"])
        )

    def next_serial(self) -> int:
        with self.lock:
            self.serial += 1
            return self.serial

    def take_budget(self) -> bool:
        with self.lock:
            if self.budget is None:
                return True
            if self.budget <= 0:
                return False
            self.budget -= 1
            return True

    def payload(
        self, version: str, proof: str, timeout: float, lane: str | None, op: str = "check", slots: int | None = None
    ) -> dict:
        from arena import engine, lean_session

        built = engine.candidate_file(self.row, proof, version, self.commits[version])
        message = {
            "op": op,
            "protocol": lean_session.PROTOCOL,
            "run_id": self.run_id,
            "project": str(built["path"]),
            "fingerprint": engine._fingerprint(str(built["path"])),
            "text": built["text"],
            "display": engine.source_path(self.row),
            "timeout": timeout,
            "header_end": built["head"],
            "prefix_sha": hashlib.sha256(built["text"][: built["head"]].encode()).hexdigest()[:16],
        }
        if lane:
            message["lane"] = lane
        if slots:
            message["slots"] = slots
        return message

    def warm(self) -> None:
        """The warm op if the session has it, else one plain long check, so the load starts on a warm worker."""
        from arena import lean_session

        started = time.monotonic()
        version = self.primary[0]
        note, mode, ok = "", "warm", False
        reply = None
        try:
            budget = float(getattr(lean_session, "OPEN_TIMEOUT", WARM_BUDGET))
            slots = int(self.config.get("slots") or getattr(lean_session, "MAX_SLOTS", 4))
            reply = (
                lean_session.request(
                    self.payload(version, split_proof(self.row)[1], budget, "model", "warm", slots),
                    budget + 120,
                    self.socket,
                )
                or {}
            )
            if not reply.get("ok") and "unknown operation" in str(reply.get("reason")):
                mode, note = "fallback-check (no warm op)", "session has no warm op"
                reply = (
                    lean_session.request(
                        self.payload(version, split_proof(self.row)[1], WARM_BUDGET, "model"),
                        WARM_BUDGET + 120,
                        self.socket,
                    )
                    or {}
                )
                budget = WARM_BUDGET
            ok = bool(reply.get("ok")) and not reply.get("timeout")
            if ok and reply.get("failed"):
                ok, note = False, f"warm failed for {reply['failed']}"
            # Like the health gate: the measure version (above) and every version background work touches get a
            # warm background worker, so compatibility checks and route extraction do not start cold.
            if ok and mode == "warm" and self.config.get("background"):
                for other in self.versions:
                    extra = (
                        lean_session.request(
                            self.payload(other, split_proof(self.row)[1], budget, "background", "warm", 1),
                            budget + 120,
                            self.socket,
                        )
                        or {}
                    )
                    if not extra.get("ok") or extra.get("failed"):
                        ok, note = False, f"background warm {other}: {extra.get('failed') or extra.get('reason')}"
                        break
            if not ok:
                note = (note + " " + str(reply.get("reason") or "timeout")).strip()
        except Exception as error:
            note = f"{type(error).__name__}: {error}"
        self.warm_done_at = time.time()
        self.info.update(
            warm_mode=mode,
            warm_seconds=round(time.monotonic() - started, 2),
            warm_ok=ok,
            warm_note=note[:200],
            warm_reply={k: v for k, v in (reply or {}).items() if k != "output"},
        )
        self.recorder.write({"event": "warm", **self.info})

    def check(self, kind: str, lane: str, version: str, proof: str, after_timeout: bool = False) -> dict:
        from arena import lean_session

        timeout = self.config["timeout"]
        started_wall = time.time()
        started = time.monotonic()
        record = {
            "run": self.index,
            "kind": kind,
            "lane": lane,
            "version": version,
            "t": round(started_wall - self.t0, 2),
            "after_timeout": after_timeout,
            "post_warm": self.warm_done_at is not None and started_wall >= self.warm_done_at,
        }
        try:
            wait = 2 * timeout + 60 + float(getattr(lean_session, "OPEN_TIMEOUT", 0))
            reply = lean_session.request(self.payload(version, proof, timeout, lane), wait, self.socket) or {}
        except Exception as error:  # a candidate_file failure is a harness bug worth seeing, not hiding
            reply = {"ok": False, "reason": f"client error {type(error).__name__}: {error}"}
        record["seconds"] = round(time.monotonic() - started, 2)
        record["ok"] = bool(reply.get("ok"))
        record["timed_out"] = bool(reply.get("timeout"))
        record["reason"] = reply.get("reason")
        record["reply_seconds"] = reply.get("seconds")
        for key in ("new_worker", "warm_kept", "header_seconds", "changed_from_line", "unchanged", "returncode"):
            if key in reply:
                record[key] = reply[key]
        self.recorder.record(record)
        return record

    def model_worker(self, seed: int) -> None:
        rng = random.Random(seed)
        version = self.primary[0]
        weights = self.config["weights"]
        while time.time() < self.deadline and self.take_budget():
            kind = pick_kind(rng, weights)
            self.check(kind, "model", version, make_proof(kind, self.row, self.next_serial(), self.config["timeout"]))
            if kind == "slow" and self.take_budget():  # the metric: is the worker still warm right after
                self.check(
                    "probe", "model", version, make_proof("sorry", self.row, self.next_serial(), 0), after_timeout=True
                )
            time.sleep(rng.uniform(0, self.config["think"]))

    def background_worker(self, seed: int) -> None:
        rng = random.Random(seed)
        reference = split_proof(self.row)[1]
        while time.time() < self.deadline and self.take_budget():
            kind, version = background_plan(self.versions, self.primary[0], rng)
            self.check(kind, "background", version, reference)
            time.sleep(rng.uniform(0, self.config["think"]) + 1)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def crash_count(directory: Path) -> int:
    try:
        return (directory / "lean-session.log").read_text(errors="replace").count("restarted: crashed")
    except OSError:
        return 0


def simulate(config: dict) -> int:
    from arena import engine, lean_session

    out: Path = config["out"]
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    recorder = Recorder(out / "raw.jsonl", t0)
    recorder.write({"event": "config", **config})
    baseline = set(processes_named(LEAN_NAMES))
    row_name = config["rows"][0]
    row = engine.problem(row_name)
    runs: list[SimRun] = []
    sampler: Sampler | None = None
    sessions: dict[int, str] = {}
    recorded_pids: set[int] = set()
    recorded_pgids: set[int] = set()
    service_path = lean_session.socket_path()
    initial_service = lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 0.5, str(service_path))
    started_service = not bool(initial_service and initial_service.get("ok"))
    try:
        for index in range(config["runs"]):
            run = SimRun(index, out / f"run-{index}", row, config, recorder, t0)
            run.start()
            if run.process is None:
                raise RuntimeError("load simulator failed to start its Lean session daemon")
            runs.append(run)
            sessions[index] = run.socket
            run.owns_service = False
            log(f"run {index}: service pid {run.process.pid}; socket={run.socket}")
        sampler = Sampler(sessions, t0, recorder.write)
        sampler.start()
        log(f"warming {len(runs)} runs at once ({row_name} on {runs[0].primary[0]})")
        warmers = [threading.Thread(target=run.warm, daemon=True) for run in runs]
        for thread in warmers:
            thread.start()
        for thread in warmers:
            thread.join()
        for run in runs:
            log(
                f"run {run.index}: warm-up {run.info.get('warm_seconds')} s ok={run.info.get('warm_ok')} {run.info.get('warm_note', '')}"
            )
        deadline = time.time() + config["minutes"] * 60
        threads = []
        for run in runs:
            run.deadline = deadline
            threads.extend(
                threading.Thread(
                    target=run.model_worker, args=(config["seed"] * 1000 + run.index * 100 + n,), daemon=True
                )
                for n in range(config["concurrency"])
            )
            threads.extend(
                threading.Thread(
                    target=run.background_worker,
                    args=(config["seed"] * 1000 + run.index * 100 + 50 + n,),
                    daemon=True,
                )
                for n in range(config["background"])
            )
        log(f"load: {len(threads)} worker threads for {config['minutes']} min")
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            time.sleep(10)
            done = len(recorder.records)
            bad = sum(1 for r in recorder.records if r["kind"] != "slow" and (r["timed_out"] or not r["ok"]))
            log(f"{done} requests, {bad} unexpected failures")
    finally:
        if sampler is not None:
            sampler.stop_event.set()
            sampler.join(timeout=15)
            recorded_pids |= sampler.seen_pids
            recorded_pgids |= sampler.seen_pgids
        try:
            info = json.loads((lean_session.service_dir() / lean_session.INFO_NAME).read_text())
            recorded_pids.update(int(p) for p in info.get("pids", []))
            recorded_pgids.update(int(g) for g in info.get("pgids", []))
        except (OSError, ValueError):
            pass
        for run in runs:
            run.info["crashes"] = crash_count(run.directory)
        for run in runs:
            try:
                lean_session.request(
                    {"op": "release", "protocol": lean_session.PROTOCOL, "run_id": run.run_id}, 10, run.socket
                )
            except Exception as error:
                log(f"release run {run.index}: {error}")
        if started_service:
            lean_session.stop_service()
        time.sleep(2)
        orphans = find_orphans(recorded_pids, recorded_pgids, baseline)
        for pid in orphans:  # only processes recorded as ours; kill by PID
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
        for run in runs:
            run.info["crashes"] = crash_count(run.directory)
            with contextlib.suppress(OSError):
                log_text = (lean_session.service_dir() / lean_session.LOG_NAME).read_text(errors="replace")
                run.info["header_opens"] = sum(
                    f"header open run={run.run_id} " in line for line in log_text.splitlines()
                )
    samples = sampler.samples if sampler else []
    results = evaluate(recorder.records, [run.info for run in runs], samples, orphans)
    report = render_report(
        {k: v for k, v in config.items() if k != "out"} | {"out": str(out)},
        results,
        recorder.records,
        [run.info for run in runs],
        samples,
        orphans,
    )
    (out / "report.md").write_text(report, encoding="utf-8")
    recorder.write({"event": "end", "orphans": orphans, "results": results})
    print("\n".join(line for line in report.splitlines()[:12]))
    log(f"report: {out / 'report.md'}")
    return 0 if all(r["ok"] for r in results) else 1


@dataclass(frozen=True)
class LeanLoadOptions:
    rows: list[str] = field(default_factory=lambda: ["putnam_1964_a4"])
    runs: int = 3
    concurrency: int = 6
    background: int = 2
    minutes: float = 20
    slots: int | None = None
    timeout: float = float(os.environ.get("ARENA_LEAN_TIMEOUT") or 180)
    out: Path | None = None
    seed: int = 1
    weights: str | None = None
    max_checks: int | None = None
    think: float = 1.0


def execute(options: LeanLoadOptions) -> int:
    out = options.out or ROOT / "runs/analysis/loadtest" / datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        weights = parse_weights(options.weights)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    config = {
        "rows": options.rows,
        "runs": options.runs,
        "concurrency": options.concurrency,
        "background": options.background,
        "minutes": options.minutes,
        "timeout": options.timeout,
        "out": out,
        "seed": options.seed,
        "weights": weights,
        "max_checks": options.max_checks,
        "think": options.think,
        "slots": options.slots,
    }
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return simulate(config)


cli_execute = execute
