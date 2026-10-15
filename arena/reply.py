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


def _origin(item: dict) -> str:
    parents = ", ".join(item.get("from") or [])
    edge = str(item.get("edge") or "root")
    if not parents or edge == "root":
        return text.render("replies/tools.map_origin_root")
    return text.render(
        "replies/tools.map_origin_from", edge=edge.removesuffix("_from").replace("_", " "), parents=parents
    )


def _map_lines(data: dict) -> list[str]:
    lines: list[str] = []
    best = data.get("best")
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
        lines.append(text.render("replies/tools.map_routes"))
    lines.extend(
        [
            text.render(
                "replies/tools.map_archive",
                letter=shown(item.get("letter")),
                node=shown(item.get("node")),
                status=shown(item.get("status")),
                score=shown(item.get("score")),
                visits=item.get("visits") or 0,
            )
            for item in archive
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_recent",
                node=shown(item.get("node")),
                origin=_origin(item),
                status=shown(item.get("status")),
                score=shown(item.get("score")),
            )
            for item in data.get("recent", [])
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_effort",
                step=shown(item.get("step")),
                at_stake=shown(item.get("at_stake")),
                variants=item.get("variants") or 0,
                best_delta=shown(item.get("best_dtok")),
                last_gain=shown(item.get("last_gain")),
            )
            for item in data.get("effort", [])
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_hole",
                hole=shown(item.get("hole")),
                line=shown(item.get("line")),
                goal=shown(item.get("goal")),
            )
            for item in data.get("open", [])
        ]
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
            result["map"] = lines
            state["map_hash"] = digest
    # Node ids the model has been shown; an update never names a node outside them.
    seen = set(state.get("seen_nodes", [])) | _node_ids(result)
    facts = [_update_text(item, seen) for item in fresh if isinstance(item.get("text"), str)] + result.get("facts", [])
    if fresh:
        state["delivered_seq"] = max(int(item.get("seq", -1)) for item in fresh)
    result["facts"] = facts
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
