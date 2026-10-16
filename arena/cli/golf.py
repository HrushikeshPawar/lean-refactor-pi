"""Offline golf pass over a loose proof file."""

from __future__ import annotations

import sys
from pathlib import Path

from arena import golf
from arena.engine import problem, validate_proof

DEFAULT_SECONDS = 600.0


def execute(theorem: str, proof_file: Path, out: Path, seconds: float = DEFAULT_SECONDS) -> int:
    try:
        proof = proof_file.read_text().strip()
        validate_proof(problem(theorem), proof)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if seconds <= 0:
        print("error: --seconds must be above 0", file=sys.stderr)
        return 2
    outcome, best = golf.golf_file(theorem, proof, seconds)
    print(golf.summary_line(outcome), flush=True)
    if outcome.reason and not outcome.tried:
        print(f"error: {outcome.reason}; nothing written", file=sys.stderr)
        return 2
    golf.write_result(out, best)
    if best != proof:
        note = ""
    elif outcome.accepted:
        note = " (unchanged: no accepted variant passed the final full cold check)"
    else:
        note = " (unchanged: no variant beat the proof)"
    print(f"Wrote {out}{note}")
    return 0
