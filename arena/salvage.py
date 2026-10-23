"""Pure salvage planning and first-class sketch-hole operations."""

from __future__ import annotations

import difflib
import re
import textwrap
from collections.abc import Callable

from arena import engine
from arena.steps import StepNode as Node
from arena.steps import parse

MAX_COMPILES = 6
OPENER = re.compile(r"\b(do|by|with|=>)\s*$")
SORRY_RE = re.compile(r"\bsorry\b")
HEAD_RE = re.compile(r"^(have|obtain|let)\b")
TYPE_RE = re.compile(r"^\s*(?:have|obtain|let)\b[^:]*:(.*):=\s*sorry\s*$")


def hdr_end(node: Node) -> int:
    return node.kids[0].start if node.kids else node.end


def deepest(nodes: list[Node], line: int) -> Node | None:
    for node in nodes:
        if node.start <= line < node.end:
            return deepest(node.kids, line) or node
    return None


def render(lines: list[str], nodes: list[Node], lo: int, hi: int, actions: dict, errors: set[int]) -> list[str]:
    out, position = [], lo
    for node in nodes:
        out += lines[position : node.start]
        out += render_node(lines, node, actions, errors)
        position = node.end
    return out + lines[position:hi]


def render_node(lines: list[str], node: Node, actions: dict, errors: set[int]) -> list[str]:
    key = (node.start, node.end)
    if key in actions["header"]:
        return [actions["header"][key]]
    if key in actions["sorry"]:
        first = lines[node.start]
        opens = bool(OPENER.search(first.rstrip())) or first.strip() == "·"
        keep = bool(node.kids) and opens and not any(node.start <= line < hdr_end(node) for line in errors)
        if keep:
            return [first, " " * (len(lines[node.kids[0].start]) - len(lines[node.kids[0].start].lstrip())) + "sorry"]
        return [" " * (len(first) - len(first.lstrip())) + "sorry"]
    return [lines[node.start], *render(lines, node.kids, node.start + 1, node.end, actions, errors)]


def whole_sorry(proof: str) -> bool:
    lines = proof.split("\n")
    roots = parse(lines)
    return roots is not None and all(not root.kids and lines[root.start].strip() == "sorry" for root in roots)


def plan(lines: list[str], roots: list[Node], errors: set[int]) -> tuple[list[str] | None, set[str], str | None]:
    mapped = [(line, node) for line in sorted(errors) if (node := deepest(roots, line)) is not None]
    if not mapped:
        return None, set(), "broken-outside-steps"
    actions = {"sorry": set(), "header": {}}
    used: set[str] = set()
    for line, node in mapped:
        raw = lines[node.start]
        joined = " ".join(value.strip() for value in lines[node.start : hdr_end(node)])
        is_header = bool(HEAD_RE.match(raw.strip())) and ":=" in joined
        if (node.kids and line >= hdr_end(node)) or (not node.kids and not is_header):
            actions["sorry"].add((node.start, node.end))
            used.add("S2")
        elif is_header:
            used.add("S3")
            target = node.parent or node
            before_assign = joined[: joined.index(":=")]
            if joined.endswith(":= sorry"):
                actions["sorry"].add((target.start, target.end))
            elif ":" in before_assign:
                indent = len(raw) - len(raw.lstrip())
                actions["header"][(node.start, node.end)] = " " * indent + before_assign.rstrip() + " := sorry"
            else:
                actions["sorry"].add((target.start, target.end))
    if used:
        changed = render(lines, roots, 0, len(lines), actions, errors)
        if changed != lines:
            return changed, used, None
    actions4 = {"sorry": set(), "header": {}}
    for _, node in mapped:
        target = node.parent or node
        actions4["sorry"].add((target.start, target.end))
    changed = render(lines, roots, 0, len(lines), actions4, errors)
    if changed == lines:
        return None, used, "broken-no-progress"
    return changed, used | {"S4"}, None


