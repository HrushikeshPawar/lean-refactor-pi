"""Internal routes from proof-shape signatures.

Each signature mixes top-level tactic heads with hashes of normalized proof steps. Assignment uses maximum
similarity to any existing route member and a parent-sensitive margin, keeping nearby edits together while
opening distinct routes for distant shapes. Routes are computed synchronously from text and frozen in the ledger.
"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

ROUTE_DEPTH = 3  # distinct goal states that make a route explored
STALE_STREAK = 5  # consecutive attempts leaving an already seen goal state
MAX_SKELETON = 24
JOIN = 0.60
OPEN_BELOW = 0.35
MARGIN = 0.10
SMALL_EDIT_LINES = 3
MAX_ROUTES = 12
_NAME = re.compile(r"\b(h[A-Za-z0-9_'₀-₉]*|this|H[A-Za-z0-9_'₀-₉]*|ih[A-Za-z0-9_']*)\b")

_COMMENT_BLOCK = re.compile(r"/-.*?-/", re.S)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_IDENT = re.compile(r"[A-Za-z_Ͱ-Ͽ][A-Za-z0-9_'.!?₀-₉]*")
_RECURSION = re.compile(
    r"(?<![\w.])(induction'?|induct|fun_induction|fun_cases|termination_by|decreasing_by)(?![\w'])"
    r"|\.(rec|recOn|casesOn|brecOn)(?![\w'])"
)


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


def proof_body(proof: str) -> str:
    """The text after the declaration's own `:=` (the first one outside brackets)."""
    text = _strip_comments(proof)
    depth = 0
    for index, char in enumerate(text):
        if char in "([{⟨":
            depth += 1
        elif char in ")]}⟩":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0 and text.startswith(":=", index):
            return text[index + 2 :]
    return text


def _heads(body: str) -> list[str]:
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return []
    first, rest = lines[0], lines[1:]
    # `:= by tac` keeps its first tactic on the statement line; it has no indentation of its own.
    top = [re.sub(r"^\s*by\b", "", first).strip()] if re.sub(r"^\s*by\b", "", first).strip() else []
    if rest:
        indent = min(len(line) - len(line.lstrip()) for line in rest)
        top += [line.strip() for line in rest if len(line) - len(line.lstrip()) == indent]
    heads: list[str] = []
    for line in top:
        if line.startswith("|"):  # a case arm of the preceding induction or match, not a tactic
            continue
        line = re.sub(r"^[·.<;>()\s*]+", "", line)
        match = re.match(r"[A-Za-z_][A-Za-z0-9_'?!]*", line)
        head = match.group(0) if match else line[:1]
        if head and (not heads or heads[-1] != head):
            heads.append(head)
    return heads[:MAX_SKELETON]


def signature(proof: str) -> dict:
    """Return tactic-head skeleton and sorted hashes of normalized body lines."""
    normalized = set()
    for line in proof_body(proof).splitlines():
        step = " ".join(line.split())
        if not step or step == "by":
            continue
        step = _NAME.sub("_h", step)
        normalized.add(hashlib.sha1(step.encode()).hexdigest()[:10])
    return {"skeleton": _heads(proof_body(proof)), "steps": sorted(normalized)}


def similarity(a: dict, b: dict) -> float:
    """Mix top-level tactic shape and normalized step overlap equally."""
    left, right = a["skeleton"], b["skeleton"]
    shape = SequenceMatcher(None, left, right, autojunk=False).ratio() if left or right else 1.0
    left_steps, right_steps = set(a["steps"]), set(b["steps"])
    union = left_steps | right_steps
    overlap = len(left_steps & right_steps) / len(union) if union else 1.0
    return 0.5 * shape + 0.5 * overlap


def line_diff(a: str, b: str) -> int:
    """Count changed proof-body lines, returning 99 when lengths differ by over three."""
    left, right = proof_body(a).splitlines(), proof_body(b).splitlines()
    if abs(len(left) - len(right)) > SMALL_EDIT_LINES:
        return 99
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
        if tag != "equal"
    )


