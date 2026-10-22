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
    return {"code": code, "input": str(bad_input), "valid": valid[:10], "forms": forms}


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
    from arena.run_control import committed_history, committed_operation_ids

    try:
        value = json.loads(_path(run_id).read_text())
    except (OSError, ValueError):
        value = {}
    state = value if isinstance(value, dict) else {}
    directory = campaign.run_dir(run_id)
    committed = committed_operation_ids(directory)
    for event in committed_history(campaign.events(directory), committed):
        if event.get("kind") != "delivered_reply" or not event.get("operation_id"):
            continue
        data = event.get("data") or {}
        if data.get("channel") == "worker_inbox" or "acked" in data:
            continue
        actor = event["actor_id"]
        bucket = _bucket(state, actor)
        if data["cursor"] < bucket.get("delivered_seq", -1):
            continue
        bucket["delivered_seq"] = data["cursor"]
        bucket["last_delivery"] = {
            "operation_id": event["operation_id"],
            "event_ids": data["event_ids"],
            "arguments": {"actor_id": actor, "seqs": data["seqs"], "event_ids": data["event_ids"]},
        }
    return state


def _save(run_id: str, value: dict, *, actor_update: tuple[str, dict] | None = None) -> None:
    from arena.run_control import control_lock

    path = _path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with control_lock(path.parent):
        current = _load(run_id)
        value = {**value, "actors": current.get("actors", {})}
        if actor_update is not None:
            actor, bucket = actor_update
            value["actors"][actor] = bucket
        for key in ("delivered_seq", "seen_nodes", "map_hash", "map_key"):
            if key in value["actors"].get("sol", {}):
                value[key] = value["actors"]["sol"][key]
            else:
                value.pop(key, None)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary, path)


def map_text(run_id: str) -> str:
    """The map exactly as `read view=map` renders it."""
    lines = _map_lines(campaign.map_view(run_id))
    return "\n".join([text.render("replies/tools.section_map"), *lines])


def current_actor() -> str:
    """Trusted invocation actor. Historical single-agent calls are Sol."""
    return os.environ.get("ARENA_ACTOR_ID") or "sol"


def _bucket(state: dict, actor: str) -> dict:
    actors = state.setdefault("actors", {})
    bucket = actors.setdefault(actor, {})
    if actor == "sol":
        for key in ("delivered_seq", "seen_nodes", "map_hash", "map_key"):
            if key not in bucket and key in state:
                bucket[key] = state[key]
    return bucket


def _write_actor(run_id: str, actor: str, bucket: dict, state: dict | None = None) -> dict:
    state = _load(run_id) if state is None else state
    state.setdefault("actors", {})[actor] = bucket
    if actor == "sol":
        for key in ("delivered_seq", "seen_nodes", "map_hash", "map_key"):
            if key in bucket:
                state[key] = bucket[key]
    _save(run_id, state, actor_update=(actor, bucket))
    return state


def actor_focuses(run_id: str) -> list[tuple[str, str]]:
    """Every actor-local filing anchor. Reading it does not move focus or start work."""
    found = []
    for actor, bucket in _load(run_id).get("actors", {}).items():
        if isinstance(bucket, dict) and isinstance(bucket.get("focus"), str):
            found.append((actor, bucket["focus"]))
    return found


def actor_focus_proof(run_id: str, actor: str | None = None) -> str | None:
    actor = actor or current_actor()
    focus = _bucket(_load(run_id), actor).get("focus")
    return focus if isinstance(focus, str) else None


def set_actor_focus(run_id: str, proof_id: str, actor: str | None = None) -> None:
    """Actor-local filing anchor. It does not move another actor's focus or the shared frontier."""
    actor = actor or current_actor()
    state = _load(run_id)
    bucket = _bucket(state, actor)
    bucket["focus"] = proof_id
    _write_actor(run_id, actor, bucket, state)


