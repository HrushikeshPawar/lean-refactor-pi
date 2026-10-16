"""Submission gates and the one-at-a-time cold compile."""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable

from arena.campaign import COLD_TOLERANCE
from arena.engine import versions
from arena.forbidden import official_filter, remove_comments

_COLD_LOCK = threading.Lock()
_BARE = re.compile(r"\b(?:sorryAx|sorry|admit)\b")
MemoryReader = Callable[[], float | None]
MEMORY_TIMEOUT_S = 1800.0


def _minimum_free_gb() -> float:
    raw = os.environ.get("ARENA_SUBMIT_MIN_FREE_GB", "8")
    try:
        return float(raw)
    except ValueError:
        return 8.0


def _wait_for_memory(reader: MemoryReader, minimum: float, sleep: Callable[[float], None], timeout: float) -> bool:
    """Wait until `reader` reports `minimum` GB free. Unknown memory (None) does not wait.

    Returns False once `timeout` seconds of sleeping pass without enough free memory.
    """
    waited = 0.0
    while True:
        free = reader()
        if free is None or free >= minimum:
            return True
        if waited >= timeout:
            return False
        sleep(1.0)
        waited += 1.0


def cold_check(
    name: str,
    proof: str,
    memory_reader: MemoryReader | None = None,
    sleep: Callable[[float], None] = time.sleep,
    memory_timeout: float = MEMORY_TIMEOUT_S,
) -> dict:
    """Cold-compile one proof on every toolchain. A Lean error is a result, never an exception.

    Compiles are sequential: one Mathlib build peaks around 8.6 GB, so a second job waits.
    `memory_reader` returns free GB, or None when the machine cannot say. Tests pass a reader
    and never touch `/proc`. Memory that stays low past `memory_timeout` seconds fails the
    cold gate with that reason.
    """
    from arena.engine import evaluate, force_cold
    from arena.lean_session import _available_gb

    reader = memory_reader or _available_gb
    with _COLD_LOCK:
        minimum = _minimum_free_gb()
        if not _wait_for_memory(reader, minimum, sleep, memory_timeout):
            return {
                "passed": {},
                "tokens": None,
                "heartbeats": None,
                "proxy": None,
                "axes": {},
                "error": f"free memory stayed below {minimum:g} GB for {memory_timeout:g} s",
            }
        try:
            with force_cold():
                result = evaluate(name, proof, "full")
        except Exception as error:
            return {
                "passed": {},
                "tokens": None,
                "heartbeats": None,
                "proxy": None,
                "axes": {},
                "error": f"{type(error).__name__}: {error}",
            }
    compat = result.get("compat") or {}
    axes = {}
    for key, info in ((result.get("metrics") or {}).get("axes") or {}).items():
        if isinstance(info, dict):
            axes[key] = info.get("contribution")
    return {
        "passed": {version: bool(info.get("passed")) for version, info in compat.items()},
        "tokens": result.get("tokens"),
        "heartbeats": result.get("heartbeat"),
        "proxy": result.get("local_proxy"),
        "axes": axes,
        "error": None,
    }


def static_gate(row: dict, proof: str) -> list[str]:
    """Gates (a)-(c), which need no compile: exact statement, official filter, no `sorry`."""
    from arena.engine import validate_proof

    reasons: list[str] = []
    try:
        validate_proof(row, proof)
    except ValueError as error:
        reasons.append(str(error))
    label = official_filter()(proof)
    if label:
        reasons.append(f"official filter: {label}")
    if _BARE.search(proof) or _BARE.search(remove_comments(proof)):
        reasons.append("sorry, admit or sorryAx")
    return reasons


def cold_gate(row: dict, cold: dict) -> list[str]:
    """Gates (d)-(e): the cold result passed every listed toolchain and agrees with the record."""
    reasons: list[str] = []
    try:
        listed = [version for version, _commit in versions(row)]
    except (KeyError, TypeError):
        listed = []
    passed = cold.get("passed") or {}
    if cold.get("error"):
        reasons.append(f"cold compile failed: {cold['error']}")
    else:
        failed = [version for version in listed if not passed.get(version)]
        if failed or not listed:
            reasons.append("cold compile failed on " + ", ".join(failed or ["no toolchain"]))
    recorded = cold.get("recorded_proxy")
    measured = cold.get("proxy")
    if (
        not isinstance(recorded, (int, float))
        or isinstance(recorded, bool)
        or not isinstance(measured, (int, float))
        or isinstance(measured, bool)
        or abs(measured - recorded) > COLD_TOLERANCE * max(recorded, 1)
    ):
        reasons.append(f"cold proxy {measured} disagrees with recorded proxy {recorded}")
    return reasons


def gate(row: dict, proof: str, cold: dict) -> list[str]:
    """Reasons `proof` cannot be submitted, gates (a)-(e) in order. Empty means it passed.

    `cold` is a `cold_check` result plus `recorded_proxy`, the candidate's recorded proxy.
    """
    return static_gate(row, proof) + cold_gate(row, cold)
