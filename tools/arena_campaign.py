#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign."""

import argparse
import json
from pathlib import Path

from arena.campaign import candidate, declaration, frontier, init, record_evaluation, source_range, set_decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "evaluate", "frontier", "candidate", "decision", "source", "declaration"))
    parser.add_argument("--theorem", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--proof-file", type=Path)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--hypothesis", default="")
    parser.add_argument("--candidate-id")
    parser.add_argument("--path")
    parser.add_argument("--first", type=int)
    parser.add_argument("--last", type=int)
    parser.add_argument("--symbol")
    parser.add_argument("--decision", choices=("pursue", "park"))
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    try:
        if args.action == "init":
            result = init(args.theorem, args.run_id)
        elif args.action == "evaluate":
            result = record_evaluation(args.theorem, args.run_id, args.proof_file.read_text(),
                                       args.mode, args.parent, args.hypothesis)
        elif args.action == "frontier":
            result = frontier(args.run_id)
        elif args.action == "candidate":
            result = candidate(args.theorem, args.run_id, args.candidate_id)
        elif args.action == "decision":
            result = set_decision(args.run_id, args.candidate_id, args.decision, args.reason)
        elif args.action == "source":
            result = source_range(args.theorem, args.path, args.first, args.last)
        else:
            result = declaration(args.theorem, args.symbol)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
