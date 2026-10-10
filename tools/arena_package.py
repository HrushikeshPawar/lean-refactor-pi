#!/usr/bin/env python3
"""Stage a manual Arena submission under runs/submission-staging/<name>/. Never uploads anything."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena import package  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="+", help="v6 run IDs under runs/pi-budget")
    parser.add_argument("--name", required=True, help="staging directory name")
    parser.add_argument("--commit", default="HEAD", help="harness commit to archive (default HEAD)")
    parser.add_argument(
        "--template", type=Path, help="report template with $title $approach $models $budget $reproduction"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="also count every other run of the same problem under runs/pi-budget against the $3 ceiling "
        "(by default only the listed runs count, so list every run of the campaign)",
    )
    args = parser.parse_args()
    template = Template(args.template.read_text()) if args.template else None
    try:
        out = package.stage(args.name, args.run_ids, commit=args.commit, template=template, discover=args.discover)
    except package.PackageError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(f"staged {out}\nUpload manually; nothing was sent anywhere.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
