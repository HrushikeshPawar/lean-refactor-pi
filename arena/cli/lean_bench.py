"""Measure Lean session latency and memory, and compare it with a recorded baseline."""

from __future__ import annotations

import json
import os
import shutil
import signal
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from arena import engine, lean_session, provenance
from arena.cli import lean_load

NOISE_FLOOR_S = 0.25
# The first open of a session measures how much of the library the page cache holds, not Lean: after other
# large workspaces evict it, it is several times slower. Reported and recorded, never gated.
UNGATED_FIGURES = frozenset({"open_cold_s"})
BENCHMARK_ROWS = (
    "Core.InitsUpdatesComm",
    "putnam_1964_b2",
    "Cslib.SKI.parallelReduction_diamond",
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius",
)


@dataclass(frozen=True)
class Regression:
    row: str
    toolchain: str
    figure: str
    baseline: float | str
    current: float | str
    ratio: float | None
    limit: float | None


def make_splice(row: dict, where: str, serial: int) -> str | None:
    """Return the reference proof with one comment inserted at an early or late proof line."""
    if where not in ("early", "late"):
        raise ValueError("where must be 'early' or 'late'")
    reference = lean_load.make_proof("reference", row, serial, 0)
    statement = row["statement"]
    if not reference.startswith(statement):
        raise ValueError("row source does not start with its statement")
    by_at = reference.find(":= by", len(statement))
    if by_at < 0:
        return None
    body_start = reference.find("\n", by_at)
    if body_start < 0:
        return None
    lines = reference.splitlines(keepends=True)
    first_body_line = reference.count("\n", 0, body_start + 1)
    body_lines = [index for index in range(first_body_line, len(lines)) if lines[index].strip()]
    if len(body_lines) <= 1:
        return None
    target = body_lines[0] if where == "early" else body_lines[-1]
    newline = "\n" if lines[target].endswith("\n") else ""
    separator = "" if newline else "\n"
    comment = f"{separator}  -- bench splice {where} {serial}{newline}"
    lines.insert(target + 1, comment)
    return "".join(lines)


def plan_checks(repeats: int) -> list[tuple[str, bool]]:
    """The deterministic check sequence; the boolean says whether the check is measured."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    checks = []
    for _ in range(repeats):
        checks.extend(
            [
                ("sorry", True),
                ("reference", True),
                ("edit", True),
                ("error", True),
                ("reference", False),
                ("splice_late", True),
                ("reference", False),
                ("splice_early", True),
            ]
        )
    return checks


def summarise_checks(records: list[dict]) -> dict:
    """Summarize successful and failed checks, excluding timeouts from latency percentiles."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["kind"], []).append(record)
    result = {}
    for kind, items in sorted(groups.items()):
        measured = [float(item["seconds"]) for item in items if not item.get("timed_out")]
        result[kind] = {
            "n": len(measured),
            "p50": lean_load.percentile(measured, 50),
            "p95": lean_load.percentile(measured, 95),
            "max": max(measured) if measured else None,
            "timeouts": sum(bool(item.get("timed_out")) for item in items),
        }
    return result


def summarise_pss(samples: list[dict[int, float]], worker_pids: set[int]) -> dict:
    """Report first-sample (idle) and peak PSS for the Lean workers observed in status trees."""
    if not samples or not worker_pids:
        return {"workers_idle_gb": [], "worker_peak_gb": None}
    first = samples[0]
    idle = [first[pid] for pid in sorted(worker_pids) if pid in first]
    values = [sample[pid] for sample in samples for pid in worker_pids if pid in sample]
    return {"workers_idle_gb": idle, "worker_peak_gb": max(values) if values else None}


def _figure_values(result: dict) -> dict[str, float | None]:
    figures: dict[str, float | None] = {}
    for kind, summary in result.get("checks", {}).items():
        if summary is None:
            figures[f"{kind}.p50"] = None
            continue
        figures[f"{kind}.p50"] = summary.get("p50")
        if kind not in ("splice_early", "splice_late"):
            figures[f"{kind}.p95"] = summary.get("p95")
    figures["open_cold_s"] = result.get("open_cold_s")
    figures["open_warm_s"] = result.get("open_warm_s")
    return figures


