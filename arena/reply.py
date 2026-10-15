"""Shared JSON replies, pending-update delivery and diagnostic deduplication."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from arena import campaign, text

DELIVERY_FILE = "tool-delivery.json"


def reply(
    *,
    ok: bool = True,
    error: dict | None = None,
    facts: list[str] | None = None,
    items: list[dict] | None = None,
    handles: list[str] | None = None,
    map_lines: list[str] | None = None,
    stop: bool = False,
) -> dict:
    return {
        "ok": ok,
        "error": error,
        "facts": list(facts or []),
        "items": list(items or []),
        "handles": list(dict.fromkeys(handles or [])),
        "map": map_lines,
        "stop": stop,
    }


def request_error(code: str, bad_input: object, valid: list[str], forms: list[str]) -> dict:
    return {"code": code, "input": str(bad_input), "valid": valid[:8], "forms": forms}


def error_reply(code: str, bad_input: object, valid: list[str], forms: list[str]) -> dict:
    return reply(ok=False, error=request_error(code, bad_input, valid, forms))


def error_item(
    ref: str, code: str, bad_input: object, valid: list[str], forms: list[str], lines: list[str] | None = None
) -> dict:
    return {
        "ref": ref,
        "ok": False,
        "lines": list(lines or []),
        "error": request_error(code, bad_input, valid, forms),
    }


def _path(run_id: str) -> Path:
    return campaign.run_dir(run_id) / DELIVERY_FILE


def _load(run_id: str) -> dict:
    try:
        value = json.loads(_path(run_id).read_text())
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _save(run_id: str, value: dict) -> None:
    path = _path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def reset_delivered(run_id: str) -> None:
    state = _load(run_id)
    state.pop("map_hash", None)
    state["goals"] = {}
    state["diagnostics"] = {}
    _save(run_id, state)


def first_time(run_id: str, key: str) -> bool:
    """True the first time `key` is seen for this run; later calls return False."""
    state = _load(run_id)
    seen = state.setdefault("offered", [])
    if key in seen:
        return False
    seen.append(key)
    _save(run_id, state)
    return True


def goal_summary(goal: object, limit: int | None = 120) -> str | None:
    """A goal as whole lines joined by " / ", stopping before a line that would pass `limit` characters."""
    if not isinstance(goal, str) or not goal.strip():
        return None
    lines = [line.rstrip() for line in goal.strip().split("\n")]
    kept: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + (3 if kept else 0)
        if kept and limit is not None and size + extra > limit:
            break
        kept.append(line)
        size += extra
    summary = " / ".join(kept)
    return summary if len(kept) == len(lines) else summary + " / ..."


def shown(value: object) -> object:
    """A value as the model sees it: a missing one is "-", never Python's None."""
    return "-" if value is None or value == "" else value


def outcome(status: object, holes: list | None = None) -> object:
    """A node's internal status as the model reads it: its compile outcome phrase."""
    if status == "closed":
        return text.render("replies/tools.outcome_closed")
    if status == "sketch":
        count = len(holes or [])
        if count == 1:
            return text.render("replies/tools.outcome_sketch_one")
        if count:
            return text.render("replies/tools.outcome_sketch", count=count)
        return text.render("replies/tools.outcome_sketch_open")
    if status == "broken":
        return text.render("replies/tools.outcome_broken")
    if status == "timeout":
        return text.render("replies/tools.outcome_timeout")
    return shown(status)


def _origin(item: dict) -> str:
    parents = ", ".join(item.get("from") or [])
    edge = str(item.get("edge") or "root")
    if not parents or edge == "root":
        return text.render("replies/tools.map_origin_root")
    return text.render(
        "replies/tools.map_origin_from", edge=edge.removesuffix("_from").replace("_", " "), parents=parents
    )


# Steps shown in full, by points at stake; the rest are one summary line.
EFFORT_SHOWN = 4
SHAPES_SHOWN = 5
GOAL_CHARS = 200


def _goal_line(goal: object) -> object:
    """A hole's case tag and its target (`⊢ ...`, continued lines joined), without the hypothesis context."""
    if not isinstance(goal, str) or not goal.strip():
        return shown(goal)
    lines = [line.strip() for line in goal.splitlines() if line.strip()]
    start = next((index for index in range(len(lines) - 1, -1, -1) if lines[index].startswith("⊢")), None)
    target = " ".join(lines[start:]) if start is not None else None
    tag = lines[0] if lines[0].startswith("case ") else None
    found = " ".join(part for part in (tag, target) if part) or lines[0]
    return found if len(found) <= GOAL_CHARS else found[: GOAL_CHARS - 1] + "…"


def _step_hb(value: object) -> object:
    """A step's heartbeats wait for the best node's background profile."""
    return text.render("replies/tools.hb_pending") if value is None else value


def _node_hb(item: dict) -> object:
    """A broken node's partial elaboration is not a heartbeat cost."""
    return "-" if item.get("status") == "broken" else shown(item.get("heartbeats"))


