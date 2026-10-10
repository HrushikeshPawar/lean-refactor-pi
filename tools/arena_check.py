#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Synced from pinned Lean Refactor Arena Space app.py.
FORBIDDEN = [
    ("#eval", re.compile(r"#\s*eval\b")),
    ("#reduce", re.compile(r"#\s*reduce\b")),
    ("IO.", re.compile(r"\bIO\.")),
    ("unsafe def/fun/theorem", re.compile(r"\bunsafe\s+(def|fun|theorem|lemma)\b")),
    ("extern", re.compile(r"\bextern\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("@[implemented_by]", re.compile(r"@\[\s*implemented[_]?[Bb]y\b")),
    ("@[extern]", re.compile(r"@\[\s*extern\b")),
    ("sorry", re.compile(r"\bsorry\b")),
    ("sorryAx", re.compile(r"\bsorryAx\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("ofReduceBool", re.compile(r"\bofReduceBool\b")),
    ("ofReduceNat", re.compile(r"\bofReduceNat\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("#exit", re.compile(r"#\s*exit\b")),
    ("#count_heartbeats", re.compile(r"#\s*count_heartbeats\b")),
    ("attribute command", re.compile(r"(?m)^\s*attribute\b")),
    (
        "macro/elab/notation",
        re.compile(r"\b(macro|macro_rules|elab|elab_rules|notation|syntax)\b"),
    ),
    ("deriving instance", re.compile(r"\bderiving\s+instance\b")),
    (
        "auxiliary declaration",
        re.compile(r"(?m)^\s*(def|abbrev|instance|structure|inductive|class|opaque)\b"),
    ),
]


def remove_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == '"':
            out.append(text[i])
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue

        if text.startswith("/-", i):
            depth = 1
            i += 2
            while i < n and depth:
                if text.startswith("/-", i):
                    depth += 1
                    i += 2
                elif text.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue

        if text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
            continue

        out.append(text[i])
        i += 1

    return "".join(out)


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