def mark_delivered(run_id: str, seq: int, shown: str) -> None:
    """Treat ledger rows up to `seq` as delivered and the nodes named in `shown` as seen."""
    actor = current_actor()
    state = _load(run_id)
    bucket = _bucket(state, actor)
    bucket["delivered_seq"] = seq
    bucket["seen_nodes"] = sorted(set(bucket.get("seen_nodes", [])) | set(re.findall(r"\bn[1-9][0-9]*\b", shown)))
    _write_actor(run_id, actor, bucket, state)


def reset_delivered(run_id: str) -> None:
    actor = current_actor()
    state = _load(run_id)
    bucket = _bucket(state, actor)
    bucket.pop("map_hash", None)
    bucket.pop("map_key", None)
    state["goals"] = {}
    state["diagnostics"] = {}
    if actor == "sol":
        state.pop("map_hash", None)
        state.pop("map_key", None)
    _write_actor(run_id, actor, bucket, state)


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


_HYPOTHESIS = re.compile(r"^[^\s:⊢][^\n]*? :(?: |$)")


def _normal(value: str) -> str:
    return " ".join(value.split())


def _goal_start(lines: list[str], target: int) -> int:
    """Index where the hypotheses of the goal whose `⊢` line is `target` begin."""
    start = target
    while start > 0:
        line = lines[start - 1]
        if line.startswith("case ") or (line and (line[0].isspace() or _HYPOTHESIS.match(line))):
            start -= 1
        else:
            break
    # Indented lines above the first hypothesis continue the message's own text, not the goal.
    while start < target and lines[start] and lines[start][0].isspace():
        start += 1
    return start


def _parse_goal(lines: list[str], start: int, target: int) -> dict:
    """One goal: its case tag, hypotheses (each with its continuation lines) and target lines."""
    tag = None
    hypotheses: list[list[str]] = []
    for line in lines[start:target]:
        if line.startswith("case ") and not hypotheses:
            tag = line
        elif line and line[0].isspace() and hypotheses:
            hypotheses[-1].append(line)
        else:
            hypotheses.append([line])
    end = target + 1
    while end < len(lines) and lines[end].strip() and lines[end][0].isspace():
        end += 1
    return {"tag": tag, "hypotheses": hypotheses, "target": lines[target:end], "end": end}


def compact_goal(goal: str, known: set[str] | frozenset[str] = frozenset(), hypothesis_chars: int | None = None) -> str:
    """A goal as its `⊢` target (whole) and only the hypotheses not in `known` (normalized hypothesis texts),
    with a count of the omitted ones. When the hypotheses pass `hypothesis_chars`, the oldest are dropped first."""
    lines = goal.strip("\n").split("\n")
    targets = [index for index, line in enumerate(lines) if line.startswith("⊢")]
    if not targets:
        return goal.strip()
    out: list[str] = []
    cursor = 0
    for target in targets:
        if target < cursor:
            continue
        start = max(cursor, _goal_start(lines, target))
        out.extend(lines[cursor:start])
        parsed = _parse_goal(lines, start, target)
        shown_hyps = [block for block in parsed["hypotheses"] if _normal(" ".join(block)) not in known]
        omitted = len(parsed["hypotheses"]) - len(shown_hyps)
        if hypothesis_chars is not None:
            while (
                len(shown_hyps) > 1 and sum(len(line) + 1 for block in shown_hyps for line in block) > hypothesis_chars
            ):
                shown_hyps.pop(0)
                omitted += 1
        if parsed["tag"]:
            out.append(parsed["tag"])
        if omitted:
            out.append(text.render("replies/tools.goal_hyps_omitted", count=omitted))
        out.extend(line for block in shown_hyps for line in block)
        out.extend(parsed["target"])
        cursor = parsed["end"]
    out.extend(lines[cursor:])
    return "\n".join(out)


def goal_blocks(goal: str) -> list[str]:
    """A goal text as its separate goals (case tag, hypotheses, `⊢` target), each one string."""
    lines = goal.strip("\n").split("\n")
    targets = [index for index, line in enumerate(lines) if line.startswith("⊢")]
    blocks: list[str] = []
    cursor = 0
    for target in targets:
        if target < cursor:
            continue
        parsed = _parse_goal(lines, max(cursor, _goal_start(lines, target)), target)
        blocks.append("\n".join(lines[cursor : parsed["end"]]))
        cursor = parsed["end"]
    if cursor < len(lines) and "\n".join(lines[cursor:]).strip():
        blocks.append("\n".join(lines[cursor:]))
    return blocks or [goal.strip()]