def _visible_sorries(proof: str) -> list[tuple[int, int]]:
    """Return character offsets for sorry tokens outside line and nested block comments."""
    found: list[tuple[int, int]] = []
    i = 0
    block_depth = 0
    line_comment = False
    string_literal = False
    escaped = False
    while i < len(proof):
        if line_comment:
            if proof[i] == "\n":
                line_comment = False
            i += 1
        elif string_literal:
            if escaped:
                escaped = False
            elif proof[i] == "\\":
                escaped = True
            elif proof[i] == '"':
                string_literal = False
            i += 1
        elif block_depth:
            if proof.startswith("/-", i):
                block_depth += 1
                i += 2
            elif proof.startswith("-/", i):
                block_depth -= 1
                i += 2
            else:
                i += 1
        elif proof.startswith("--", i):
            line_comment = True
            i += 2
        elif proof.startswith("/-", i):
            block_depth = 1
            i += 2
        elif proof[i] == '"':
            string_literal = True
            i += 1
        else:
            match = SORRY_RE.match(proof, i)
            if match:
                found.append((i, match.end()))
                i = match.end()
            else:
                i += 1
    return found


def holes(proof: str, goals: list[dict]) -> list[dict]:
    """Project visible sorry tokens and attach tactic or stated goals by source line."""
    goals_by_line: dict[int, list[dict]] = {}
    for goal in goals:
        proof_line = goal.get("proof_line")
        if isinstance(proof_line, int):
            goals_by_line.setdefault(proof_line, []).append(goal)
    result = []
    for index, (start, _) in enumerate(_visible_sorries(proof), 1):
        line = proof.count("\n", 0, start) + 1
        last_newline = proof.rfind("\n", 0, start)
        column = start - last_newline
        row = proof.splitlines()[line - 1]
        candidates = goals_by_line.get(line, [])
        if candidates:
            goal_text = candidates.pop(0).get("goals")
            goal_text = "\n".join(goal_text) if isinstance(goal_text, list) else goal_text
            goal_source = "lean"
        else:
            match = TYPE_RE.match(row)
            goal_text = match.group(1).strip() if match else None
            goal_source = "stated" if goal_text is not None else None
        result.append({"index": index, "line": line, "column": column, "goal": goal_text, "goal_source": goal_source})
    return result


def fill_text(proof: str, hole: dict, text: str) -> str:
    """Replace the indexed token while preserving all surrounding source bytes."""
    line = hole["line"]
    column = hole["column"]
    lines = proof.splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise ValueError(f"hole position {line}:{column} does not point at sorry")
    start = sum(map(len, lines[: line - 1])) + column - 1
    end = start + len("sorry")
    match = SORRY_RE.match(proof, start)
    if proof[start:end] != "sorry" or match is None or match.end() != end:
        raise ValueError(f"hole position {line}:{column} does not point at sorry")
    row = lines[line - 1]
    indent = len(row) - len(row.lstrip())
    midline = bool(row[: column - 1].strip())
    replacement = textwrap.dedent(text).strip("\n")
    replacement_lines = replacement.split("\n") if replacement else [""]
    pad = " " * (indent + (2 if midline else 0))
    replacement = replacement_lines[0] + "".join("\n" + pad + part for part in replacement_lines[1:])
    return proof[:start] + replacement + proof[end:]


def fill_cost(text: str) -> int:
    return engine._proof_length("theorem x : True := " + text)


def _compiled(name: str, text: str, compile: Callable[[str], dict]) -> dict:
    compiled = compile(text)
    if not isinstance(compiled, dict):
        raise ValueError("salvage compile must return a result dictionary")
    if {"clean", "error_lines", "unlocated", "result"} <= compiled.keys():
        return {**compiled, "finished_lines": _finished_lines(compiled["result"] or {})}
    result = compiled
    compat = result.get("compat") or {}
    first = next(iter(compat.values()), {})
    diagnostics = first.get("diagnostics") or []
    clean = bool(first.get("passed")) and not any(item.get("severity") == "error" for item in diagnostics)
    error_lines = [
        item["proof_line"] for item in diagnostics if item.get("severity") == "error" and item.get("proof_line")
    ]
    return {
        "clean": clean,
        "error_lines": error_lines,
        "finished_lines": _finished_lines(result),
        "unlocated": not clean and not error_lines,
        "result": result,
    }


def _finished_lines(result: dict) -> list[int]:
    """Error lines when every error is "No goals" (the proof was already done there); otherwise none."""
    first = next(iter((result.get("compat") or {}).values()), {})
    errors = [item for item in first.get("diagnostics") or [] if item.get("severity") == "error"]
    if not errors or not all(str(item.get("message", "")).startswith("No goals") for item in errors):
        return []
    return [item["proof_line"] for item in errors if item.get("proof_line")]


