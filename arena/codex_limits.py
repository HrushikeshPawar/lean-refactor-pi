"""Current Codex/ChatGPT usage limits (5-hour and weekly windows), read locally without spending usage.

Primary source: `codex app-server` over stdio, JSON-RPC `account/rateLimits/read` (live, uses the stored OAuth login).
Fallback: the newest `rate_limits` snapshot in `~/.codex/sessions/**/rollout-*.jsonl` (only as fresh as the last Codex use).
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CODEX_HOME = Path.home() / ".codex"
READ_TIMEOUT_S = 20.0
TAIL_BYTES = 1 << 20
FIVE_HOUR_MINUTES = 300


@dataclass(frozen=True)
class CodexLimits:
    five_hour_pct: float
    weekly_pct: float
    five_hour_resets_at: float | None
    weekly_resets_at: float | None
    observed_at: float
    source: str


def _window(snapshot: dict[str, Any], key: str) -> tuple[float, float | None] | None:
    win = snapshot.get(key)
    if not isinstance(win, dict):
        return None
    pct = win.get("usedPercent", win.get("used_percent"))
    if not isinstance(pct, (int, float)):
        return None
    resets = win.get("resetsAt", win.get("resets_at"))
    return float(pct), float(resets) if isinstance(resets, (int, float)) else None


def from_snapshot(snapshot: Any, observed_at: float, source: str) -> CodexLimits | None:
    """Build limits from a `rateLimits` / `rate_limits` object (camelCase or snake_case)."""
    if not isinstance(snapshot, dict):
        return None
    five, week = _window(snapshot, "primary"), _window(snapshot, "secondary")
    if five is None or week is None:
        return None
    return CodexLimits(five[0], week[0], five[1], week[1], observed_at, source)


def read_app_server(command: str = "codex", timeout: float = READ_TIMEOUT_S) -> CodexLimits | None:
    """Ask a short-lived `codex app-server` for the account rate limits (no model call)."""
    try:
        proc = subprocess.Popen(
            [command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    assert proc.stdin is not None and proc.stdout is not None
    try:
        init = {"clientInfo": {"name": "arena", "title": "arena", "version": "0"}}
        for message in (
            {"id": 1, "method": "initialize", "params": init},
            {"method": "initialized"},
            {"id": 2, "method": "account/rateLimits/read"},
        ):
            proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([proc.stdout], [], [], min(left, 1.0))[0]:
                continue
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if isinstance(reply, dict) and reply.get("id") == 2:
                result = reply.get("result")
                snapshot = result.get("rateLimits") if isinstance(result, dict) else None
                return from_snapshot(snapshot, time.time(), "app-server")
        return None
    except (OSError, ValueError):
        return None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _newest_snapshot(path: Path) -> CodexLimits | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if "rate_limits" not in line:
            continue
        try:
            event = json.loads(line)
            payload = event["payload"]
            limits = from_snapshot(payload["rate_limits"], 0.0, "rollout")
            stamp = event.get("timestamp")
            observed = time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone if stamp else path.stat().st_mtime
        except (ValueError, KeyError, TypeError, OSError):
            continue
        if limits is not None:
            return CodexLimits(limits.five_hour_pct, limits.weekly_pct, limits.five_hour_resets_at, limits.weekly_resets_at, observed, "rollout")
    return None


def read_rollout(home: Path = CODEX_HOME) -> CodexLimits | None:
    """Newest `token_count` rate-limit snapshot from Codex session files; a window already reset reads as 0%."""
    try:
        files = sorted(home.glob("sessions/*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in files[:5]:
        limits = _newest_snapshot(path)
        if limits is None:
            continue
        now = time.time()
        five = 0.0 if limits.five_hour_resets_at is not None and limits.five_hour_resets_at <= now else limits.five_hour_pct
        week = 0.0 if limits.weekly_resets_at is not None and limits.weekly_resets_at <= now else limits.weekly_pct
        return CodexLimits(five, week, limits.five_hour_resets_at, limits.weekly_resets_at, limits.observed_at, "rollout")
    return None


def read_limits(home: Path = CODEX_HOME, command: str | None = "codex", timeout: float = READ_TIMEOUT_S) -> CodexLimits | None:
    """Live app-server reading, else the newest rollout snapshot, else None. Never raises."""
    if command:
        limits = read_app_server(command, timeout)
        if limits is not None:
            return limits
    return read_rollout(home)


def _when(stamp: float | None) -> str:
    return "?" if stamp is None else time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def main() -> int:
    limits = read_limits()
    if limits is None:
        print("codex limits: unavailable")
        return 1
    age = int(time.time() - limits.observed_at)
    print(
        f"5h {limits.five_hour_pct:.0f}% (resets {_when(limits.five_hour_resets_at)}) | "
        f"weekly {limits.weekly_pct:.0f}% (resets {_when(limits.weekly_resets_at)}) | {limits.source}, {age}s old"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