def compact_message(
    message: str, known: set[str] | frozenset[str] = frozenset(), hypothesis_chars: int | None = None
) -> str:
    """A Lean message with its goal state compacted by `compact_goal`; the text before the goal stays."""
    if "⊢" not in message:
        return message
    lines = message.split("\n")
    first = next((index for index, line in enumerate(lines) if line.startswith("⊢")), None)
    if first is None:  # `⊢` only inside a line (v7-check4 SKI: 11 scratch replies became internal errors)
        return message
    start = _goal_start(lines, first)
    return "\n".join([*lines[:start], compact_goal("\n".join(lines[start:]), known, hypothesis_chars)])


def hypothesis_set(goal: str | None) -> set[str]:
    """The normalized hypothesis texts of a goal, for `compact_goal`'s `known`."""
    if not goal or "⊢" not in goal:
        return set()
    lines = goal.strip("\n").split("\n")
    found: set[str] = set()
    cursor = 0
    for target in (index for index, line in enumerate(lines) if line.startswith("⊢")):
        if target < cursor:
            continue
        parsed = _parse_goal(lines, max(cursor, _goal_start(lines, target)), target)
        found.update(_normal(" ".join(block)) for block in parsed["hypotheses"])
        cursor = parsed["end"]
    return found


def shown(value: object) -> object:
    """A value as the model sees it: a missing one is "-", never Python's None."""
    return "-" if value is None or value == "" else value


def outcome(status: object, holes: list | None = None) -> object:
    """A node's internal status as the model reads it: its compile outcome phrase."""
    if status == "closed":
        return text.render("replies/tools.outcome_closed")
    if status == "ineligible":
        return text.render("replies/tools.outcome_ineligible")
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
    if not parents or (item.get("edge") or "root") == "root":
        return text.render("replies/tools.map_origin_root")
    return text.render("replies/tools.map_origin_from", parents=parents)


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


def _effort_lines(data: dict, compact: bool = False) -> list[str]:
    """The best node's steps ranked by points at stake, with units the model can act on."""
    rows = sorted(data.get("effort", []), key=lambda item: (-(item.get("at_stake") or 0), -(item.get("tokens") or 0)))
    if not rows:
        return []
    best = data.get("best") or {}
    lines = [
        text.render("replies/tools.map_steps_head", node=shown(best.get("node"))),
        *([] if compact else [text.render("replies/tools.map_steps_legend")]),
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
    # On a first node every step has 0 tries, so "barely tried" would name arbitrary steps.
    untried = _untried_steps(rest) if any(int(item.get("variants") or 0) for item in rows) else None
    if untried:
        lines.append(untried)
    return lines


def _untried_steps(hidden: list[dict]) -> str | None:
    """One line naming the steps below the table that still hold points but were barely tried: the table shows only
    the top steps, and in v7-em2 a 512-heartbeat step sat there untouched for the whole run."""
    numbers = text.numbers()
    most = int(numbers.get("untried_step_max_tries", 2))
    least = float(numbers.get("untried_step_min_pts", 0.5))
    picked = [
        item for item in hidden if int(item.get("variants") or 0) <= most and (item.get("at_stake") or 0) >= least
    ][:3]
    if not picked:
        return None
    named = ", ".join(
        text.render(
            "replies/tools.map_steps_untried_item",
            step=shown(item.get("step")),
            tries=int(item.get("variants") or 0),
            at_stake=shown(item.get("at_stake")),
        )
        for item in picked
    )
    return text.render("replies/tools.map_steps_untried", steps=named)


LINE_TEXT_CHARS = 90


def cell(value: object, limit: int = LINE_TEXT_CHARS) -> str:
    """Text inside a table cell: one line, no column separators, cut at `limit` characters."""
    flat = " ".join(str(value).replace("|", "\\|").replace("`", "'").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _line_cost_lines(data: dict, compact: bool = False) -> list[str]:
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
                text=cell(row["text"]),
                heartbeats=shown(row.get("heartbeats")),
                tokens=shown(row.get("tokens")),
            )
            for row in costs["tactic"]
        )
    if costs.get("quiet"):
        lines.append(text.render("replies/tools.map_quiet_lines_head", node=node))
        if not compact:
            lines.append(text.render("replies/tools.map_quiet_lines_note"))
        lines.append(text.render("replies/tools.map_quiet_lines_cols"))
        lines.extend(
            text.render(
                "replies/tools.map_quiet_line",
                line=row["line"],
                text=cell(row["text"]),
                tokens=shown(row.get("tokens")),
                heartbeats=shown(row.get("heartbeats")),
            )
            for row in costs["quiet"]
        )
    if costs.get("repeated"):
        lines.append(text.render("replies/tools.map_repeated_head"))
        lines.extend(
            text.render(
                "replies/tools.map_repeated_line",
                count=row["count"],
                tokens=shown(row["tokens"]),
                saved=shown(row["saved_tokens"]),
                points=shown(row["points"]),
                text=cell(row["text"]),
            )
            for row in costs["repeated"]
        )
    if not compact and (costs.get("tactic") or costs.get("quiet")):
        lines.append(text.render("replies/tools.map_lines_note"))
    return lines


