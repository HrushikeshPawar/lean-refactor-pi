#!/usr/bin/env python3
"""Evaluate every unchecked pair of open good candidates without model calls."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from arena.campaign import merge_batch, run_dir


def _status(directory: Path, state: str, detail: dict | None = None) -> None:
    path = directory / "merge-worker.json"
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {"state": state, "pid": os.getpid(), "updated_at": time.time(), "detail": detail}, ensure_ascii=False
        )
    )
    temporary.replace(path)
    summary = ""
    if detail:
        pair = detail.get("parents") or []
        label = f"#{detail['node_number']}" if detail.get("node_number") else detail.get("reason", "")
        summary = f" pair={'+'.join(str(item)[:8] for item in pair)} result={label}"
    print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] merge worker {state}{summary}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    directory = run_dir(args.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "merge-worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        _status(directory, "starting")
        last_state = None
        while True:
            try:
                batch = merge_batch(args.run_id)
                result = batch["last"]
            except Exception as error:
                _status(directory, "error", {"error": repr(error)})
                raise
            if result is not None:
                _status(directory, "working", result)
                last_state = "working"
                if args.once:
                    return 0
                continue
            if last_state != "idle":
                _status(directory, "idle")
                last_state = "idle"
            if args.once:
                return 0
            if args.parent_pid:
                try:
                    os.kill(args.parent_pid, 0)
                except ProcessLookupError:
                    return 0
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
