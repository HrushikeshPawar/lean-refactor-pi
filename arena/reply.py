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


def _map_lines(data: dict) -> list[str]:
    lines: list[str] = []
    best = data.get("best")
    if best:
        lines.append(
            text.render(
                "replies/tools.map_best",
                node=best.get("node", ""),
                score=best.get("score", "n/a"),
                tokens=best.get("tokens", "n/a"),
                heartbeats=best.get("heartbeats", "n/a"),
            )
        )
    lines.extend(
        [
            text.render(
                "replies/tools.map_archive",
                letter=item.get("letter", ""),
                node=item.get("node", ""),
                status=item.get("status", ""),
                score=item.get("score", "n/a"),
                visits=item.get("visits", 0),
            )
            for item in data.get("archive", [])
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_recent",
                node=item.get("node", ""),
                edge=item.get("edge") or "root",
                parent=",".join(item.get("from") or []) or "none",
                status=item.get("status", ""),
                score=item.get("score", "n/a"),
            )
            for item in data.get("recent", [])
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_effort",
                step=item.get("step", ""),
                at_stake=item.get("at_stake", "n/a"),
                variants=item.get("variants", 0),
                best_delta=item.get("best_dtok", "n/a"),
                last_gain=item.get("last_gain", "n/a"),
            )
            for item in data.get("effort", [])
        ]
    )
    lines.extend(
        [
            text.render(
                "replies/tools.map_hole",
                hole=item.get("hole", ""),
                line=item.get("line", ""),
                goal=item.get("goal") or "n/a",
            )
            for item in data.get("open", [])
        ]
    )
    return lines


def attach_context(run_id: str, result: dict, *, include_map: bool = False, force_map: bool = False) -> dict:
    """Attach new state updates and a changed map, persisting delivery cursors."""
    state = _load(run_id)
    try:
        updates = campaign.state(run_id).get("updates", [])
    except (OSError, ValueError, KeyError):
        updates = []
    delivered = int(state.get("delivered_seq", -1))
    fresh = [item for item in updates if int(item.get("seq", -1)) > delivered]
    facts = [item["text"] for item in fresh if isinstance(item.get("text"), str)] + result.get("facts", [])
    if fresh:
        state["delivered_seq"] = max(int(item.get("seq", -1)) for item in fresh)
    result["facts"] = facts
    if include_map or force_map:
        lines = _map_lines(campaign.map_view(run_id))
        digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        if force_map or digest != state.get("map_hash"):
            result["map"] = lines
            state["map_hash"] = digest
    _save(run_id, state)
    return result


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
                if digest in goals:
                    row["goal"] = text.render("replies/tools.same_goal", ref=goals[digest])
                else:
                    goals[digest] = row.get("id")
            message = row.get("message")
            if isinstance(message, str) and len(message) >= 120:
                digest = hashlib.sha256(message.encode()).hexdigest()
                if digest in diagnostics:
                    row["message"] = text.render(
                        "replies/tools.same_diagnostic", first=message.splitlines()[0], ref=diagnostics[digest]
                    )
                else:
                    diagnostics[digest] = row.get("id")
            result.append(row)
    _save(run_id, state)
    return result