def _map_lines(data: dict, compact: bool = False) -> list[str]:
    """The search map. `compact` (the copy a compile reply carries for a new best) keeps the best, its ranked
    steps, its costly lines and the open holes; `read` with view "map" shows everything."""
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
    archive = [] if compact else data.get("archive", [])
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
    recent = [] if compact else data.get("recent", [])
    if recent:
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
            for item in recent
        ]
    )
    if any(item.get("status") == "sketch" for item in recent):
        lines.append(text.render("replies/tools.map_recent_salvage"))
    lines.extend(_effort_lines(data, compact))
    lines.extend(_line_cost_lines(data, compact))
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


def _map_key(data: dict) -> list:
    """What makes a map worth showing again: the best node."""
    return [(data.get("best") or {}).get("node")]


def _commit_delivery(run_id: str, actor: str, fresh: list[dict]) -> dict:
    """Commit this actor's cursor with the delivered identities. The same delivery retries once."""
    from arena.run_control import actor_ids, apply_operation

    seqs = [int(item.get("seq", -1)) for item in fresh]
    identities = [str(item.get("event_id") or item.get("seq")) for item in fresh]
    operation_id = hashlib.sha256(f"{actor}:{seqs}:{identities}".encode()).hexdigest()[:32]
    identity = actor_ids(run_id)
    directory = campaign.run_dir(run_id)

    def mutate(ctx):
        return [
            ctx.append_ledger(
                {
                    "kind": "delivered_reply",
                    "data": {"seqs": seqs, "event_ids": identities, "cursor": max(seqs)},
                }
            )
        ]

    receipt = apply_operation(
        directory,
        {
            "operation_id": operation_id,
            "kind": "delivered_reply",
            "arguments": {"actor_id": actor, "seqs": seqs, "event_ids": identities},
            "run_id": run_id,
            "actor_id": identity["actor_id"] if identity["actor_id"] == actor else actor,
            "session_id": identity["session_id"],
        },
        mutate,
    )
    return {**receipt, "event_ids": identities, "operation_id": operation_id}


def redeliver(run_id: str, actor: str | None = None) -> dict:
    """Repeat the last committed delivery for this actor. Does not append another reply."""
    actor = actor or current_actor()
    bucket = _bucket(_load(run_id), actor)
    last = bucket.get("last_delivery")
    if not isinstance(last, dict):
        return {"ok": True, "event_ids": [], "repeated": False}
    from arena.run_control import apply_operation

    directory = campaign.run_dir(run_id)
    receipt = apply_operation(
        directory,
        {
            "operation_id": last["operation_id"],
            "kind": "delivered_reply",
            "arguments": last["arguments"],
            "run_id": run_id,
            "actor_id": actor,
            "session_id": os.environ.get("ARENA_SESSION_ID") or run_id,
        },
        lambda ctx: [],
    )
    return {"ok": True, "event_ids": last.get("event_ids") or [], "repeated": True, "receipt": receipt}


