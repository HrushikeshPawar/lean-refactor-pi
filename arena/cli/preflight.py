#!/usr/bin/env python3
"""Cheap live proof that one Arena run is readable in Langfuse before a paid matrix.

One real request per selected model, plus the read-only arena_skill_read tool. arena_state
belongs to a later ticket, so the harmless model-visible tool is the skill listing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

from arena.campaign import run_dir
from arena.cli.run import MODELS
from arena.engine import ROOT
from arena.traces import (
    PATCH_SHA256,
    list_observations,
    plugin_problems,
    preflight_problems,
    read_journal,
    write_receipt,
)


def execute(theorem: str = "Core.InitsUpdatesComm", models_csv: str | None = None, json_output: bool = False) -> int:
    models = [item.strip() for item in (models_csv or ",".join(MODELS)).split(",") if item.strip()]
    unknown = [model for model in models if model not in MODELS]
    if unknown or len(models) != len(set(models)):
        print(f"error: models must be distinct members of {', '.join(MODELS)}", file=sys.stderr)
        return 2
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
                "-m",
                "arena.cli",
                "run",
                "--model",
                model,
                "--theorem",
                theorem,
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
        trace_ids = sorted({trace_id for row in observations if isinstance((trace_id := row.get("traceId")), str)})
        if not json_output:
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
    if json_output:
        print(json.dumps(receipt, ensure_ascii=False))
    if receipt["status"] != "pass":
        if not json_output:
            print("preflight failed", file=sys.stderr)
        return 1
    if not json_output:
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