def compare(
    baseline: dict,
    current: dict,
    tolerance_p50: float = 0.10,
    tolerance_p95: float = 0.20,
    floor_s: float = NOISE_FLOOR_S,
) -> list[Regression]:
    """Find regressions only when both the relative tolerance and absolute noise floor are exceeded."""
    baseline_repeats = baseline.get("settings", {}).get("repeats")
    current_repeats = current.get("settings", {}).get("repeats")
    if baseline_repeats != current_repeats:
        raise ValueError(f"baseline repeats ({baseline_repeats}) differ from current repeats ({current_repeats})")
    regressions = []
    for row_name, toolchains in current.get("rows", {}).items():
        if row_name not in baseline.get("rows", {}):
            raise ValueError(f"row {row_name!r} is missing from baseline")
        for toolchain, current_result in toolchains.items():
            if toolchain not in baseline["rows"][row_name]:
                raise ValueError(f"toolchain {toolchain!r} for row {row_name!r} is missing from baseline")
            base_result = baseline["rows"][row_name][toolchain]
            before, after = _figure_values(base_result), _figure_values(current_result)
            for figure in sorted((set(before) | set(after)) - UNGATED_FIGURES):
                old, new = before.get(figure), after.get(figure)
                if new is None and old is None:
                    continue
                if new is None:
                    regressions.append(
                        Regression(
                            row_name, toolchain, "missing", old if old is not None else "-", "missing", None, None
                        )
                    )
                    continue
                if old is None:
                    continue
                tolerance = tolerance_p95 if figure.endswith(".p95") or figure.startswith("open_") else tolerance_p50
                if new > old * (1 + tolerance) and new - old > floor_s:
                    regressions.append(
                        Regression(row_name, toolchain, figure, old, new, new / old - 1 if old else None, tolerance)
                    )
    return regressions


def cold_cache_warnings(result: dict, ratio: float = 2.0) -> list[str]:
    """Name each row and toolchain whose first open was much slower than its repeat: the page cache was cold."""
    warnings = []
    for row, toolchains in result.get("rows", {}).items():
        for toolchain, item in toolchains.items():
            cold, warm = item.get("open_cold_s"), item.get("open_warm_s")
            if cold is not None and warm and cold > warm * ratio and cold - warm > NOISE_FLOOR_S:
                warnings.append(
                    f"{row} | {toolchain} | first open {cold:.2f}s vs repeat {warm:.2f}s: the page cache was cold; "
                    "if the gate fails, run it once more"
                )
    return warnings


def format_report(regressions: list[Regression]) -> str:
    """One concise operator-facing line per regression."""
    lines = []
    for item in regressions:
        if item.ratio is None or item.limit is None:
            amount = "missing"
            limit = "n/a"
        else:
            amount = f"+{item.ratio * 100:.0f}%"
            limit = f"+{item.limit * 100:.0f}%"
        lines.append(
            f"{item.row} | {item.toolchain} | {item.figure} | "
            f"{_display(item.baseline)} -> {_display(item.current)} | {amount} (limit {limit})"
        )
    return "\n".join(lines) if lines else "0 regressions"


def _display(value: float | str | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, (float, int)) else value


def _validate_shape(data: dict, path: Path) -> None:
    def invalid(problem: str) -> None:
        raise ValueError(f"{path}: {problem}")

    if not isinstance(data, dict) or data.get("schema") != 1:
        invalid("schema must be 1")
    if not isinstance(data.get("settings"), dict) or not isinstance(data["settings"].get("repeats"), int):
        invalid("settings.repeats must be an integer")
    if not isinstance(data.get("rows"), dict):
        invalid("rows must be an object")
    for row_name, toolchains in data["rows"].items():
        if not isinstance(toolchains, dict):
            invalid(f"rows.{row_name} must be an object")
        for toolchain, result in toolchains.items():
            if not isinstance(result, dict) or not isinstance(result.get("checks"), dict):
                invalid(f"rows.{row_name}.{toolchain}.checks must be an object")
            for figure, value in _figure_values(result).items():
                if value is not None and not isinstance(value, (float, int)):
                    invalid(f"rows.{row_name}.{toolchain}.{figure} must be numeric or null")


