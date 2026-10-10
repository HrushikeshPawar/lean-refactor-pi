#!/usr/bin/env python3
"""Cheap live proof that one Arena run is readable in Langfuse before a paid matrix.

One real request per selected model, plus the read-only arena_skill_read tool. arena_state
belongs to a later ticket, so the harmless model-visible tool is the skill listing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.campaign import run_dir
from arena.traces import (
    PATCH_SHA256,
    list_observations,
    plugin_problems,
    preflight_problems,
    read_journal,
    write_receipt,
)
from tools.run_pi_budgeted import MODELS

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theorem", default="Core.InitsUpdatesComm")
    parser.add_argument("--models", default=",".join(MODELS), help="Comma-separated Arena models")
    args = parser.parse_args()
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    unknown = [model for model in models if model not in MODELS]
    if unknown or len(models) != len(set(models)):
        parser.error(f"models must be distinct members of {', '.join(MODELS)}")
    problems = plugin_problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    covered = {}
    failed = False
    for model in models:
        run_id = f"preflight-{model.replace('.', '-')}-{uuid.uuid4().hex[:8]}"
        started = datetime.now(UTC)
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/run_pi_budgeted.py"),
                "--model",
                model,
                "--theorem",
                args.theorem,
                "--run-id",
                run_id,
                "--limit-usd",
                "0.10",
                "--thinking",
                "off",
                "--no-mcp",
                "--preflight",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=300,
        )
        directory = run_dir(run_id)
        journal_path = directory / "trace-journal.jsonl"
        journal = read_journal(journal_path)
        observations, problems = _wait(run_id, started, journal)
        trace_ids = sorted({row.get("traceId") for row in observations if row.get("traceId")})
        print(
            f"{model} session={run_id} exit={proc.returncode} observations={len(observations)} traces={','.join(trace_ids)}"
        )
        if proc.returncode != 0 or problems:
            failed = True
            print(proc.stderr[-1500:], file=sys.stderr)
            for item in problems:
                print(item, file=sys.stderr)
            continue
        # The journal is opened 0600, but a filesystem that ignores chmod (fuseblk) keeps its own
        # mode; record what the file really has rather than claim owner-only access.
        covered[model] = {
            "session_id": run_id,
            "trace_ids": trace_ids,
            "journal_mode": oct(journal_path.stat().st_mode & 0o777),
        }
    receipt = {
        "status": "pass" if covered and not failed and set(covered) == set(models) else "fail",
        "patch_sha256": PATCH_SHA256,
        "models": covered,
    }
    write_receipt(receipt)
    if receipt["status"] != "pass":
        print("preflight failed", file=sys.stderr)
        return 1
    print(f"preflight passed for {', '.join(models)}")
    return 0


def _wait(run_id: str, started: datetime, journal: list[dict]) -> tuple[list[dict], list[str]]:
    deadline = time.monotonic() + 30
    observations: list[dict] = []
    problems = ["missing Langfuse observations"]
    while time.monotonic() < deadline:
        try:
            observations = list_observations(run_id, started)
        except RuntimeError as error:
            problems = [str(error)]
            time.sleep(2)
            continue
        problems = preflight_problems(journal, observations)
        if not problems:
            return observations, []
        if not any("missing" in item or "unjoinable" in item for item in problems):
            return observations, problems
        time.sleep(2)
    return observations, problems


if __name__ == "__main__":
    raise SystemExit(main())
