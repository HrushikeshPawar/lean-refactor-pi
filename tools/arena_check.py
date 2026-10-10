#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.forbidden import FORBIDDEN, remove_comments


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proof-name", required=True)
    ap.add_argument("--temp-file-path", required=True)
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--upstream-checker", required=True)
    args = ap.parse_args()

    temp_file = Path(args.temp_file_path).resolve()

    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", args.proof_name)
    expected_suffix = f"_{sanitized}"

    if temp_file.suffix != ".lean" or not temp_file.stem.endswith(expected_suffix):
        print(
            "ARENA_CHECK_ERROR: --temp-file-path does not match the expected "
            f"Lean candidate naming convention: *{expected_suffix}.lean"
        )
        return 2

    original_stem = temp_file.stem[: -len(expected_suffix)]
    original_file = temp_file.with_name(original_stem + ".lean")

    if not temp_file.is_file():
        print(f"ARENA_CHECK_ERROR: candidate Lean file does not exist: {temp_file}")
        return 2

    if not original_file.is_file():
        print(f"ARENA_CHECK_ERROR: original Lean file does not exist: {original_file}")
        return 2

    proof_path = Path(args.task_dir) / "current_proof.txt"
    proof = proof_path.read_text()
    clean = remove_comments(proof)

    occurrences = temp_file.read_text().count(proof.strip())
    if occurrences != 1:
        print(
            "ARENA_CHECK_ERROR: current_proof.txt must occur exactly once in "
            f"the candidate Lean file; found {occurrences}"
        )
        return 2

    for label, pattern in FORBIDDEN:
        if pattern.search(clean):
            print(f"ARENA_REJECTED: proof contains forbidden construct `{label}`")
            return 0

    cmd = [
        sys.executable,
        args.upstream_checker,
        "--proof-name",
        args.proof_name,
        "--temp-file-path",
        args.temp_file_path,
        "--task-dir",
        args.task_dir,
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )

    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)

    if proc.returncode != 0:
        return proc.returncode

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")

    reject_markers = (
        "FILE_MODIFIED:",
        "STATEMENT_MODIFIED:",
        "INCOMPLETE_PROOF:",
        "MISSING_FILES:",
        "ERROR:",
        "WARNING:",
    )

    if any(marker in output for marker in reject_markers):
        return 2

    if "IMPROVED:" in output or "NOT_IMPROVED:" in output:
        return 0

    print("ARENA_CHECK_ERROR: upstream checker returned no recognized accept/reject status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