def assign(
    members: dict[str, list[dict]],
    sig: dict,
    parent_route: str | None,
    parent_line_diff: int | None,
) -> dict:
    """Assign a signature to the best existing route, respecting edit hysteresis and the route cap."""
    if not members:
        return {"route": "r1", "new": True, "similarity": 1.0, "runner_up": None}

    scores = {
        route: max(similarity(sig, member) for member in route_members) for route, route_members in members.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_route, top = ranked[0]
    runner_up = {"route": ranked[1][0], "similarity": ranked[1][1]} if len(ranked) > 1 else None

    if parent_route is not None and parent_line_diff is not None and parent_line_diff <= SMALL_EDIT_LINES:
        return {
            "route": parent_route,
            "new": False,
            "similarity": scores.get(parent_route, top),
            "runner_up": runner_up,
        }

    if top >= JOIN:
        route = best_route
    elif top < OPEN_BELOW:
        route = best_route if len(members) >= MAX_ROUTES else f"r{len(members) + 1}"
    elif (
        top - (ranked[1][1] if len(ranked) > 1 else 0.0) >= MARGIN or best_route == parent_route or parent_route is None
    ):
        route = best_route
    else:
        route = parent_route
    return {"route": route, "new": route not in members, "similarity": scores.get(route, top), "runner_up": runner_up}


def attempt_results(history: list[dict]) -> dict[str, tuple[str, dict | None]]:
    """Per attempt id: ("probe" | "candidate", the compile result of its first probe or evaluation)."""
    found: dict[str, tuple[str, dict | None]] = {}
    for event in history:
        if event.get("kind") == "probe":
            found.setdefault(event["proof_id"], ("probe", event.get("result")))
        elif event.get("kind") == "evaluation":
            found.setdefault(event["candidate_id"], ("candidate", event.get("result")))
    return found


def route_table(history: list[dict]) -> list[dict]:
    """Per route: label, number of model attempts (compiled candidates and probe drafts), best candidate and proxy,
    and depth: distinct goal-state signatures (arena/goalstate.py), the fewest open holes, the stale streak (latest
    consecutive attempts whose signature the route had already seen), and whether it is explored. Pure function of the ledger."""
    from arena import goalstate

    labels: dict[str, str] = {}
    origin: dict[str, str] = {}
    for event in history:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
            origin[event["candidate_id"]] = event.get("origin", "model")
    score: dict[str, tuple[bool, float]] = {}
    for event in history:
        if event.get("kind") != "evaluation":
            continue
        metrics = (event.get("result") or {}).get("metrics") or {}
        verified = event.get("mode") == "full" and metrics.get("proxy") is not None
        value = metrics.get("proxy") if verified else metrics.get("estimated_proxy")
        if value is not None and (
            event["candidate_id"] not in score or (verified, value) > score[event["candidate_id"]]
        ):
            score[event["candidate_id"]] = (verified, value)
    results = attempt_results(history)
    table: dict[str, dict] = {}
    seen: dict[str, set[str]] = {}
    for event in history:
        if event.get("kind") != "route":
            continue
        identifier = event["proof_id"]
        kind = origin.get(identifier)
        route = event["route"]
        # Credit is for compiled proofs only: the attempt must be a candidate whose compile passed with no error and no
        # sorry. A draft or a failed compile never earns credit, even if an older ledger marks it credited.
        earned = (
            identifier in results and results[identifier][0] == "candidate" and goalstate.closed(results[identifier][1])
        )
        if route not in table:
            table[route] = {
                "route": route,
                "label": event.get("label") or route,
                "short_label": event.get("short_label") or event.get("label") or route,
                "original": False,
                "attempts": 0,
                "best_candidate": None,
                "best_proxy": None,
                "verified": False,
                "depth": 0,
                "new_states": 0,
                "min_holes": None,
                "stale_streak": 0,
                "compiled": False,
                "explored": False,
                "stale": False,
                "credited": bool(event.get("credited")) and earned and kind != "reference",
                "skeleton": False,
            }
            seen[route] = set()
        row = table[route]
        if kind == "reference":
            # In legacy ledgers, the reference may follow attempts that already opened its route; then mark that route
            # original and uncredited.
            row["original"] = row["compiled"] = row["explored"] = True
            row["credited"] = False
            seen[route].add(goalstate.CLOSED)
            continue
        if kind == "auto_merge":
            continue
        row["attempts"] += 1
        if identifier in score and (
            row["best_proxy"] is None
            or (score[identifier][0], score[identifier][1]) > (row["verified"], row["best_proxy"])
        ):
            row["verified"], row["best_proxy"] = score[identifier]
            row["best_candidate"] = labels.get(identifier)
        if identifier not in results:
            continue
        sig = goalstate.signature(results[identifier][1])
        if sig == goalstate.CLOSED:
            row["compiled"], open_holes = True, 0
        else:
            open_holes = (event.get("holes") or 0) + (event.get("synthetic") or 0) if "holes" in event else None
        if open_holes is not None and (row["min_holes"] is None or open_holes < row["min_holes"]):
            row["min_holes"] = open_holes
        if sig in seen[route]:
            row["stale_streak"] += 1
        else:
            seen[route].add(sig)
            row["depth"] += 1
            row["new_states"] += 1
            row["stale_streak"] = 0
        row["explored"] = row["compiled"] or row["depth"] >= ROUTE_DEPTH
    for row in table.values():
        row["stale"] = row["stale_streak"] >= STALE_STREAK
    return list(table.values())


def progress(table: list[dict]) -> dict:
    """Run-level depth metrics of a route table: credited and explored routes, and the share of model attempts
    that produced a goal state new to their route."""
    rows = [row for row in table if row["attempts"]]
    attempts = sum(row["attempts"] for row in rows)
    new = sum(row["new_states"] for row in rows)
    return {
        "credited_routes": sum(row["credited"] for row in rows),
        "explored_routes": sum(row["explored"] for row in rows),
        "new_state_attempts": new,
        "new_state_share": round(new / attempts, 3) if attempts else None,
    }


def routes_detail_text(table: list[dict]) -> str:
    """`routes_text` with each route's depth: goal states, fewest holes, stale streak, explored/opened, credit."""
    # not-model-facing: this detailed format is only included in the operator's run summary.
    parts = []
    for row in table:
        if not row["attempts"] and not row["original"]:
            continue
        best = (
            f"best proxy {row['best_proxy']} ({row['best_candidate']})"
            if row["best_proxy"] is not None
            else "no scored proof"
        )
        # not-model-facing: detailed route table is only shown in the operator summary.
        tag = " [the original proof's route]" if row["original"] else ""
        states = row.get("depth", 0)
        extra = [f"{states} goal state{'s' if states != 1 else ''}"]
        if row.get("min_holes") is not None:
            extra.append(f"min holes {row['min_holes']}")
        if row.get("stale_streak"):
            extra.append(f"stale streak {row['stale_streak']}")
        extra.append("explored" if row.get("explored") else "opened")
        if row.get("credited"):
            # not-model-facing: detailed route table is only shown in the operator summary.
            extra.append("credited" + (" (opened by a skeleton)" if row.get("skeleton") else ""))
        parts.append(
            f'{row["route"]} "{row["label"]}"{tag}: {row["attempts"]} attempt{"s" if row["attempts"] != 1 else ""}, '
            f"{', '.join(extra)}, {best}"
        )
    return "; ".join(parts) if parts else "none"
