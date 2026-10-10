#!/usr/bin/env python3
"""Check or reapply the vendored Langfuse Pi plugin patch.

python tools/langfuse_plugin.py --check
python tools/langfuse_plugin.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.traces import apply_plugin, plugin_problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Fail when the installed plugin is not patched 0.1.2")
    mode.add_argument("--apply", action="store_true", help="Reapply the vendored patch onto an unpatched 0.1.2 install")
    args = parser.parse_args()
    if args.apply:
        try:
            print(apply_plugin())
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 1
    problems = plugin_problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if not args.apply:
        print("patched Langfuse plugin 0.1.2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
