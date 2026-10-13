"""Run-level Lean health: a gate before any model request and a circuit breaker during the run.

v6cov spent hours of model money on rows where every Lean check timed out (a fresh worker needed ~175 s to import
Mathlib from NTFS against a 180 s budget). Two protections, both free of model calls:

* `gate(theorem, slots)` warms the run's Lean session, checks the reference proof on every listed version and decides
  the row's per-check limit (`ARENA_LEAN_TIMEOUT`). An unhealthy row is refused before spending.
* `streak` / `trip_if_unhealthy` count consecutive model-lane checks that timed out or could not run Lean at all
  (compile errors in the proof do not count; a check that got an answer resets the count). At `BREAKER_LIMIT` the run
  is marked tripped (`lean-unhealthy.json`), the runner stops Pi, and the stop reason is `lean_unhealthy`.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import cast

HEALTH_FILE = "lean-health.json"
TRIPPED_FILE = "lean-unhealthy.json"
STOP_REASON = "lean_unhealthy"
EXIT_CODE = 75  # runner exit status for a Lean-unhealthy row (EX_TEMPFAIL): the campaign skips the row and goes on
LIMIT_FLOOR = 60
LIMIT_CAP = 900
LIMIT_FACTOR = 3
MAX_USE = 0.5  # a warm reference check may use at most this share of the limit
BREAKER_LIMIT = 5
TIMEOUT_ENV = "ARENA_LEAN_TIMEOUT"
GATE_ENV = "ARENA_LEAN_GATE"  # "0" turns the gate off (offline tests with a fake Lean)


def choose_limit(slowest_warm: float | None) -> int:
    """clamp(max(60, 3 x the primary warm reference check), <= 900)."""
    return int(min(LIMIT_CAP, max(LIMIT_FLOOR, LIMIT_FACTOR * (slowest_warm or 0.0))))


def _say(log, message: str) -> None:
    log(message, flush=True) if log is print else log(message)


def gate_versions(row: dict) -> list[tuple[str, str]]:
    """The measure version first, then every other listed version."""
    from arena import engine

    first = engine.measure_version(row)
    return [first] + [pair for pair in engine.versions(row) if pair != first]


def _warm(row: dict, version: str, commit: str, slots: int, lane: str = "model", wait: bool = True) -> dict | None:
    from arena import engine

    warm = getattr(engine, "warm_session", None)
    if not warm:
        return None
    return warm(row, version, commit, slots, lane=lane, wait=wait)


def _reference_check(row: dict, version: str, commit: str, timeout: int = LIMIT_CAP, lane: str = "model") -> dict:
    """Compile the untouched reference proof through the normal path (the session when one is configured)."""
    from arena import engine

    built = engine.candidate_file(row, row["src"], version, commit)
    started = time.monotonic()
    try:
        done = engine.run_lean(
            row,
            cast(Path, built["path"]),
            str(built["text"]),
            prefix_end=cast(int, built["head"]),
            timeout=timeout,
            lane=lane,
        )
    except Exception as error:
        return {
            "seconds": round(time.monotonic() - started, 2),
            "passed": False,
            "timed_out": False,
            "detail": f"could not run Lean: {type(error).__name__}: {str(error)[:160]}",
        }
    seconds = round(time.monotonic() - started, 2)
    if done is None:
        return {
            "seconds": seconds,
            "passed": False,
            "timed_out": True,
            "detail": f"timed out after {timeout} s",
            "path": engine.last_lean_run().get("path"),
        }
    returncode, output = done
    return {
        "seconds": seconds,
        "passed": returncode == 0,
        "timed_out": False,
        "detail": "" if returncode == 0 else output.strip()[:200],
        "path": engine.last_lean_run().get("path"),
    }


def gate(
    theorem: str,
    slots: int,
    directory: Path | None = None,
    *,
    row_fn=None,
    versions_fn=None,
    warm_fn=None,
    check_fn=None,
    log=print,
    now_fn=time.time,
) -> dict:
    """Warm and check the primary version, starting other toolchain warm-ups in the background.

    Blocking and free of model calls. The four functions are injected in tests. Persists `lean-health.json` in
    `directory` when given. Returns {"verdict": "healthy"|"unhealthy", "timeout": int, "reasons": [...],
    "versions": {version: {...}}, ...}.
    """
    if row_fn is None:
        from arena import engine

        row_fn = engine.problem
    row = row_fn(theorem)
    targets = (versions_fn or gate_versions)(row)
    warm_fn = warm_fn or _warm
    check_fn = check_fn or _reference_check
    report: dict = {"theorem": theorem, "slots": slots, "started": now_fn(), "versions": {}}
    started = time.monotonic()
    version, commit = targets[0]
    entry: dict = {}
    report["versions"][version] = entry
    try:
        warmed = warm_fn(row, version, commit, slots, lane="model", wait=True)
    except Exception as error:
        warmed = {"ok": False, "workers": 0, "seconds": [], "failed": [f"{type(error).__name__}: {error}"]}
    if warmed is None:
        entry.update(workers=None, header_seconds=None, warm_failed=[])
        _say(log, f"lean warm {version}: no session configured; the reference check below includes the import")
    else:
        warm_result = warmed if isinstance(warmed, dict) else {}
        seconds_value = warm_result.get("seconds")
        seconds = [float(s) for s in seconds_value] if isinstance(seconds_value, list) else []
        failed_value = warm_result.get("failed")
        failed = [str(item) for item in failed_value] if isinstance(failed_value, list) else []
        entry.update(
            workers=warm_result.get("workers"),
            header_seconds=round(max(seconds), 1) if seconds else None,
            warm_failed=failed,
            warm_ok=bool(warm_result.get("ok")),
        )
        if entry["workers"]:
            took = f" in {max(seconds):.0f} s" if seconds else ""
            _say(
                log,
                f"lean warm {version}: {entry['workers']} workers ready{took}"
                + (f"; {len(failed)} failed" if failed else ""),
            )
        else:
            _say(log, f"lean warm {version}: NO worker ready ({'; '.join(failed)[:160]})")
    checked = check_fn(row, version, commit, lane="model")
    entry.update(
        check_seconds=checked["seconds"],
        passed=bool(checked["passed"]),
        timed_out=bool(checked.get("timed_out")),
        detail=checked.get("detail", ""),
    )
    _say(
        log,
        f"reference {version}: {checked['seconds']:.0f} s "
        + ("passed" if checked["passed"] else f"FAILED ({entry['detail'][:100]})"),
    )
    pending = []
    for other_version, other_commit in targets[1:]:
        pending.append(other_version)
        try:
            warmed = warm_fn(row, other_version, other_commit, 1, lane="background", wait=False)
        except Exception as error:
            warmed = {"ok": False, "workers": 0, "seconds": [], "failed": [f"{type(error).__name__}: {error}"]}
        warm_result = warmed if isinstance(warmed, dict) else {}
        seconds_value = warm_result.get("seconds")
        seconds = [float(s) for s in seconds_value] if isinstance(seconds_value, list) else []
        failed_value = warm_result.get("failed")
        failed = [str(item) for item in failed_value] if isinstance(failed_value, list) else []
        report["versions"][other_version] = {
            "warmup": "background",
            "checked": False,
            "workers": warm_result.get("workers"),
            "header_seconds": round(max(seconds), 1) if seconds else None,
            "warm_failed": failed,
            "warm_ok": bool(warm_result.get("ok")),
        }
    report["pending"] = pending
    slowest = float(entry["check_seconds"])
    limit = choose_limit(slowest)
    reasons = []
    if entry.get("workers") == 0:
        reasons.append(f"{version}: no Lean worker could open the file header")
    if not entry["passed"]:
        reasons.append(
            f"{version}: reference proof did not pass ({'timed out' if entry['timed_out'] else entry['detail'][:100] or 'failed'})"
        )
    elif entry["check_seconds"] > MAX_USE * limit:
        reasons.append(
            f"{version}: warm reference check took {entry['check_seconds']:.0f} s, over "
            f"{int(MAX_USE * 100)}% of the {limit} s limit"
        )
    report.update(
        timeout=limit,
        slowest_warm_seconds=slowest,
        reasons=reasons,
        verdict="unhealthy" if reasons else "healthy",
        wall_seconds=round(time.monotonic() - started, 1),
        finished=now_fn(),
    )
    if directory is not None:
        _write_health(directory, report)
    _say(log, f"lean gate {report['verdict']}: limit {limit} s" + (" (" + "; ".join(reasons) + ")" if reasons else ""))
    return report


def trip_unhealthy(directory: Path, version: str, detail: str, now_fn=time.time) -> dict:
    marker = {
        "ts": now_fn(),
        "stop_reason": STOP_REASON,
        "source": "reference_check",
        "version": version,
        "detail": detail,
    }
    (Path(directory) / TRIPPED_FILE).write_text(json.dumps(marker) + "\n")
    _say(print, f"Lean reference check failed on {version}: {detail[:160]}")
    return marker


def check_others(
    theorem: str,
    directory: Path,
    *,
    row_fn=None,
    versions_fn=None,
    check_fn=None,
    cancelled=lambda: False,
    log=print,
    now_fn=time.time,
) -> list[dict]:
    """Run pending cross-version reference checks serially and trip on the first failure."""
    report = read_health(directory)
    if report is None:
        return []
    if row_fn is None:
        from arena import engine

        row_fn = engine.problem
    row = row_fn(theorem)
    targets = (versions_fn or gate_versions)(row)
    check_fn = check_fn or _reference_check
    completed = []
    for version, commit in targets[1:]:
        if cancelled():
            break
        entry = report.get("versions", {}).get(version, {})
        if entry.get("checked"):
            continue
        check = check_fn(row, version, commit, lane="background")
        entry.update(
            checked=True,
            check_seconds=check["seconds"],
            passed=bool(check["passed"]),
            timed_out=bool(check.get("timed_out")),
            detail=check.get("detail", ""),
        )
        report["versions"][version] = entry
        report["pending"] = [pending for pending in report.get("pending", []) if pending != version]
        _write_health(directory, report)
        completed.append({"version": version, **entry})
        detail = entry["detail"] or ("timed out" if entry["timed_out"] else "reference failed")
        if (
            not entry["passed"]
            or entry.get("workers") == 0
            or entry.get("warm_ok") is False
            or check.get("path") == "cold-fallback"
        ):
            trip_unhealthy(directory, version, detail, now_fn=now_fn)
            break
        _say(log, f"reference {version}: {entry['check_seconds']:.0f} s passed")
    return completed


def _write_health(directory: Path, report: dict) -> None:
    """Replace lean-health.json whole: check_others rewrites it while the run may be reading it."""
    path = Path(directory) / HEALTH_FILE
    temporary = path.with_name(f".{HEALTH_FILE}.{os.getpid()}.tmp")
    with contextlib.suppress(OSError):
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        os.replace(temporary, path)


def read_health(directory: Path) -> dict | None:
    try:
        return json.loads((Path(directory) / HEALTH_FILE).read_text())
    except (OSError, ValueError):
        return None


# ---- circuit breaker --------------------------------------------------------------------------------------------


def is_timeout(entry: dict) -> bool:
    return str(entry.get("error") or "").startswith("Lean timed out")


def check_outcome(result: dict) -> str | None:
    """How one recorded model-lane check went: "ok" (Lean answered, even with compile errors), "timeout",
    "unavailable" (Lean could not run at all), or None when it says nothing about Lean (a proof the harness
    rejected before compiling)."""
    compat = list((result.get("compat") or {}).values())
    if result.get("lean_unavailable") or any((e.get("lean") or {}).get("path") == "unavailable" for e in compat):
        return "unavailable"
    if not compat:
        return None
    if all(is_timeout(e) for e in compat):
        return "timeout"
    return "ok"


def model_checks(ledger: list[dict]) -> list[dict]:
    """Probe and evaluation records of the model lane, in order."""
    return [
        e
        for e in ledger
        if e.get("result") is not None
        and ((e.get("kind") == "probe") or (e.get("kind") == "evaluation" and e.get("trigger", "model") == "model"))
    ]


def streak(ledger: list[dict]) -> int:
    """Consecutive trailing model-lane checks that timed out or could not run Lean."""
    count = 0
    for event in reversed(model_checks(ledger)):
        outcome = check_outcome(event["result"])
        if outcome is None:
            continue
        if outcome == "ok":
            break
        count += 1
    return count


def tripped(directory: Path) -> dict | None:
    try:
        return json.loads((Path(directory) / TRIPPED_FILE).read_text())
    except (OSError, ValueError):
        return None


def trip_if_unhealthy(directory: Path, ledger: list[dict], limit: int = BREAKER_LIMIT, now_fn=time.time) -> dict | None:
    """Mark the run tripped once `limit` consecutive model-lane checks failed to get a Lean answer."""
    existing = tripped(directory)
    if existing:
        return existing
    count = streak(ledger)
    if count < limit:
        return None
    last = next(
        (e for e in reversed(model_checks(ledger)) if check_outcome(e["result"]) in ("timeout", "unavailable")), {}
    )
    marker = {
        "ts": now_fn(),
        "consecutive": count,
        "limit": limit,
        "last_outcome": check_outcome(last.get("result") or {}),
        "stop_reason": STOP_REASON,
    }
    with contextlib.suppress(OSError):
        (Path(directory) / TRIPPED_FILE).write_text(json.dumps(marker) + "\n")
    return marker


def apply_timeout_env(report: dict, environ=os.environ) -> None:
    environ[TIMEOUT_ENV] = str(int(report["timeout"]))
