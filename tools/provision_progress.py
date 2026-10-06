#!/usr/bin/env python3
"""Live progress of workspace provisioning, read from runs/provision/<source>-<version>.log.

    python tools/provision_progress.py                 # once
    python tools/provision_progress.py --watch         # refresh every 3 s until everything is done
    python tools/provision_progress.py --only cslib-v4.32.0 physlib-v4.32.0
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "runs" / "provision"
# Stages in order, with the share of total time each usually takes.
STAGES = [("clone", "git clone", 0.05), ("checkout", "git worktree add --detach", 0.05),
          ("seed Mathlib", "remote.origin.url", 0.05), ("Mathlib cache", "lake exe cache get", 0.35),
          ("build", "lake build", 0.50)]
DEFAULT = ["cslib-v4.33.0-rc2", "cslib-v4.32.0", "cslib-v4.31.0", "physlib-v4.32.0"]
BAR = 28


def status(name: str) -> tuple[float, str, bool, bool]:
    """(fraction done, what is happening, finished, failed) for one environment."""
    log = LOGS / f"{name}.log"
    if not log.exists():
        return 0.0, "waiting to start", False, False
    text = log.read_text(errors="ignore")
    # Only the latest attempt counts; earlier, interrupted attempts stay in the log above it.
    text = text[text.rfind("=== provisioning"):] if "=== provisioning" in text else text
    commands = [m for m in re.finditer(r"^\$ (.*)$", text, re.M)]
    if not commands:
        return 0.0, "starting", False, False
    last = commands[-1]
    tail = text[last.end():]
    stage_index = max((i for i, (_, marker, _) in enumerate(STAGES) if marker in last[1]), default=0)
    done_share = sum(share for _, _, share in STAGES[:stage_index])
    share = STAGES[stage_index][2]
    exit_code = re.search(r"\[exit (\d+) after (\d+)s\]", tail)
    if exit_code and exit_code[1] != "0":
        return done_share, f"FAILED at {STAGES[stage_index][0]} (see {log.name})", True, True
    if exit_code and STAGES[stage_index][0] == "build":
        return 1.0, f"done (build {exit_code[2]}s)", True, False
    inner, detail = 0.0, ""
    if STAGES[stage_index][0] == "build":
        steps = re.findall(r"\[(\d+)/(\d+)\]", tail)
        if steps:
            current, total = map(int, steps[-1])
            inner, detail = current / total, f" {current}/{total} modules"
    elif STAGES[stage_index][0] == "Mathlib cache":
        if "downloading https://releases.lean-lang.org" in tail and "installing" not in tail:
            detail = " (downloading Lean toolchain)"
        elif "cloning" in tail and "Built Cache" not in tail:
            detail = " (fetching small dependencies)"
        elif "Decompress" in tail or "unpack" in tail.lower():
            inner, detail = 0.8, " (unpacking)"
        else:
            inner, detail = 0.4, " (downloading cache files)"
    elif exit_code:
        inner = 1.0
    return done_share + share * inner, f"{STAGES[stage_index][0]}{detail}", False, False


def render(names: list[str]) -> tuple[str, bool]:
    lines, overall, finished = [], 0.0, True
    for name in names:
        fraction, what, done, failed = status(name)
        overall += fraction
        finished &= done
        filled = int(BAR * fraction)
        mark = "✗" if failed else "✓" if done else "…"
        lines.append(f"{mark} {name:20} [{'█' * filled}{'·' * (BAR - filled)}] {100 * fraction:3.0f}%  {what}")
    overall /= max(1, len(names))
    filled = int(BAR * overall)
    lines.append(f"\n  {'overall':20} [{'█' * filled}{'·' * (BAR - filled)}] {100 * overall:3.0f}%  "
                 f"({time.strftime('%H:%M:%S')})")
    return "\n".join(lines), finished


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--only", nargs="+", default=DEFAULT, help="Environments as <source>-<version>")
    args = parser.parse_args()
    while True:
        text, finished = render(args.only)
        print(("\033[2J\033[H" if args.watch else "") + text, flush=True)
        if not args.watch or finished:
            return 0
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