def drop_finished(lines: list[str], roots: list[Node], finished: set[int]) -> list[str] | None:
    """S1: the proof is already done before these one-line tactics ("No goals"); remove them. Only leaf steps
    whose single line is the error line go; anything else is left to the other strategies."""
    drop = set()
    for line in finished:
        node = deepest(roots, line)
        if node is None or node.kids or node.start != line or node.end - node.start != 1:
            return None
        drop.add(line)
    return [text for index, text in enumerate(lines) if index not in drop] if drop else None


def _kept(original: str, final: str) -> float:
    before, after = original.splitlines(), final.splitlines()
    h1, h2 = (
        next((i for i, line in enumerate(before) if line.rstrip().endswith(":= by")), -1),
        next((i for i, line in enumerate(after) if line.rstrip().endswith(":= by")), -1),
    )
    left, right = (
        [line for line in before[h1 + 1 :] if line.strip()],
        [line for line in after[h2 + 1 :] if line.strip()],
    )
    matched = sum(
        block.size for block in difflib.SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks()
    )
    return matched / len(left) if left else 0.0


def salvage(
    name: str,
    proof: str,
    compile: Callable[[str], dict],
    *,
    should_yield: Callable[[], str | None] | None = None,
    resume: dict | None = None,
) -> dict:
    """Attempt salvage, yielding only between compiler requests when asked."""
    roots = parse(proof.split("\n"))
    if roots is None:
        return {"status": "unparseable", "compiles": 0, "rounds": [], "text": None, "result": None, "kept": None}
    current = resume["current"] if resume else proof
    rounds = list(resume["rounds"]) if resume else []
    last_result = resume.get("last_result") if resume else None
    s1_used = bool(resume.get("s1_used")) if resume else False
    completed = int(resume.get("compiles", 0)) if resume else 0
    for index in range(completed, MAX_COMPILES):
        reason = should_yield() if should_yield else None
        if reason:
            return {
                "status": "deferred",
                "reason": reason,
                "compiles": completed,
                "rounds": rounds,
                "text": None,
                "result": last_result,
                "kept": None,
                "continuation": {
                    "current": current,
                    "rounds": rounds,
                    "s1_used": s1_used,
                    "compiles": completed,
                },
            }
        try:
            compiled = _compiled(name, current, compile)
        except (ValueError, FileNotFoundError):
            return {
                "status": "unavailable",
                "compiles": completed + 1,
                "rounds": rounds,
                "text": None,
                "result": last_result,
                "kept": None,
            }
        last_result = compiled["result"]
        completed += 1
        if compiled["clean"]:
            status = "salvaged" if index else "clean-as-is"
            return {
                "status": status,
                "compiles": completed,
                "rounds": rounds,
                "text": current if status == "salvaged" else None,
                "result": last_result,
                "kept": _kept(proof, current) if status == "salvaged" else None,
            }
        if compiled["unlocated"]:
            status = "broken-unlocated"
            break
        if completed == MAX_COMPILES:
            status = "broken-pass-limit"
            break
        lines = current.split("\n")
        tree = parse(lines)
        if tree is None:
            status = "broken-outside-steps"
            break
        # S1 removes steps that come after a finished proof. Once S2-S4 have inserted sorry, later "No goals" errors
        # are their doing, so S1 may not run then; and it runs at most once per salvage.
        s1_allowed = not s1_used and all(round_["strategies"] == ["S1"] for round_ in rounds)
        dropped = (
            drop_finished(lines, tree, {line - 1 for line in compiled.get("finished_lines") or []})
            if s1_allowed
            else None
        )
        if dropped is not None:
            s1_used = True
            rounds.append({"round": index + 1, "errors": len(compiled["error_lines"]), "strategies": ["S1"]})
            current = "\n".join(dropped)
            continue
        next_lines, strategies, reason = plan(lines, tree, {line - 1 for line in compiled["error_lines"]})
        if reason:
            status = reason
            break
        next_text = "\n".join(next_lines or [])
        if whole_sorry(next_text):
            status = "broken-whole-proof-sorried"
            break
        rounds.append({"round": index + 1, "errors": len(compiled["error_lines"]), "strategies": sorted(strategies)})
        current = next_text
    return {
        "status": status,
        "compiles": completed,
        "rounds": rounds,
        "text": None,
        "result": last_result,
        "kept": None,
    }
