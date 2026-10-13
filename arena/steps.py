"""Parse top-level tactic steps from a proof."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from arena.routes import proof_body


@dataclass
class StepNode:
    start: int
    end: int
    parent: StepNode | None
    kids: list[StepNode]


@dataclass(frozen=True)
class Step:
    id: str
    first_line: int
    last_line: int
    text: str
    hash: str
    indent: int
    before: str | None = None
    after: str | None = None


def hdr_index(lines: list[str]) -> int | None:
    return next((i for i, line in enumerate(lines) if line.strip().endswith(":= by")), None)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def build(lines: list[str], lo: int, hi: int, parent: StepNode | None) -> list[StepNode]:
    indexes = [i for i in range(lo, hi) if lines[i].strip() and not lines[i].lstrip().startswith("--")]
    if not indexes:
        return []
    minimum = min(_indent(lines[i]) for i in indexes)
    starts = [i for i in indexes if _indent(lines[i]) == minimum]
    nodes: list[StepNode] = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else hi
        node = StepNode(start, end, parent, [])
        node.kids = build(lines, start + 1, end, node)
        nodes.append(node)
    return nodes


def parse(lines: list[str]) -> list[StepNode] | None:
    """Return the proof's top-level step tree, or None when no tactic steps exist."""
    header = hdr_index(lines)
    if header is None:
        return None
    nodes = build(lines, header + 1, len(lines), None)
    return nodes or None


def _step(text: str, ident: str, first_line: int, last_line: int, indent: int) -> Step:
    normalized = re.sub(r"\s+", " ", text)
    digest = hashlib.sha1(normalized.encode()).hexdigest()[:10]
    return Step(ident, first_line, last_line, text, digest, indent)


def split_steps(proof: str) -> list[Step]:
    lines = proof.split("\n")
    roots = parse(lines)
    if roots:
        steps = []
        for index, node in enumerate(roots, 1):
            end = node.end
            while end > node.start and not lines[end - 1].strip():
                end -= 1
            first_line = node.start + 1
            last_line = max(node.start, end - 1) + 1
            text = "\n".join(lines[node.start : end])
            steps.append(_step(text, f"s{index}", first_line, last_line, _indent(lines[node.start])))
        return steps

    body = proof_body(proof)
    if not body.strip():
        body = ""
    delimiter = proof.find(":=")
    body_start = proof.find(body, delimiter + 2) if body else delimiter + 2
    if body_start < 0:
        body_start = delimiter + 2
    first_line = proof.count("\n", 0, max(0, body_start)) + 1
    body_lines = body.split("\n") if body else [""]
    last_line = max(first_line, first_line + len(body_lines) - 1)
    indent = min((_indent(line) for line in body_lines if line.strip()), default=0)
    return [_step(body, "s1", first_line, last_line, indent)]


def step_range(steps: list[Step], spec: str) -> tuple[Step, Step]:
    valid = f"s1-s{len(steps)}" if steps else "none"
    match = re.fullmatch(r"(s[1-9][0-9]*)(?:-(s[1-9][0-9]*))?", spec)
    by_id = {step.id: index for index, step in enumerate(steps)}
    if not match:
        raise ValueError(f"unknown step range {spec}; steps are {valid}")
    first_id, last_id = match.group(1), match.group(2) or match.group(1)
    if first_id not in by_id:
        raise ValueError(f"unknown step {first_id}; steps are {valid}")
    if last_id not in by_id:
        raise ValueError(f"unknown step {last_id}; steps are {valid}")
    first, last = by_id[first_id], by_id[last_id]
    if first > last:
        raise ValueError(f"reversed step range {spec}; steps are {valid}")
    return steps[first], steps[last]
