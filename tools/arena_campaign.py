#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign.

Every failure is one line of JSON: `{"ok": false, "error": "..."}`.
"""

import argparse
import json
import subprocess
from pathlib import Path

from arena.campaign import (candidate, declaration, evaluate_request, frontier, init, probe,
                            profile_request, record_idea, set_decision, source_range)

ACTIONS = ("init", "evaluate", "probe", "idea", "frontier", "candidate", "decision", "source",
           "declaration", "profile")


def run(args: argparse.Namespace) -> dict:
    if args.action == "init":
        return init(args.theorem, args.run_id)
    if args.action == "evaluate":
        proof = args.proof_file.read_text() if args.proof_file else None
        return evaluate_request(args.theorem, args.run_id, proof, args.mode, args.parent,
                                args.hypothesis, args.idea_id, args.candidate, args.from_probe)
    if args.action == "probe":
        return probe(args.theorem, args.run_id, args.proof_file.read_text(), args.idea_id,
                     args.parent[0] if args.parent else None)
    if args.action == "idea":
        return record_idea(args.run_id, args.title, args.hypothesis, args.region,
                           json.loads(args.expected_effect) if args.expected_effect else None,
                           args.idea_id, args.status, args.reason)
    if args.action == "frontier":
        return frontier(args.run_id)
    if args.action == "candidate":
        return candidate(args.theorem, args.run_id, args.candidate)
    if args.action == "decision":
        return set_decision(args.run_id, args.candidate, args.decision, args.reason)
    if args.action == "profile":
        return profile_request(args.theorem, args.run_id, args.candidate,
                               args.proof_file.read_text() if args.proof_file else None)
    if args.action == "source":
        return source_range(args.theorem, args.path, args.first, args.last)
    return declaration(args.theorem, args.symbol)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--proof-file", type=Path)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--idea-id")
    parser.add_argument("--candidate", help="#N (or probe pN for the candidate action)")
    parser.add_argument("--from-probe")
    parser.add_argument("--path")
    parser.add_argument("--first", type=int)
    parser.add_argument("--last", type=int)
    parser.add_argument("--symbol")
    parser.add_argument("--decision", choices=("pursue", "park"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--title")
    parser.add_argument("--region")
    parser.add_argument("--expected-effect")
    parser.add_argument("--status")
    args = parser.parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        message = " ".join(str(error).split()) or type(error).__name__
        print(json.dumps({"ok": False, "error": message[:400]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
