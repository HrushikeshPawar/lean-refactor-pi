"""Kernel-term features of compiled proofs, read by a Lean metaprogram (arena/lean/route.lean).

Harness-only and separate from scoring: it runs after a candidate is scored, in its own Lean command,
so it never counts toward a candidate's heartbeats or tokens. Many proofs of one theorem can be read
in one Lean process; each is elaborated, read, and discarded in turn.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from arena.engine import candidate_file, measure_version, problem, run_lean

LEAN_FILE = Path(__file__).with_name("lean") / "route.lean"
_RECORD = re.compile(r"^ARENA_ROUTE (\{.*\})$", re.M)
_DECLARED = re.compile(r"(?:theorem|lemma|def)\s+([^\s:({\[]+)")
TIMEOUT = 120


def short_name(statement: str) -> str:
    """Last component of the declared name of a statement (`open X in theorem A.b ...` gives `b`)."""
    match = _DECLARED.search(statement)
    return match.group(1).rsplit(".", 1)[-1] if match else ""


def parse_features(output: str) -> dict[str, dict]:
    """The feature records in Lean's output, keyed by the tag each one was requested with."""
    found: dict[str, dict] = {}
    for line in _RECORD.findall(output):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        found[str(record.get("tag"))] = record
    return found


def extraction_text(name: str, proofs: dict[str, str]) -> tuple[Path, str, int]:
    """The pinned file with the extractor, then one `arena_route` command per proof (project path, text, head)."""
    row = problem(name)
    version, commit = measure_version(row)
    first = next(iter(proofs.values()))
    built = candidate_file(row, first, version, commit)
    text, head, offset = built["text"], built["head"], built["offset"]
    short = json.dumps(short_name(row["statement"]))
    # A doc comment or attribute list before the declaration belongs to its command.
    lead = text[head:offset]
    parts = [text[:head], LEAN_FILE.read_text().rstrip() + "\n\n"]
    for tag, proof in proofs.items():
        parts.append(f"arena_route {json.dumps(tag)} {short} {lead}{proof.rstrip()}\n\n")
    return built["path"], "".join(parts), head


def extract(name: str, proofs: dict[str, str], timeout: int = TIMEOUT) -> dict[str, dict]:
    """Features per tag; a proof the extractor could not read maps to {"ok": False, "error": ...}."""
    if not proofs:
        return {}
    row = problem(name)
    project, text, head = extraction_text(name, proofs)
    ran = run_lean(row, project, text, timeout=timeout, prefix_end=head)
    if ran is None:
        return {tag: {"tag": tag, "ok": False, "error": "timeout"} for tag in proofs}
    _, output = ran
    found = parse_features(output)
    reason = next((line for line in output.splitlines() if "error" in line), "no feature record")[:200]
    return {tag: found.get(tag, {"tag": tag, "ok": False, "error": reason}) for tag in proofs}
