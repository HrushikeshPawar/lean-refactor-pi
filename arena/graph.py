"""Pure candidate graph operations shared by the worker, frontier and viewer.

The graph ledger adds two events: ``edge`` records node lineage and operation
provenance, while ``focus`` records the current filing point independently of
lineage. ``step_goals`` records before/after states for each proof step, or an
error when background extraction fails. These records are append-only and do
not replace legacy campaign rows.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from functools import cache

from arena import goalstate
from arena.routes import proof_body
from arena.steps import Step, hdr_index, split_steps, step_range


def _replace_step_range(proof: str, first: Step, last: Step, replacement: str) -> str:
    if hdr_index(proof.split("\n")) is None:
        body = proof_body(proof)
        delimiter = proof.find(":=")
        start = proof.find(body, delimiter + 2) if body else delimiter + 2
        if start < 0:
            start = delimiter + 2
        original = proof[start:]
        value = textwrap.dedent(replacement).strip("\n")
        if first.indent:
            value = "\n".join(" " * first.indent + line if line.strip() else line for line in value.split("\n"))
        if original.endswith("\n") and value and not value.endswith("\n"):
            value += "\n"
        return proof[:start] + value
    lines = proof.splitlines(keepends=True)
    start, end = first.first_line - 1, last.last_line
    original = "".join(lines[start:end])
    ends_with_newline = original.endswith("\n")
    replacement_lines = textwrap.dedent(replacement).strip("\n").split("\n")
    indent = " " * first.indent
    body = "\n".join(indent + line if line.strip() else line for line in replacement_lines)
    if ends_with_newline:
        body += "\n"
    return "".join(lines[:start]) + body + "".join(lines[end:])


def splice_text(proof: str, spec: str, text: str) -> str:
    steps = split_steps(proof)
    first, last = step_range(steps, spec)
    return _replace_step_range(proof, first, last, text)


def merge_steps(base: str, takes: list[dict]) -> str:
    result = base
    seen: set[str] = set()
    for take in takes:
        ident = take["step"]
        if ident in seen:
            raise ValueError(f"duplicate step {ident}")
        seen.add(ident)
        target = next((step for step in split_steps(result) if step.id == ident), None)
        if target is None:
            raise ValueError(f"base has no step {ident}")
        donor = next((step for step in split_steps(take["text"]) if step.id == ident), None)
        if donor is None:
            raise ValueError(f"donor has no step {ident}")
        result = _replace_step_range(result, target, target, donor.text)
    return result


def _lines_of(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if len(line.strip()) >= 6 and line.strip() != "by"]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _lines_of(a), _lines_of(b), autojunk=False).ratio()


def measured_parent(texts: list[tuple[str, str]], text: str) -> tuple[str | None, float]:
    """Return the closest id among the 20 most recent earlier proofs; ties favor recency."""
    best_id, best_score = None, 0.0
    for proof_id, earlier in texts[-20:]:
        score = similarity(earlier, text)
        if score >= best_score:
            best_id, best_score = proof_id, score
    return best_id, best_score


# Fixed by decision 8; must not be tuned.
FILING_MIN_SIMILARITY = 0.50


@dataclass
class Node:
    id: str
    proof_id: str
    status: str
    origin: str
    score: float | None
    verified: bool
    tokens: int | None
    heartbeats: int | None
    versions: dict[str, bool]
    edge: dict | None
    steps: list[Step]
    depth: int


@dataclass
class Graph:
    nodes: list[Node]
    focus: str | None
    order: list[str]

    @classmethod
    def from_history(cls, history: list[dict], read_text: Callable[[str], str | None]) -> Graph:
        total_versions = len((history[0].get("versions") if history else None) or [1])
        proof_ids: list[str] = []
        entries: dict[str, dict] = {}
        evaluations: dict[str, list[tuple[str, dict]]] = {}
        probe_results: dict[str, dict] = {}
        edges: dict[str, dict] = {}
        step_goals: dict[str, list[dict]] = {}
        focus = None
        for event in history:
            kind = event.get("kind")
            if kind == "candidate":
                proof_id = event["candidate_id"]
                if proof_id not in entries:
                    proof_ids.append(proof_id)
                entries[proof_id] = event
            elif kind == "probe":
                proof_id = event["proof_id"]
                if proof_id not in entries:
                    proof_ids.append(proof_id)
                    entries[proof_id] = {"origin": "model"}
                probe_results[proof_id] = event["result"]
            elif kind == "evaluation":
                evaluations.setdefault(event["candidate_id"], []).append((event["mode"], event["result"]))
            elif kind == "edge":
                edges[event["proof_id"]] = event
            elif kind == "focus":
                focus = event["proof_id"]
            elif kind == "step_goals" and isinstance(event.get("goals"), list):
                step_goals[event["proof_id"]] = event["goals"]

        ids = {proof_id: f"n{index}" for index, proof_id in enumerate(proof_ids, 1)}
        nodes: list[Node] = []
        depths: dict[str, int] = {}
        for proof_id in proof_ids:
            candidates = evaluations.get(proof_id, [])
            ranked = []
            for mode, result in candidates:
                compat = result.get("compat") or {}
                status = (
                    "full"
                    if mode == "full"
                    and len(compat) == total_versions
                    and all(v.get("passed") for v in compat.values())
                    else ("primary" if next(iter(compat.values()), {}).get("passed") else "fail")
                )
                score = _score(result)
                ranked.append((status, score, result))
            full = [item for item in ranked if item[0] == "full"]
            primary = [item for item in ranked if item[0] == "primary"]
            best = (
                max(full, key=lambda item: item[1] if item[1] is not None else -1)
                if full
                else (
                    max(primary, key=lambda item: item[1] if item[1] is not None else -1)
                    if primary
                    else (ranked[-1] if ranked else None)
                )
            )
            result = best[2] if best else probe_results.get(proof_id, {})
            proof = read_text(proof_id) or ""
            passed_primary = next(iter((result.get("compat") or {}).values()), {}).get("passed", False)
            has_sorry = re.search(r"\bsorry\b", proof) is not None
            status = (
                "closed"
                if goalstate.closed(result) and not has_sorry
                else "sketch"
                if passed_primary and has_sorry
                else "broken"
            )
            edge = edges.get(proof_id)
            parents = (edge or {}).get("from") or []
            depth = depths.get(parents[0], -1) + 1 if parents else 0
            depths[proof_id] = depth
            verified = bool(best and best[0] == "full")
            steps = split_steps(proof)
            goals_by_id = {goal.get("id"): goal for goal in step_goals.get(proof_id, [])}
            steps = [
                replace(step, before=goals_by_id[step.id].get("before"), after=goals_by_id[step.id].get("after"))
                if step.id in goals_by_id
                else step
                for step in steps
            ]
            nodes.append(
                Node(
                    ids[proof_id],
                    proof_id,
                    status,
                    entries[proof_id].get("origin", "model"),
                    _score(result) if best else None,
                    verified,
                    result.get("tokens"),
                    result.get("heartbeat"),
                    {version: bool(value.get("passed")) for version, value in (result.get("compat") or {}).items()},
                    edge,
                    steps,
                    depth,
                )
            )
        return cls(nodes, focus, [node.id for node in nodes])


def _score(result: dict) -> float | None:
    metrics = result.get("metrics") or {}
    value = metrics.get("proxy")
    return value if value is not None else metrics.get("estimated_proxy")


def common_base(left: str, right: str, parents: dict[str, list[str]]) -> dict:
    @cache
    def ancestors(node: str) -> frozenset[str]:
        found = {node}
        for parent in parents[node]:
            found.update(ancestors(parent))
        return frozenset(found)

    shared = ancestors(left) & ancestors(right)
    maximal = [node for node in shared if not any(node != other and node in ancestors(other) for other in shared)]
    if len(maximal) != 1:
        return {"base": None, "reason": "ambiguous_common_base" if maximal else "no_common_base"}
    return {"base": maximal[0], "reason": None}


def _edits(base: list[str], variant: list[str]) -> list[dict]:
    matcher = SequenceMatcher(None, base, variant, autojunk=False)
    return [
        {"start": start, "end": end, "replacement": variant[other_start:other_end]}
        for tag, start, end, other_start, other_end in matcher.get_opcodes()
        if tag != "equal"
    ]


def edit_fingerprint(base: str, variant: str) -> set[str]:
    original = base.splitlines(keepends=True)
    return {
        "".join(original[edit["start"] : edit["end"]]) + "→" + "".join(edit["replacement"])
        for edit in _edits(original, variant.splitlines(keepends=True))
    }


def _conflict(a: dict, b: dict) -> bool:
    if a["start"] == a["end"] and b["start"] == b["end"]:
        return a["start"] == b["start"]
    if a["start"] == a["end"]:
        return b["start"] <= a["start"] < b["end"]
    if b["start"] == b["end"]:
        return a["start"] <= b["start"] < a["end"]
    return max(a["start"], b["start"]) < min(a["end"], b["end"])


def merge_text(base: str, left: str, right: str) -> dict:
    """Three-way line merge; reject ambiguity and preserve exact bytes."""
    base_lines = base.splitlines(keepends=True)
    left_edits = _edits(base_lines, left.splitlines(keepends=True))
    right_edits = _edits(base_lines, right.splitlines(keepends=True))
    details = {"left_edits": left_edits, "right_edits": right_edits}
    if not left_edits or not right_edits:
        return {**details, "text": None, "reason": "no_independent_edits"}
    if any(_conflict(a, b) for a in left_edits for b in right_edits):
        return {**details, "text": None, "reason": "overlapping_edits"}
    edits = sorted(left_edits + right_edits, key=lambda edit: (edit["start"], edit["end"]))
    output: list[str] = []
    cursor = 0
    for edit in edits:
        output.extend(base_lines[cursor : edit["start"]])
        output.extend(edit["replacement"])
        cursor = edit["end"]
    output.extend(base_lines[cursor:])
    text = "".join(output)
    if text in (left, right):
        return {**details, "text": None, "reason": "duplicate_parent"}
    return {**details, "text": text, "reason": None}


def ranked_frontier(nodes: list[dict]) -> list[dict]:
    """Rank exploration priority separately from verified proof quality."""
    eligible = [node for node in nodes if node.get("status") in ("full", "primary") and node.get("decision") != "park"]
    best = max((node.get("local_proxy") or 0 for node in eligible if node["status"] == "full"), default=0)
    result = []
    for node in eligible:
        quality = 40 * max(0, min(1, (node.get("local_proxy") or 0) / best)) if best else 0
        novelty = 20 * max(0, min(1, node.get("novelty", 0.5)))
        underexplored = 20 / (1 + len(node.get("children", [])))
        mergeability = min(20, 5 * node.get("merge_partners", 0))
        saturation = min(40, 6 * node.get("attempts_since_gain", 0))
        components = {
            "quality": round(quality, 2),
            "novelty": round(novelty, 2),
            "underexplored": round(underexplored, 2),
            "mergeability": mergeability,
            "saturation": -saturation,
        }
        result.append(
            {
                "candidate_id": node["id"],
                "status": node["status"],
                "local_proxy": node.get("local_proxy"),
                "tokens": node.get("tokens"),
                "priority": components,
                "priority_total": round(sum(components.values()), 2),
            }
        )
    result.sort(
        key=lambda row: (
            row["status"] != "full",
            -row["priority_total"],
            row["tokens"] if row["tokens"] is not None else 10**9,
            row["candidate_id"],
        )
    )
    return result
