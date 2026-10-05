"""Run one fresh, budgeted Arena theorem session through Pi's JSON mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.campaign import init, packet, run_dir


ROOT = Path(__file__).resolve().parents[1]
MODELS = ("gpt-6-luna", "deepseek-v4.1-flash")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--prompt-file", type=Path, help="Optional extra instructions appended after the source packet")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--hard-cap-usd", type=float, default=1.0)
    parser.add_argument("--resume-run", action="store_true", help="Resume the exact Pi session and cost ledger")
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without launching Pi")
    args = parser.parse_args()

    if not math.isfinite(args.hard_cap_usd) or not 0.1 <= args.hard_cap_usd <= 3:
        parser.error("--hard-cap-usd must be between 0.10 and 3.00")

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", args.run_id):
        parser.error("--run-id must be a Pi-compatible session ID")
    rows = (json.loads(line) for line in (ROOT / "benchmark/original/warmup.jsonl").read_text().splitlines())
    if args.theorem not in {row["name"] for row in rows}:
        parser.error(f"unknown warm-up theorem: {args.theorem}")
    extra = args.prompt_file.read_text().strip() if args.prompt_file else ""

    directory = run_dir(args.run_id)
    if directory.exists() != args.resume_run:
        parser.error("--resume-run must be used exactly when the run ID already exists")
    if args.resume_run:
        config = json.loads((directory / "run-config.json").read_text())
        if (config["theorem"], config["model"], config["hard_cap_usd"]) != (args.theorem, args.model, args.hard_cap_usd):
            parser.error("resume theorem, model, or cap differs from the original run")
        prompt = "Resume the existing Arena run from its recorded candidate frontier. Continue improving the proof."
    else:
        prompt = packet(args.theorem) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
    command = [
        "pi", "--offline", "--approve", "--mode", "json",
        "--no-builtin-tools", "--no-context-files",
        "--extension", str(ROOT / "packages/arena-pi/extensions/arena.ts"),
        "--model", f"arena-budget/{args.model}",
        "--session-id", args.run_id,
        "--session-dir", str(directory / "session"),
        "--name", f"{args.theorem} | {args.model} | {args.run_id}",
        "--", f"/arena {args.theorem}", prompt,
    ]
    if args.dry_run:
        print(f"Validated {args.theorem} with {args.model}; session {args.run_id}; cap ${args.hard_cap_usd:g}")
        print("Pi will write packet, candidate ledger, events, cost, and session under", directory)
        return 0

    if not args.resume_run:
        init(args.theorem, args.run_id, extra)
        (directory / "run-config.json").write_text(json.dumps({"theorem": args.theorem,
            "model": args.model, "hard_cap_usd": args.hard_cap_usd,
            "packet_sha256": hashlib.sha256(prompt.encode()).hexdigest()}, indent=2) + "\n")
    shadow = directory / "scratch" / "project"
    env = os.environ.copy()
    env["ARENA_BUDGET_REQUIRED"] = "1"
    env["ARENA_AUTOCONTINUE"] = "1"
    env["ARENA_RUN_ID"] = args.run_id
    env["ARENA_MODEL"] = args.model
    env["ARENA_HARD_CAP_USD"] = str(args.hard_cap_usd)
    env.pop("ARENA_STOP_USD", None)
    env["ARENA_BUDGET_REPORT_PATH"] = str(directory / "cost.json")
    with (directory / "events.jsonl").open("a") as output:
        completed = subprocess.run(command, cwd=shadow, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, check=False)
    report_path = directory / "cost.json"
    print(f"Pi exit={completed.returncode}; events={directory / 'events.jsonl'}; cost={report_path}")
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
    if report["hard_cap_usd"] != args.hard_cap_usd or report["spent_usd"] + report.get("unresolved_usd", 0) > args.hard_cap_usd:
        print("Arena hard cap exceeded", file=sys.stderr)
        return 1
    with (directory / "events.jsonl").open() as events:
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
