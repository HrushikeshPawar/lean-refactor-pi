#!/usr/bin/env python3
"""Reproduction CLI; Pi extension is the model-facing interface."""

import argparse
import json
from pathlib import Path

from arena.engine import evaluate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("proof_file", type=Path)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    args = parser.parse_args()
    try:
        result = evaluate(args.name, args.proof_file.read_text(), args.mode)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "name": args.name, "mode": args.mode,
                          "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
