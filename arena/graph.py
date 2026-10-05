"""Pure candidate graph operations shared by the worker, frontier and viewer."""

from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache


def common_base(left: str, right: str, parents: dict[str, list[str]]) -> dict:
    @lru_cache(maxsize=None)
    def ancestors(node: str) -> frozenset[str]:
        found = {node}
        for parent in parents[node]:
            found.update(ancestors(parent))
        return frozenset(found)

    shared = ancestors(left) & ancestors(right)
    maximal = [node for node in shared if not any(node != other and node in ancestors(other)
                                                   for other in shared)]
    if len(maximal) != 1:
        return {"base": None, "reason": "ambiguous_common_base" if maximal else "no_common_base"}
    return {"base": maximal[0], "reason": None}


def _edits(base: list[str], variant: list[str]) -> list[dict]:
    matcher = SequenceMatcher(None, base, variant, autojunk=False)
    return [{"start": start, "end": end, "replacement": variant[other_start:other_end]}
            for tag, start, end, other_start, other_end in matcher.get_opcodes() if tag != "equal"]


def edit_fingerprint(base: str, variant: str) -> set[str]:
    original = base.splitlines(keepends=True)
    return {"".join(original[edit["start"]:edit["end"]]) + "→" + "".join(edit["replacement"])
            for edit in _edits(original, variant.splitlines(keepends=True))}


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
        output.extend(base_lines[cursor:edit["start"]])
        output.extend(edit["replacement"])
        cursor = edit["end"]
    output.extend(base_lines[cursor:])
    text = "".join(output)
    if text == left or text == right:
        return {**details, "text": None, "reason": "duplicate_parent"}
    return {**details, "text": text, "reason": None}


def ranked_frontier(nodes: list[dict]) -> list[dict]:
    """Rank exploration priority separately from verified proof quality."""
    eligible = [node for node in nodes if node.get("status") in ("full", "primary")
                and node.get("decision") != "park"]
    best = max((node.get("local_proxy") or 0 for node in eligible if node["status"] == "full"), default=0)
    result = []
    for node in eligible:
        quality = 40 * max(0, min(1, (node.get("local_proxy") or 0) / best)) if best else 0
        novelty = 20 * max(0, min(1, node.get("novelty", 0.5)))
        underexplored = 20 / (1 + len(node.get("children", [])))
        mergeability = min(20, 5 * node.get("merge_partners", 0))
        saturation = min(40, 6 * node.get("attempts_since_gain", 0))
        components = {"quality": round(quality, 2), "novelty": round(novelty, 2),
                      "underexplored": round(underexplored, 2), "mergeability": mergeability,
                      "saturation": -saturation}
        result.append({"candidate_id": node["id"], "status": node["status"],
                       "local_proxy": node.get("local_proxy"), "tokens": node.get("tokens"),
                       "priority": components, "priority_total": round(sum(components.values()), 2)})
    result.sort(key=lambda row: (row["status"] != "full", -row["priority_total"],
                                 row["tokens"] if row["tokens"] is not None else 10**9,
                                 row["candidate_id"]))
    return result