def _shortest(item: dict) -> object:
    """The shortest compiling replacement's token change and the node it is in."""
    delta, node = item.get("best_dtok"), item.get("best_dtok_node")
    return f"{_signed(delta)} in {node}" if node and delta is not None else _signed(delta)


def _signed(value: object) -> object:
    return f"{value:+d}" if isinstance(value, int) else shown(value)


def _effort_lines(data: dict) -> list[str]:
    """The best node's steps ranked by points at stake, with units the model can act on."""
    rows = sorted(data.get("effort", []), key=lambda item: -(item.get("at_stake") or 0))
    if not rows:
        return []
    best = data.get("best") or {}
    lines = [
        text.render("replies/tools.map_steps_head", node=shown(best.get("node"))),
        text.render("replies/tools.map_steps_legend"),
        text.render("replies/tools.map_steps_cols"),
    ]
    for item in rows[:EFFORT_SHOWN]:
        gain = item.get("last_gain")
        lines.append(
            text.render(
                "replies/tools.map_step",
                step=shown(item.get("step")),
                tokens=shown(item.get("tokens")),
                heartbeats=_step_hb(item.get("heartbeats")),
                at_stake=shown(item.get("at_stake")),
                variants=item.get("variants") or 0,
                best_delta=_shortest(item),
                last_gain=shown(gain),
            )
        )
    rest = rows[EFFORT_SHOWN:]
    if rest:
        lines.append(
            text.render("replies/tools.map_steps_more", count=len(rest), at_stake=shown(rest[0].get("at_stake")))
        )
    return lines


LINE_TEXT_CHARS = 90


def _cell(value: object) -> str:
    """Proof text inside a table cell: one line, no column separators, cut at LINE_TEXT_CHARS."""
    flat = str(value).replace("|", "\\|").replace("`", "'")
    return flat if len(flat) <= LINE_TEXT_CHARS else flat[: LINE_TEXT_CHARS - 1] + "…"


def _line_cost_lines(data: dict) -> list[str]:
    """The best node's costliest tactic lines and its longest lines that run nothing of their own."""
    costs = data.get("line_costs") or {}
    node = shown((data.get("best") or {}).get("node"))
    lines: list[str] = []
    if costs.get("tactic"):
        lines.append(text.render("replies/tools.map_tactic_lines_head", node=node))
        lines.extend(
            text.render(
                "replies/tools.map_tactic_line",
                line=row["line"],
                text=_cell(row["text"]),
                heartbeats=shown(row.get("heartbeats")),
                tokens=shown(row.get("tokens")),
            )
            for row in costs["tactic"]
        )
    if costs.get("quiet"):
        lines.append(text.render("replies/tools.map_quiet_lines_head", node=node))
        lines.append(text.render("replies/tools.map_quiet_lines_note"))
        lines.append(text.render("replies/tools.map_quiet_lines_cols"))
        lines.extend(
            text.render(
                "replies/tools.map_quiet_line",
                line=row["line"],
                text=_cell(row["text"]),
                tokens=shown(row.get("tokens")),
            )
            for row in costs["quiet"]
        )
    if lines:
        lines.append(text.render("replies/tools.map_lines_note"))
    return lines


def _map_lines(data: dict) -> list[str]:
    lines: list[str] = []
    best = data.get("best")
    if best or data.get("reference"):
        lines.append(text.render("replies/tools.map_best_head"))
    if best:
        lines.append(
            text.render(
                "replies/tools.map_best",
                node=shown(best.get("node")),
                score=shown(best.get("score")),
                tokens=shown(best.get("tokens")),
                heartbeats=shown(best.get("heartbeats")),
            )
        )
    original = data.get("reference")
    if original:
        lines.append(
            text.render(
                "replies/tools.map_reference",
                node=shown(original.get("node")),
                tokens=shown(original.get("tokens")),
                heartbeats=shown(original.get("heartbeats")),
            )
        )
    archive = data.get("archive", [])
    if archive:
        lines.append(text.render("replies/tools.map_shapes"))
    lines.extend(
        [
            text.render(
                "replies/tools.map_shape",
                node=shown(item.get("node")),
                status=outcome(item.get("status")),
                tokens=shown(item.get("tokens")),
                heartbeats=_node_hb(item),
                score=shown(item.get("score")),
                visits=item.get("visits") or 0,
            )
            for item in sorted(archive, key=lambda item: (item.get("score") is None, -(item.get("score") or 0)))[
                :SHAPES_SHOWN
            ]
        ]
    )
    if data.get("recent"):
        lines.append(text.render("replies/tools.map_recent_head"))
    lines.extend(
        [
            text.render(
                "replies/tools.map_recent",
                node=shown(item.get("node")),
                origin=_origin(item),
                status=outcome(item.get("status")),
                tokens=shown(item.get("tokens")),
                heartbeats=_node_hb(item),
                score=shown(item.get("score")),
            )
            for item in data.get("recent", [])
        ]
    )
    lines.extend(_effort_lines(data))
    lines.extend(_line_cost_lines(data))
    holes = data.get("open", [])
    if holes:
        lines.append(text.render("replies/tools.map_holes_head"))
    lines.extend(
        text.render(
            "replies/tools.map_hole_goal",
            hole=shown(item.get("hole")),
            line=shown(item.get("line")),
            goal=_goal_line(item.get("goal")),
        )
        for item in holes
    )
    return lines