def load_baseline(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: could not read baseline: {error}") from error
    _validate_shape(data, path)
    return data


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _sample_workers(run: lean_load.SimRun) -> tuple[dict[int, float], set[int], float | None]:
    status = lean_session.request({"op": "status"}, 10, run.socket) or {}
    if not status.get("ok"):
        raise RuntimeError(f"Lean status failed: {status.get('reason', 'unknown error')}")
    samples: dict[int, float] = {}
    workers: set[int] = set()
    for server in status.get("servers", []):
        for pid in server.get("pids", []):
            pid = int(pid)
            if "--worker" not in _cmdline(pid):
                continue
            workers.add(pid)
            pss = lean_session.pid_pss_gb(pid)
            if pss is None:
                raise RuntimeError(f"smaps_rollup is unreadable for Lean worker pid {pid}")
            samples[pid] = pss
    return samples, workers, lean_load.mem_available_gb()


class _WorkerSampler(threading.Thread):
    """Sample the live worker set while a potentially long compile is running."""

    def __init__(self, run: lean_load.SimRun, recorder: lean_load.Recorder) -> None:
        super().__init__(daemon=True, name="lean-bench-sampler")
        self.run_session, self.recorder = run, recorder
        self.stop_event = threading.Event()
        self.samples: list[dict[int, float]] = []
        self.worker_pids: set[int] = set()
        self.available: list[float] = []
        self.error: Exception | None = None

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                values, workers, free = _sample_workers(self.run_session)
                self.samples.append(values)
                self.worker_pids.update(workers)
                if free is not None:
                    self.available.append(free)
                    if free < lean_load.MIN_AVAILABLE_GB:
                        raise RuntimeError(
                            f"MemAvailable fell below {lean_load.MIN_AVAILABLE_GB:.0f} GB ({free:.2f} GB)"
                        )
                self.recorder.write(
                    {
                        "event": "bench_sample",
                        "pss_gb": values,
                        "worker_pids": sorted(workers),
                        "mem_available_gb": free,
                    }
                )
            except Exception as error:
                self.error = error
                self.stop_event.set()
                return
            self.stop_event.wait(2.0)

    def stop(self) -> None:
        self.stop_event.set()
        self.join()


def _kill_orphans(pids: list[int]) -> list[int]:
    for pid in pids:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    time.sleep(0.1)
    still_running = [pid for pid in pids if lean_session.running(pid)]
    for pid in still_running:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    return [pid for pid in still_running if lean_session.running(pid)]


def _stop_checked(run: lean_load.SimRun, service: Path, baseline_processes: set[int]) -> None:
    """Stop the bench's private service and check that none of its Lean processes outlived it."""
    status = lean_session.request({"op": "status", "protocol": lean_session.PROTOCOL}, 10, run.socket) or {}
    if not status.get("ok"):
        raise RuntimeError(f"Lean status failed before shutdown: {status.get('reason', 'unknown error')}")
    pids = {int(pid) for server in status.get("servers", []) for pid in server.get("pids", [])}
    pgids = {int(server["pgid"]) for server in status.get("servers", []) if server.get("pgid")}
    lean_session.request({"op": "release", "protocol": lean_session.PROTOCOL, "run_id": run.run_id}, 10, run.socket)
    run.process = None
    lean_session.stop_service(service)
    orphans = lean_load.find_orphans(pids, pgids, baseline_processes)
    remaining = _kill_orphans(orphans)
    if remaining:
        raise RuntimeError(f"Lean orphan processes remain for {run.row['name']}: {remaining}")


def _measure_pair(
    row: dict,
    version: str,
    commit: str,
    repeats: int,
    timeout: float,
    out: Path,
    index: int,
    recorder: lean_load.Recorder,
    t0: float,
) -> dict:
    config = {"max_checks": None, "timeout": timeout, "weights": {}, "slots": 1, "background": 0, "think": 0}
    directory = out / f"session-{index}"
    run = lean_load.SimRun(index, directory, row, config, recorder, t0)
    run.primary = (version, commit)
    baseline_processes = set(lean_load.processes_named(lean_load.LEAN_NAMES))
    sampler: _WorkerSampler | None = None
    # A service of the bench's own (short path: the socket name is limited): no other run's Lean is measured
    # with it or killed by it, and stopping it between the two opens makes the repeat open a real one where
    # a shared service would keep the header warm.
    service = Path(tempfile.mkdtemp(prefix="arena-bench-"))
    try:
        run.start(lean_session.ensure_service(service))
        run.warm()
        if not run.info.get("warm_ok"):
            raise RuntimeError(f"Lean warm-up failed for {row['name']} {version}: {run.info.get('warm_note')}")
        cold = float(run.info["warm_seconds"])
        _stop_checked(run, service, baseline_processes)
        run = lean_load.SimRun(index + 1_000_000, out / f"session-{index}-repeat", row, config, recorder, t0)
        run.primary = (version, commit)
        run.start(lean_session.ensure_service(service))
        run.warm()
        if not run.info.get("warm_ok"):
            raise RuntimeError(f"Lean repeat warm-up failed for {row['name']} {version}: {run.info.get('warm_note')}")
        warm = float(run.info["warm_seconds"])
        sampler = _WorkerSampler(run, recorder)
        sampler.start()
        records = []
        for serial, (kind, recorded) in enumerate(plan_checks(repeats), 1):
            if sampler.error is not None:
                raise sampler.error
            if kind == "splice_early":
                proof = make_splice(row, "early", serial)
            elif kind == "splice_late":
                proof = make_splice(row, "late", serial)
            else:
                proof = lean_load.make_proof(kind, row, serial, timeout)
            if proof is not None:
                result = run.check(kind, "model", version, proof)
                if recorded:
                    records.append(result)
                if not result.get("ok") or result.get("timed_out"):
                    raise RuntimeError(
                        f"Lean {kind} failed for {row['name']} {version}: {result.get('reason') or 'timeout'}"
                    )
        sampler.stop()
        if sampler.error is not None:
            raise sampler.error
        if not sampler.worker_pids:
            raise RuntimeError(f"no Lean --worker process found for {row['name']} {version}")
        result = {
            "commit": commit,
            "open_cold_s": cold,
            "open_warm_s": warm,
            "checks": summarise_checks(records),
            "pss_gb": summarise_pss(sampler.samples, sampler.worker_pids),
            "min_available_gb": min(sampler.available) if sampler.available else None,
        }
        for splice in ("splice_early", "splice_late"):
            if make_splice(row, splice.removeprefix("splice_"), 0) is None:
                result["checks"][splice] = None
        return result
    finally:
        if sampler is not None and sampler.ident is not None and sampler.is_alive():
            sampler.stop()
        if run.process is not None:
            _stop_checked(run, service, baseline_processes)
        with suppress(OSError):
            shutil.copyfile(service / lean_session.LOG_NAME, out / f"service-{index}.log")
        shutil.rmtree(service, ignore_errors=True)


def measure(rows: list[str], versions: str | dict[str, list[str]], repeats: int, timeout: float, out_dir: Path) -> dict:
    """Run one cold and one warm open, then the serial check plan for each row and toolchain."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    recorder = lean_load.Recorder(out_dir / "raw.jsonl", t0)
    result = {
        "measurement_note": (
            "Cold is the first open of this invocation; the page cache is not dropped (that requires root), "
            "so it is reported but not gated."
        ),
        "settings": {"repeats": repeats, "timeout": timeout},
        "rows": {},
    }
    index = 0
    try:
        for row_name in rows:
            row = engine.problem(row_name)
            listed = engine.versions(row)
            requested_versions = versions.get(row_name) if isinstance(versions, dict) else versions
            if requested_versions is None:
                selected = []
            elif requested_versions == "first":
                selected = listed[:1]
            elif requested_versions == "all":
                selected = listed
            else:
                requested = (
                    requested_versions
                    if isinstance(requested_versions, list)
                    else [value.strip() for value in requested_versions.split(",") if value.strip()]
                )
                missing = [value for value in requested if value not in dict(listed)]
                if missing:
                    raise ValueError(f"unknown toolchain(s) for {row_name}: {', '.join(missing)}")
                selected = [(version, commit) for version, commit in listed if version in requested]
            result["rows"][row_name] = {}
            for version, commit in selected:
                workspace = engine.workspace(row, version, commit)
                if not workspace.is_dir():
                    raise FileNotFoundError(f"workspace not provisioned: {workspace}")
                result["rows"][row_name][version] = _measure_pair(
                    row, version, commit, repeats, timeout, out_dir, index, recorder, t0
                )
                index += 1
    finally:
        recorder.file.close()
    return result


def _read_mem_total_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        pass
    return 0.0


def baseline_document(result: dict, label: str = "v6") -> dict:
    return {
        "schema": 1,
        "label": label,
        "recorded": date.today().isoformat(),
        "code": provenance.code_version(),
        "machine": {"cpus": os.cpu_count(), "mem_total_gb": _read_mem_total_gb()},
        **result,
    }


def write_baseline(path: Path, result: dict, force: bool = False) -> dict | None:
    old = load_baseline(path) if path.exists() and force else None
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path}; pass --force")
    data = baseline_document(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return old


def render_table(result: dict) -> str:
    lines = ["row | toolchain | cold | warm | checks (p50 / p95) | worker PSS idle / peak | min free"]
    for row, toolchains in result["rows"].items():
        for toolchain, item in toolchains.items():
            checks = ", ".join(
                f"{name} {_display(summary.get('p50'))}/{_display(summary.get('p95'))}"
                for name, summary in item["checks"].items()
                if summary is not None
            )
            pss = item["pss_gb"]
            idle = ",".join(f"{value:.2f}" for value in pss["workers_idle_gb"])
            lines.append(
                f"{row} | {toolchain} | {item['open_cold_s']:.2f} | {item['open_warm_s']:.2f} | {checks} | "
                f"{idle} / {_display(pss['worker_peak_gb'])} | {_display(item['min_available_gb'])}"
            )
    return "\n".join(lines)


def print_table(result: dict) -> None:
    """Render the measured figures as an operator-facing Rich table."""
    from rich.console import Console
    from rich.table import Table

    table = Table(title="Lean speed and worker memory")
    for heading in (
        "Row",
        "Toolchain",
        "Open cold / warm",
        "Check p50 / p95",
        "Splice early / late",
        "Worker PSS idle / peak",
        "Min free GB",
    ):
        table.add_column(heading)
    for row, toolchains in result["rows"].items():
        for toolchain, item in toolchains.items():
            check_text = ", ".join(
                f"{name} {_display(summary.get('p50'))}/{_display(summary.get('p95'))}"
                for name, summary in item["checks"].items()
                if summary is not None and not name.startswith("splice_")
            )
            splice = ", ".join(
                f"{name.removeprefix('splice_')} {_display(summary.get('p50'))}"
                for name, summary in item["checks"].items()
                if summary is not None and name.startswith("splice_")
            )
            pss = item["pss_gb"]
            idle = ", ".join(f"{value:.2f}" for value in pss["workers_idle_gb"])
            table.add_row(
                row,
                toolchain,
                f"{item['open_cold_s']:.2f} / {item['open_warm_s']:.2f}",
                check_text,
                splice or "-",
                f"{idle} / {_display(pss['worker_peak_gb'])}",
                _display(item["min_available_gb"]),
            )
    Console().print(table)
