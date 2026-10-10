#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign.

Every failure is one line of JSON: `{"ok": false, "error": "..."}`.
"""

import argparse
import json
import subprocess
from pathlib import Path

from arena.campaign import (
    autocheck,
    candidate,
    declarations,
    evaluate_request,
    find,
    frontier,
    init,
    probe,
    probe_batch,
    profile_request,
    record_idea,
    run_dir,
    set_decision,
    source_range,
    state,
    submission,
    write_state,
)
from arena.memory import memory

ACTIONS = (
    "init",
    "evaluate",
    "probe",
    "idea",
    "frontier",
    "candidate",
    "decision",
    "source",
    "declarations",
    "find",
    "profile",
    "autocheck",
    "state",
    "submission",
    "memory",
)


def run(args: argparse.Namespace) -> dict:
    if args.action == "init":
        return init(args.theorem, args.run_id)
    if args.action == "evaluate":
        proof = args.proof_file.read_text() if args.proof_file else None
        return evaluate_request(
            args.theorem,
            args.run_id,
            proof,
            args.mode,
            args.parent,
            args.hypothesis,
            args.idea_id,
            args.candidate,
            args.from_probe,
        )
    if args.action == "probe":
        parent = args.parent[0] if args.parent else None
        if args.draft_file:
            if args.proof_file:
                raise ValueError("Use proof-file or draft-file, not both")
            return probe_batch(
                args.theorem, args.run_id, [path.read_text() for path in args.draft_file], args.idea_id, parent
            )
        if args.proof_file:
            return probe(args.theorem, args.run_id, args.proof_file.read_text(), args.idea_id, parent)
        raise ValueError("Pass proof-file or one to four draft-file values")
    if args.action == "idea":
        return record_idea(
            args.run_id,
            args.title,
            args.hypothesis,
            args.region,
            json.loads(args.expected_effect) if args.expected_effect else None,
            args.idea_id,
            args.status,
            args.reason,
        )
    if args.action == "frontier":
        return frontier(args.run_id)
    if args.action == "candidate":
        return candidate(args.theorem, args.run_id, args.candidate)
    if args.action == "decision":
        return set_decision(args.run_id, args.candidate, args.decision, args.reason)
    if args.action == "profile":
        return profile_request(
            args.theorem, args.run_id, args.candidate, args.proof_file.read_text() if args.proof_file else None
        )
    if args.action == "autocheck":
        return autocheck(args.theorem, args.run_id, args.max_seconds)
    if args.action == "state":
        return state(args.run_id)
    if args.action == "memory":
        return memory(args.run_id, args.spent_usd, args.cap_usd)
    if args.action == "submission":
        return submission(args.run_id)
    if args.action == "source":
        return source_range(args.theorem, args.handle, args.first, args.last)
    if args.action == "declarations":
        return declarations(args.theorem, json.loads(args.items) if args.items else None, args.cursor)
    if args.action == "find":
        return find(args.theorem, json.loads(args.queries), args.limit)
    raise ValueError(f"Unsupported action: {args.action}")


def publish_state(run_id: str) -> None:
    """Refresh state.json after every action; it is derived data, so failures are ignored."""
    try:
        if (run_dir(run_id) / "ledger.jsonl").exists():
            write_state(run_id)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--proof-file", type=Path)
    parser.add_argument("--draft-file", type=Path, action="append", default=[])
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--idea-id")
    parser.add_argument("--candidate", help="#N (or probe pN for the candidate action)")
    parser.add_argument("--from-probe")
    parser.add_argument("--handle")
    parser.add_argument("--first", type=int)
    parser.add_argument("--last", type=int)
    parser.add_argument("--items")
    parser.add_argument("--queries")
    parser.add_argument("--cursor")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--decision", choices=("pursue", "park"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--title")
    parser.add_argument("--region")
    parser.add_argument("--expected-effect")
    parser.add_argument("--status")
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--spent-usd", type=float)
    parser.add_argument("--cap-usd", type=float)
    args = parser.parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False))
        publish_state(args.run_id)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        message = " ".join(str(error).split()) or type(error).__name__
        print(json.dumps({"ok": False, "error": message[:400]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