def attach_context(
    run_id: str,
    result: dict,
    *,
    include_map: bool = False,
    force_map: bool = False,
    holes: list[dict] | None = None,
) -> dict:
    """Attach new state updates and a changed map, persisting delivery cursors.
    `holes`, when given, replaces the map's open holes (the caller's current lineage only)."""
    state = _load(run_id)
    try:
        updates = campaign.state(run_id).get("updates", [])
    except (OSError, ValueError, KeyError):
        updates = []
    delivered = int(state.get("delivered_seq", -1))
    fresh = [item for item in updates if int(item.get("seq", -1)) > delivered]
    if include_map or force_map:
        data = campaign.map_view(run_id)
        if holes is not None:
            data["open"] = holes
        lines = _map_lines(data)
        digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        if force_map or digest != state.get("map_hash"):
            result["map"] = [text.render("replies/tools.section_map"), *lines] if lines else lines
            state["map_hash"] = digest
    # Node ids the model has been shown; an update never names a node outside them.
    seen = set(state.get("seen_nodes", [])) | _node_ids(result)
    facts = [_update_text(item, seen) for item in fresh if isinstance(item.get("text"), str)] + result.get("facts", [])
    if fresh:
        state["delivered_seq"] = max(int(item.get("seq", -1)) for item in fresh)
    # Sections: updates from background checks, this call's result, then the search map.
    # A reply can pass through here more than once; each header is added once.
    updates_head, result_head = (
        text.render("replies/tools.section_updates"),
        text.render("replies/tools.section_result"),
    )
    facts = [line for line in facts if line != updates_head]
    first = next((item for item in result.get("items", []) if item.get("lines")), None)
    # An update about a node this call filed (its cross-version verdict) belongs with this call's result.
    own = set(result.get("handles", []))
    mine = [
        line for line in facts if own and re.match(r"(n[1-9][0-9]*)\b", line) and line.split()[0].rstrip(":") in own
    ]
    if first is not None and mine:
        facts = [line for line in facts if line not in mine]
    result["facts"] = [updates_head, *facts] if facts else facts
    if first is not None:
        body = first["lines"][1:] if first["lines"][0] == result_head else first["lines"]
        first["lines"] = [result_head, *[line for line in mine if line not in body], *body]
    state["seen_nodes"] = sorted(seen | _node_ids(result))
    _save(run_id, state)
    return result


def _node_ids(result: dict) -> set[str]:
    shown_text = [*result.get("facts", []), *(result.get("map") or []), *result.get("handles", [])]
    shown_text += [
        line for item in result.get("items", []) for line in item.get("lines") or [] if isinstance(line, str)
    ]
    return set(re.findall(r"\bn[1-9][0-9]*\b", "\n".join(shown_text)))


def _update_text(update: dict, seen: set[str]) -> str:
    sources = update.get("source") or []
    if isinstance(sources, str):
        sources = [sources]
    if sources and not set(sources) <= seen and isinstance(update.get("unseen_text"), str):
        return update["unseen_text"]
    return update["text"]


def _cross_node_ref(store: dict, digest: str, node: str) -> str | None:
    """The first id that showed this text, when it belongs to another node; a node never refers to itself."""
    ref = store.get(digest)
    return ref if ref and str(ref).split(".", 1)[0] != node else None


def deduplicate_diagnostics(run_id: str, node: str, errors: list[dict]) -> list[dict]:
    """Store full diagnostics and abbreviate repeated goals and long messages."""
    state = _load(run_id)
    goals = state.setdefault("goals", {})
    diagnostics = state.setdefault("diagnostics", {})
    directory = campaign.run_dir(run_id) / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    full_path = directory / f"{node}.jsonl"
    result = []
    with full_path.open("a") as output:
        for error in errors:
            row = dict(error)
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            goal = row.get("goal")
            if isinstance(goal, str) and goal.strip():
                normalized = re.sub(r"\s+", " ", goal).strip()
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                ref = _cross_node_ref(goals, digest, node)
                if ref:
                    row["goal"] = text.render("replies/tools.same_goal", ref=ref)
                else:
                    goals.setdefault(digest, row.get("id"))
            message = row.get("message")
            if isinstance(message, str) and len(message) >= 120:
                digest = hashlib.sha256(message.encode()).hexdigest()
                ref = _cross_node_ref(diagnostics, digest, node)
                if ref:
                    row["message"] = text.render(
                        "replies/tools.same_diagnostic", first=message.splitlines()[0], ref=ref
                    )
                else:
                    diagnostics.setdefault(digest, row.get("id"))
            result.append(row)
    _save(run_id, state)
    return result
