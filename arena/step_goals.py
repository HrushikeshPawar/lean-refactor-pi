"""Capture the goal state before each top-level proof step."""

from __future__ import annotations

import json
import re
from pathlib import Path

from arena.engine import candidate_file, measure_version, problem, run_lean
from arena.steps import split_steps

LEAN_FILE = Path(__file__).with_name("lean") / "steps.lean"
STEP_TIMEOUT = 60
_RECORD = re.compile(r"^ARENA_STEPS (\{.*\})$", re.M)


def _lean_name(name: str) -> str:
    result = "Lean.Name.anonymous"
    for part in name.split("."):
        result = f"Lean.Name.str ({result}) {json.dumps(part)}"
    return result


def parse_step_goals(output: str, proof: str, shift: int = 0, start_line: int = 1) -> list[dict]:
    """Map wrapper records to proof steps and carry each state to the preceding step."""
    records: dict[int, str | None] = {}
    for raw in _RECORD.findall(output):
        record = json.loads(raw)
        proof_line = record["line"] - shift - start_line + 1
        text = record.get("text", "").strip() or None
        records[proof_line] = text

    steps = split_steps(proof)
    before = [records.get(step.first_line) for step in steps]
    return [
        {
            "id": step.id,
            "before": before[index],
            "after": before[index + 1] if index + 1 < len(steps) else None,
        }
        for index, step in enumerate(steps)
    ]


def step_goals(name: str, proof: str, lane: str = "background") -> list[dict]:
    """Run the per-step goal wrapper in the requested Lean lane."""
    row = problem(name)
    version, commit = measure_version(row)
    source = LEAN_FILE.read_text()
    inserted = source.replace("@@TARGET@@", _lean_name(name))
    built = candidate_file(row, proof, version, commit)
    text = built["text"][: built["head"]] + inserted + built["text"][built["head"] :]
    result = run_lean(
        row,
        built["path"],
        text,
        timeout=STEP_TIMEOUT,
        prefix_end=built["head"],
        lane=lane,
        request_class="opportunistic",
    )
    if result is None:
        raise ValueError("step-goal Lean job timed out")
    returncode, output = result
    if returncode != 0:
        detail = next((line.strip() for line in output.splitlines() if "error" in line.lower()), "Lean failed")
        raise ValueError(f"step-goal Lean job failed: {detail[:200]}")
    return parse_step_goals(output, proof, inserted.count("\n"), built["start_line"])