def attach_context(
    run_id: str,
    result: dict,
    *,
    include_map: bool = False,
    force_map: bool = False,
    holes: list[dict] | None = None,
) -> dict:
    """Attach new state updates and a changed map, persisting this actor's delivery cursor.
    `holes`, when given, replaces the map's open holes (the caller's current lineage only)."""
    actor = current_actor()
    state = _load(run_id)
    bucket = _bucket(state, actor)
    try:
        updates = campaign.state(run_id).get("updates", [])
    except (OSError, ValueError, KeyError):
        updates = []
    delivered = int(bucket.get("delivered_seq", -1))
    fresh = [item for item in updates if int(item.get("seq", -1)) > delivered]
    if include_map or force_map:
        data = campaign.map_view(run_id)
        if holes is not None:
            data["open"] = holes
        key = _map_key(data)
        # A compile reply carries the map only for a first or new best; `read` with view "map" shows all of it.
        if force_map or "map_hash" not in bucket or key != bucket.get("map_key"):
            lines = _map_lines(data, compact=not force_map)
            result["map"] = [text.render("replies/tools.section_map"), *lines] if lines else lines
        bucket["map_hash"], bucket["map_key"] = "shown", key
    # Node ids the model has been shown; an update never names a node outside them.
    seen = set(bucket.get("seen_nodes", [])) | _node_ids(result)
    authors = node_authors(run_id) if fresh else {}
    facts = [
        _tag_authors(_update_text(item, seen), authors)
        for item in fresh
        if isinstance(item.get("text"), str) and not item.get("quiet")
    ]
    facts += result.get("facts", [])
    if fresh:
        receipt = _commit_delivery(run_id, actor, fresh)
        bucket["delivered_seq"] = max(int(item.get("seq", -1)) for item in fresh)
        bucket["last_delivery"] = {
            "operation_id": receipt["operation_id"],
            "event_ids": receipt["event_ids"],
            "arguments": {
                "actor_id": actor,
                "seqs": [int(item.get("seq", -1)) for item in fresh],
                "event_ids": receipt["event_ids"],
            },
        }
        result["delivery"] = {"actor_id": actor, "event_ids": receipt["event_ids"], "cursor": bucket["delivered_seq"]}
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
    bucket["seen_nodes"] = sorted(seen | _node_ids(result))
    _write_actor(run_id, actor, bucket, state)
    return result


def node_authors(run_id: str) -> dict[str, str]:
    """Node id to the author label, for nodes first saved by an actor other than the caller's."""
    from arena import orchestration
    from arena.run_control import published_history

    try:
        directory = campaign.run_dir(run_id)
        history = published_history(directory, campaign.events(directory))
        first: dict[str, str] = {}
        for event in history:
            if event.get("kind") == "attempt" and event.get("proof_id") and event.get("actor_id"):
                first.setdefault(event["proof_id"], event["actor_id"])
        labels = orchestration.worker_job_labels(directory)
        me = current_actor()
        return {
            f"n{index}": labels.get(first[proof_id]) or ("orchestrator" if first[proof_id] == "sol" else first[proof_id])
            for index, proof_id in enumerate(campaign._graph_proof_ids(history), 1)
            if first.get(proof_id) not in (None, me)
        }
    except (OSError, ValueError, KeyError):
        return {}


def _tag_authors(line: str, authors: dict[str, str]) -> str:
    """Name the author at the first mention of each node another actor saved."""
    named: set[str] = set()

    def tag(match: re.Match) -> str:
        node = match.group(0)
        if node not in authors or node in named:
            return node
        named.add(node)
        return text.render("replies/tools.by_author", node=node, author=authors[node])

    return re.sub(r"\bn[1-9][0-9]*\b", tag, line)


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
