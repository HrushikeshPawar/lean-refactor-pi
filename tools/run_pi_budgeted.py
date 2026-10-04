"""Run one fresh, budgeted Arena theorem session through Pi's JSON mode."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODELS = ("gpt-6-luna", "deepseek-v4.1-flash")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hard-cap-usd", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without launching Pi")
    args = parser.parse_args()

    if not math.isfinite(args.hard_cap_usd) or not 0 < args.hard_cap_usd <= 3:
        parser.error("--hard-cap-usd must be greater than zero and at most 3")

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.run_id):
        parser.error("--run-id must be a Pi-compatible session ID")
    rows = (json.loads(line) for line in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines())
    if args.theorem not in {row["name"] for row in rows}:
        parser.error(f"unknown warm-up theorem: {args.theorem}")
    prompt = args.prompt_file.read_text().strip()
    if not prompt:
        parser.error("prompt file is empty")

    run_dir = ROOT / "runs" / "pi-budget" / args.run_id
    if run_dir.exists():
        parser.error(f"run ID already exists: {run_dir}")
    command = [
        "pi", "--offline", "--approve", "--mode", "json",
        "--no-builtin-tools", "--no-context-files",
        "--extension", str(ROOT / "packages/arena-pi/extensions/arena.ts"),
        "--model", f"arena-budget/{args.model}",
        "--session-id", args.run_id,
        "--session-dir", str(run_dir / "session"),
        "--name", f"{args.theorem} | {args.model} | {args.run_id}",
        "--", f"/arena {args.theorem}", prompt,
    ]
    if args.dry_run:
        print(f"Validated {args.theorem} with {args.model}; session {args.run_id}; cap ${args.hard_cap_usd:g}")
        print("Pi will write events.jsonl, cost.json, and session files under", run_dir)
        return 0

    run_dir.mkdir(parents=True)
    env = os.environ.copy()
    env["ARENA_BUDGET_REQUIRED"] = "1"
    env["ARENA_HARD_CAP_USD"] = str(args.hard_cap_usd)
    env.pop("ARENA_STOP_USD", None)
    env["ARENA_BUDGET_REPORT_PATH"] = str(run_dir / "cost.json")
    with (run_dir / "events.jsonl").open("w") as output:
        completed = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, check=False)
    report_path = run_dir / "cost.json"
    print(f"Pi exit={completed.returncode}; events={run_dir / 'events.jsonl'}; cost={report_path}")
    if completed.returncode:
        return completed.returncode
    if not report_path.exists():
        print("Pi did not produce a cost report", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text())
    if report.get("error") or report.get("theorem") != args.theorem:
        print(f"Invalid cost report: {report.get('error', 'theorem mismatch')}",
              file=sys.stderr)
        return 1
    if report["hard_cap_usd"] != args.hard_cap_usd or report["spent_usd"] > args.hard_cap_usd:
        print("Arena hard cap exceeded", file=sys.stderr)
        return 1
    with (run_dir / "events.jsonl").open() as events:
        for line in events:
            event = json.loads(line)
            if event.get("type") == "message_end":
                message = event.get("message", {})
                if message.get("role") == "assistant" and message.get("stopReason") in ("error", "aborted"):
                    print("Pi ended with a model error or abort; inspect events.jsonl",
                          file=sys.stderr)
                    return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
