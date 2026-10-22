"""Python handlers for the v7 five-tool protocol surface."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time

from arena import campaign, engine, experiments, graph, reply, salvage, search, text
from arena.forbidden import official_filter
from arena.prices import rates, snippet_tokens
from arena.run_control import committed_operation_ids
from arena.steps import parse, split_steps, step_range

TOOL_FORMS = {
    "compile": ["drafts[1..N]", "splice{base,steps,text}", "fill{hole,text}", "merge{base,take}"],
    "goal": ["node+hole", "node+line", "hole:nN.hK", "try:[snippets]"],
    "search": ["queries:[strings]", "kind:name|type|text", "after:prefix"],
    "read": [
        "handle:decl:<name>",
        "node:nN",
        "hole:nN.hK",
        "experiment:eN",
        "ref:<evidence>",
        "view:source|prices|diff|outline|tree|tree:<page>|map",
        "step:sN (with view outline)",
        "against:nN (with view diff)",
    ],
    "scratch": ["code:<lean commands>", "replacement+at", "helpers:[experiment ids]"],
}


def _history(run_id: str) -> list[dict]:
    from arena.run_control import published_history

    directory = campaign.run_dir(run_id)
    return published_history(directory, campaign.events(directory))


def _nodes(run_id: str) -> tuple[list[dict], graph.Graph]:
    directory = campaign.run_dir(run_id)
    from arena.run_control import published_history

    history = published_history(directory, campaign.events(directory))
    return history, graph.Graph.from_history(
        history, campaign._proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )


def _node(run_id: str, reference: str):
    history, projection = _nodes(run_id)
    proof_id = campaign.resolve_node_ref(history, reference)
    return next(item for item in projection.nodes if item.proof_id == proof_id)


def _actor_focus_id(run_id: str):
    proof_id = reply.actor_focus_proof(run_id)
    _history_rows, projection = _nodes(run_id)
    if proof_id is None:
        proof_id = projection.focus
        if proof_id is not None:
            reply.set_actor_focus(run_id, proof_id)
    return next((item for item in projection.nodes if item.proof_id == proof_id), None)


def _focus_ref(run_id: str) -> str:
    actor_node = _actor_focus_id(run_id)
    if actor_node is not None:
        return actor_node.id
    _history_rows, projection = _nodes(run_id)
    node = next((item for item in projection.nodes if item.proof_id == projection.focus), None)
    if node is None:
        raise ValueError("focus")
    return node.id


def _empty_error(tool: str) -> dict:
    valid = {
        "compile": ["drafts", "splice", "fill", "merge", "steps", "text", "base", "from", "note", "check"],
        "goal": ["node", "hole", "line", "try"],
        "search": ["queries", "kind", "after"],
        "read": ["handle", "node", "hole", "experiment", "ref", "view", "against", "step"],
        "scratch": ["code", "replacement", "at", "helpers"],
    }[tool]
    return reply.error_reply("empty_arguments", "{}", valid, TOOL_FORMS[tool])


def _is_empty(request: object, tool: str) -> bool:
    if not isinstance(request, dict):
        return True
    keys = {
        "compile": ("drafts", "splice", "fill", "merge", "base", "from", "note", "check"),
        "goal": ("node", "hole", "line", "try"),
        "search": ("queries", "kind", "after"),
        "read": ("handle", "node", "hole", "experiment", "ref", "view", "against", "step"),
        "scratch": ("code", "replacement", "at", "helpers"),
    }[tool]
    return not any(key in request and request[key] not in (None, "", [], {}) for key in keys)


def _invalid(code: str, bad: object, valid: list[str], forms: list[str]) -> dict:
    return reply.error_reply(code, bad, valid, forms)


def _item_error(
    ref: str, code: str, bad: object, valid: list[str], forms: list[str], lines: list[str] | None = None
) -> dict:
    return reply.error_item(ref, code, bad, valid, forms, lines)


def _render(key: str, **values) -> str:
    return text.render(f"replies/tools.{key}", **values)


def _primary(result: dict) -> dict:
    compat = result.get("compat") or {}
    return next(iter(compat.values()), {})


def _proof_for_node(run_id: str, proof_id: str) -> str:
    return (campaign.run_dir(run_id) / "proofs" / f"{proof_id}.lean").read_text()


def _node_result(run_id: str, proof_id: str) -> dict:
    history = _history(run_id)
    for event in reversed(history):
        if event.get("proof_id") == proof_id and event.get("kind") == "probe":
            return event.get("result") or {}
        if event.get("candidate_id") == proof_id and event.get("kind") == "evaluation":
            return event.get("result") or {}
    return {}


def _filing_line(node, projection, result: dict) -> str:
    """How a node was filed, without its id: the operation and the node it came from."""
    edge = result.get("edge") or node.edge or {}
    sources = edge.get("from") or []

    def node_id(source: str) -> str:
        return next((item.id for item in projection.nodes if item.proof_id == source), "n?")

    if edge.get("type") == "filled_from" and sources:
        operation = edge.get("operation") or {}
        parent = node_id(sources[0])
        return _render("filing_fill", parent=parent, hole=f"{parent}.{operation.get('hole', '').split('.')[-1]}")
    if edge.get("type") == "edited_from" and sources:
        operation = edge.get("operation") or {}
        if operation.get("steps"):
            return _render("filing_splice", parent=node_id(sources[0]), steps=operation["steps"])
        return _render("filing_draft", parent=node_id(sources[0]))
    if edge.get("type") == "merged_from" and sources:
        ids = [node_id(source) for source in sources]
        return _render("filing_merge", base=ids[0], take=", ".join(ids[1:]) or "n?")
    if edge.get("type") == "filed_under_focus" and sources:
        return _render("filing_focus", focus=node_id(sources[0]))
    return _render("filing_root")


_TARGET_MARK = "in the target expression"


def _rewrite_parts(message: str) -> tuple[str, list[str]] | None:
    """A failed rewrite's missing pattern (one line) and the lines after its target expression (the goal), or None
    for any other message. Lean prints: headline, indented pattern, the mark, indented target, then the goal."""
    lines = message.split("\n")
    if _TARGET_MARK not in lines[1:] and not any(line.strip() == _TARGET_MARK for line in lines[1:]):
        return None
    mark = next(index for index, line in enumerate(lines) if line.strip() == _TARGET_MARK)
    pattern = " ".join(line.strip() for line in lines[1:mark])
    rest = lines[mark + 1 :]
    start = next((index for index, line in enumerate(rest) if line and not line[0].isspace()), len(rest))
    return pattern, rest[start:]


_GOAL_BLOCK_START = re.compile(r"^(?:case\s|⊢|\S[^:]*? : |\[)")


_COMBINING = re.compile("[\u0332\u0335\u0336]")
_DIFF_REMOVED = re.compile(".\u0335")


def plain_diff(message: str) -> str:
    """Lean draws a hint's suggested edit as a diff: removed characters carry U+0335, added ones U+0332. Keep the new
    text only; dropping just the marks would run the old and new text together (`par.red_KS`)."""
    if "\u0332" in message:
        message = _DIFF_REMOVED.sub("", message)
    return _COMBINING.sub("", message)
_HYP_NAME = re.compile(r"\w+✝[⁰¹²³⁴⁵⁶⁷⁸⁹]*")


def _same_message_key(message: str) -> str:
    """A message with line numbers, other digits and inaccessible hypothesis names blurred, so near-identical ones match."""
    return re.sub(r"\d+", "#", _HYP_NAME.sub("_", error_message(message)))


def _same_message_groups(groups: list[tuple[dict, int]]) -> list[tuple[dict, int, list[str]]]:
    """Groups whose messages match merge into the first; the ids of the later ones come back with it."""
    merged: dict[str, tuple[dict, int, list[str]]] = {}
    for item, branches in groups:
        message = item.get("message", "")
        # An open goal is its own fact; only the same complaint about different goals merges.
        key = f"{id(item)}" if message.startswith("unsolved goals") else _same_message_key(message)
        if key in merged:
            merged[key][2].append(str(item["id"]))
        else:
            merged[key] = (item, branches, [])
    return list(merged.values())


def error_message(message: str) -> str:
    """A diagnostic's text up to its goal block: the headline and the lines under it, joined into one line and capped
    at `error_message_chars`. A failed rewrite names the pattern it did not find instead."""
    message = plain_diff(message)
    parts = _rewrite_parts(message)
    lines = message.split("\n")
    if parts:
        return f"{lines[0]} `{parts[0]}`"
    kept = [lines[0]]
    for line in lines[1:]:
        if _GOAL_BLOCK_START.match(line):
            break
        kept.append(line)
    compact = " ".join(line.strip() for line in kept if line.strip())
    limit = int(text.numbers().get("error_message_chars", 400))
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _statement_by_line(proof: str) -> int | None:
    """The proof line (1-based) that ends the statement with `:= by`."""
    return next((number for number, line in enumerate(proof.split("\n"), 1) if re.search(r":=\s*by\s*$", line)), None)


def message_goal(message: str) -> str | None:
    """The goal Lean prints under the first line of a diagnostic (case tag, hypotheses, `⊢`), without the tactic's own report."""
    if message.startswith("No goals"):
        return None
    parts = _rewrite_parts(message)
    body: list[str] = []
    for line in parts[1] if parts else message.split("\n")[1:]:
        if line.startswith("["):
            break
        if not body and (not line.strip() or line.startswith(("Note:", "Hint:"))):
            continue  # Lean's advice lines before the goal are part of the report, not the goal
        body.append(line)
    goal = "\n".join(body).strip()
    return goal if "⊢" in goal else None


def _branch_groups(errors: list[dict]) -> list[tuple[dict, int]]:
    """Failures of one tactic after `<;>` arrive as one diagnostic per branch at the same position; keep the first of each."""
    groups: dict[tuple, list[dict]] = {}
    for item in errors:
        headline = item.get("message", "").split("\n")[0]
        fan_out = "<;>" in (item.get("source_line_text") or "")
        key = (item.get("line"), item.get("column"), headline) if fan_out else (id(item),)
        groups.setdefault(key, []).append(item)
    return [(items[0], len(items) if len(items) > 1 else 0) for items in groups.values()]


def all_errors(name: str, run_id: str, node, result: dict) -> tuple[list[dict], bool]:
    """Reveal diagnostics one step at a time without filing replacement texts."""
    primary = _primary(result)
    diagnostics = [item for item in primary.get("diagnostics", []) if item.get("severity") == "error"]
    if not diagnostics or result.get("timeout") or primary.get("timeout"):
        return diagnostics, False
    proof = node.proof_text
    max_passes = int(text.numbers().get("error_passes_max", 3))
    revealed = list(diagnostics)
    goal_by_line: dict[int, str] = {}
    for goals in [primary.get("goals") or [], result.get("goals") or []]:
        for item in goals:
            line = item.get("proof_line")
            value = item.get("goals")
            if isinstance(line, int) and value:
                goal_by_line[line] = "\n".join(value) if isinstance(value, list) else str(value)
    incomplete = False
    for _pass in range(max_passes):
        lines = proof.split("\n")
        roots = parse(lines)
        error_lines = {item.get("proof_line") for item in revealed if isinstance(item.get("proof_line"), int)}
        if roots is None or not error_lines:
            break
        planned, _strategies, reason = salvage.plan(lines, roots, {line - 1 for line in error_lines})
        if reason or planned is None:
            break
        replacement = "\n".join(planned)
        try:
            checked = campaign.evaluate(name, replacement, "probe", request_class="opportunistic")
        except (OSError, ValueError, RuntimeError):
            incomplete = True
            break
        checked_primary = _primary(checked)
        for item in checked_primary.get("goals", []) + checked.get("goals", []):
            line = item.get("proof_line")
            value = item.get("goals")
            if isinstance(line, int) and value:
                goal_by_line[line] = "\n".join(value) if isinstance(value, list) else str(value)
        next_errors = [item for item in checked_primary.get("diagnostics", []) if item.get("severity") == "error"]
        known = {(item.get("proof_line"), item.get("message")) for item in revealed}
        fresh = [item for item in next_errors if (item.get("proof_line"), item.get("message")) not in known]
        for item in fresh:
            row_item = dict(item)
            row_item["goal"] = message_goal(item.get("message", "")) or goal_by_line.get(item.get("proof_line"))
            revealed.append(row_item)
        if checked_primary.get("timeout") or checked.get("timeout"):
            incomplete = True
            break
        if not fresh:
            break
        proof = replacement
    else:
        incomplete = True
    ordered = sorted(revealed, key=lambda item: (item.get("proof_line") or 0, item.get("column") or 0))
    for index, item in enumerate(ordered, 1):
        item["goal"] = (
            None
            if str(item.get("message", "")).startswith("No goals")
            else message_goal(item.get("message", "")) or item.get("goal") or goal_by_line.get(item.get("proof_line"))
        )
        item["id"] = f"{node.id}.e{index}"
        item["line"] = item.get("proof_line")
    return ordered, incomplete


def _timed_out(primary: dict) -> bool:
    """Lean was cut off at its time limit: the version's error is the timeout message."""
    error = primary.get("error")
    return bool(error) and error == text.render("messages/errors.lean_timeout", timeout=engine.lean_timeout())


def _lineage(projection, node_ids: list[str]) -> set[str]:
    """Node ids of the given nodes and every ancestor (the base chain they were filed from)."""
    by_id = {node.id: node for node in projection.nodes}
    by_proof = {node.proof_id: node for node in projection.nodes}
    pending = [by_id[ident].proof_id for ident in node_ids if ident in by_id]
    seen: set[str] = set()
    while pending:
        proof_id = pending.pop()
        node = by_proof.get(proof_id)
        if node is None or proof_id in seen:
            continue
        seen.add(proof_id)
        pending.extend((node.edge or {}).get("from") or [])
    return {by_proof[proof_id].id for proof_id in seen}


def _open_holes(projection, lineage: set[str]) -> list[dict]:
    """Open sketch holes of the lineage only, with whole-line goals."""
    return [
        {
            "node": node.id,
            "hole": f"{node.id}.h{hole['index']}",
            "line": hole["line"],
            "goal": reply.goal_summary(hole.get("goal")),
        }
        for node in projection.nodes
        if node.id in lineage and node.status == "sketch"
        for hole in node.holes
        if hole["status"] == "open"
    ]


def _refresh_versions(item: dict, history: list[dict], projection) -> None:
    """Rewrite a closed item's versions and score from the ledger after the in-call check,
    so the item agrees with the state updates delivered alongside it."""
    price = item.get("price")
    if not isinstance(price, str) or not item.get("lines"):
        return
    proof_id = next((node.proof_id for node in projection.nodes if node.id == item["node"]), None)
    rows = {row["id"]: row for row in campaign._summaries(history)}
    row = rows.get(proof_id)
    if row is None or not row["evaluations"]:
        return
    total = len((history[0].get("versions") if history else None) or [1])
    full = [evaluation for evaluation in row["evaluations"] if evaluation["mode"] == "full"]
    source = full[-1] if full else row["evaluations"][-1]
    statuses = {version: bool(value.get("passed")) for version, value in (source["result"].get("compat") or {}).items()}
    tail = text.render(
        "replies/tools.refresh_tail",
        versions=campaign._versions_text(statuses, total),
        score="n/a" if row["score"] is None else f"{row['score']:.2f}",
    )
    first, separator, rest = price.partition("\n")
    head, marker, _stale = first.partition(" · versions ")
    if not marker:
        return
    refreshed = head + tail + separator + rest
    item["price"] = refreshed
    item["lines"] = [refreshed if line == price else line for line in item["lines"]]


def _mark_ineligible(item: dict, projection) -> None:
    """A node that fails a required version is never reported as compiling."""
    node = next((node for node in projection.nodes if node.id == item.get("node")), None)
    if node is not None and graph.shown_status(node) == "ineligible" and item.get("lines"):
        closed, failed = reply.outcome("closed"), reply.outcome("ineligible")
        item["lines"][0] = item["lines"][0].replace(f" {closed} ", f" {failed} ", 1)
        item["status"] = "ineligible"


def _best_label(history: list[dict], proof_id: str) -> str | None:
    rows = [row for row in campaign._summaries(history)
            if row.get("score") is not None and row.get("status") in ("primary", "full")
            and campaign.proof_eligibility(history, row["id"]) == "eligible"]
    verified = max((row for row in rows if row["verified"]), key=lambda row: row["score"], default=None)
    if verified and verified["id"] == proof_id:
        return _render("best_all_pin")
    provisional = max(rows, key=lambda row: row["score"], default=None)
    if provisional and not provisional["verified"] and provisional["id"] == proof_id:
        return _render("best_provisional")
    return None


def _invocation_evidence(name: str, run_id: str, proof_id: str, result: dict, attempt: dict | None) -> dict:
    """Join one invocation-owned attempt, never the node's most recent construction."""
    history = _history(run_id)
    data = (attempt or {}).get("data") or {}
    derivation = next((event for event in history if event.get("kind") == "derivation"
                       and event.get("proof_id") == proof_id
                       and data.get("construction_digest") is not None
                       and (event.get("data") or {}).get("construction_digest") == data.get("construction_digest")), None)
    key = campaign._evaluation_key(proof_id, "fast", campaign.problem(name))
    evaluation = next((event for event in reversed(history) if event.get("kind") == "evaluation"
                       and event.get("key") == key), None)
    if evaluation is None:
        evaluation = next((event for event in reversed(history) if event.get("kind") == "probe"
                           and event.get("proof_id") == proof_id), None)
    inputs = data.get("inputs") or []
    roles = {source["role"] for source in inputs}
    kind = ("merged_from" if "donor" in roles else "edited_from" if "base" in roles else
            "filled_from" if "sketch" in roles else "filed_under_focus" if "focus" in roles else "root")
    return {**result, "edge": {"type": kind, "from": [source["proof_id"] for source in inputs],
                              "operation": data.get("operation")},
            "attempt_id": (attempt or {}).get("event_id"),
            "derivation_id": (derivation or {}).get("event_id"),
            "construction_operation_id": (attempt or {}).get("operation_id"),
            "evaluation_id": (evaluation or {}).get("key") or (evaluation or {}).get("evaluation_id"),
            "evaluation_ref": None if evaluation is None else {
                "record": "ledger.jsonl",
                "row": next(index for index, event in enumerate(campaign.events(campaign.run_dir(run_id)), 1)
                            if event == evaluation),
            },
            "raw_result": (evaluation or {}).get("result") or {}}


def _compile_evidence(name: str, run_id: str, item: dict, history: list[dict], projection, result: dict) -> None:
    node = next(node for node in projection.nodes if node.id == item["node"])
    attempt = next((event for event in history if event.get("kind") == "attempt"
                    and event.get("event_id") == result.get("attempt_id")), None)
    data = (attempt or {}).get("data") or {}
    inputs = [dict(source) for source in data.get("inputs") or []]
    if (data.get("operation") or {}).get("steps"):
        for source in inputs:
            if source["role"] == "base":
                source["steps"] = data["operation"]["steps"]
    if data.get("named_parent"):
        inputs.append({"role": "named_parent", "proof_id": data["named_parent"]})
    labels = {node.proof_id: node.id for node in projection.nodes}
    for source in inputs:
        source["node"] = labels.get(source["proof_id"])
    raw = result.get("raw_result") or {}
    primary = campaign._verification_outcome(raw) if raw else result.get("outcome", "not_checked")
    if campaign._has_hole(campaign.problem(name), node.proof_text):
        primary = "incomplete"
    full_key = campaign._evaluation_key(node.proof_id, "full", campaign.problem(name))
    full = next((event.get("result") for event in reversed(history)
                 if event.get("kind") == "evaluation" and event.get("key") == full_key), None)
    full_status = campaign._verification_outcome(full) if full else "not_checked"
    if full_status == "passed" and len(full.get("compat") or {}) != len(history[0].get("versions") or []):
        full_status = "inconclusive"
    if full is None and any(job["id"] == node.proof_id
                            for job in campaign._autocheck_jobs(campaign._summaries(history))):
        full_status = "pending"
    cold = next((event for event in reversed(history) if event.get("kind") == "cold_verification"
                 and event.get("candidate_id") == node.proof_id), None)
    cold = campaign._cold_view(campaign.run_dir(run_id), history, cold) if cold else None
    verification = {"primary": primary, "full": full_status,
                    "cold": (cold or {}).get("outcome", "not_checked")}
    comparisons = []
    for source in inputs:
        parent = next((other for other in projection.nodes if other.proof_id == source["proof_id"]), None)
        if parent is None:
            continue
        previous = next((event.get("result") for event in reversed(history)
                         if (event.get("proof_id") or event.get("candidate_id")) == parent.proof_id
                         and event.get("kind") in ("evaluation", "probe")
                         and next(iter((event.get("result", {}).get("compat") or {}).keys()), None)
                         == next(iter((raw.get("compat") or {}).keys()), None)), None)
        deltas = {}
        if raw.get("tokens") is not None and previous and previous.get("tokens") is not None:
            deltas["tokens"] = raw["tokens"] - previous["tokens"]
        if primary == "passed" and previous and campaign._verification_outcome(previous) == "passed":
            heartbeat_deltas = {
                version: current["heartbeats"] - previous["compat"][version]["heartbeats"]
                for version, current in (raw.get("compat") or {}).items()
                if version in (previous.get("compat") or {}) and current.get("heartbeats") is not None
                and previous["compat"][version].get("heartbeats") is not None
            }
            if heartbeat_deltas:
                deltas["heartbeats_by_version"] = heartbeat_deltas
            elif (raw.get("heartbeat") is not None and previous.get("heartbeat") is not None
                  and len(raw.get("compat") or {}) == len(previous.get("compat") or {}) == 1):
                deltas["heartbeats"] = raw["heartbeat"] - previous["heartbeat"]
        comparisons.append({**source, "deltas": deltas})
    refs = {key: result.get(key) for key in
            ("attempt_id", "derivation_id", "construction_operation_id", "evaluation_id", "evaluation_ref")}
    item.update(**refs, operation=data.get("operation"), inputs=inputs, comparisons=comparisons,
                verification=verification, best=_best_label(history, node.proof_id))
    if not item.get("same_as"):
        item["lines"][0] = _render("compile_filed", node=node.id,
                                   outcome=reply.outcome(item["status"], node.holes),
                                   filing=_filing_line(node, projection, result))
    item["lines"].append(_render("compile_verification", **verification))
    if item["best"]:
        item["lines"].append(_render("compile_best", best=item["best"], node=node.id))
    for source in comparisons:
        changes = []
        for metric, delta in source["deltas"].items():
            if isinstance(delta, dict):
                changes.extend(_render("compile_heartbeat_delta", version=version, delta=f"{change:+}")
                               for version, change in delta.items())
            else:
                changes.append(_render("compile_delta", metric=metric, delta=f"{delta:+}"))
        item["lines"].append(_render("compile_input", role=source["role"], node=source["node"] or "?",
                                    detail=source.get("step") or source.get("steps") or source.get("hole") or "",
                                    deltas=", ".join(changes) or _render("compile_not_comparable")))


def _error_lines(name: str, run_id: str, node, projection, result: dict) -> tuple[list[str], list[dict], bool]:
    errors, incomplete = all_errors(name, run_id, node, result)
    if errors:
        errors = reply.deduplicate_diagnostics(run_id, node.id, errors)
    lines: list[str] = []
    groups = _same_message_groups(_branch_groups(errors))
    known = _statement_context(projection) | _binder_hypotheses(name, errors) if groups else set()
    if groups:
        lines.append(_render("lean_messages"))
    main_line = _statement_by_line(node.proof_text)
    for item, branches, same in groups:
        lines.append(
            _render(
                "error_item",
                id=item["id"],
                line=item.get("line") or "?",
                message=error_message(item.get("message", "")),
            )
        )
        if item.get("message", "").startswith("unsolved goals") and item.get("line") == main_line:
            lines.append(_render("error_main_goal_open"))
        if branches:
            lines.append(_render("error_branches", count=branches))
        if item.get("goal"):
            goal = reply.compact_goal(item["goal"], known, int(text.numbers().get("goal_hyp_chars", 1000)))
            lines.append(_render("error_goal", goal=goal))
        if same:
            lines.append(_render("error_same", count=len(same), ids=", ".join(same)))
    return lines, errors, incomplete


def _compile_item(name: str, run_id: str, node_ref: str, result: dict, filing: str) -> dict:
    _history_rows, projection = _nodes(run_id)
    node = next((item for item in projection.nodes if item.id == node_ref), None)
    if node is None:
        return {
            "ref": node_ref,
            "ok": False,
            "lines": [],
            "error": reply.request_error("internal_error", node_ref, [], TOOL_FORMS["compile"]),
        }
    primary = _primary(result)
    # `compat[v]["lean"]` is the model view's Lean-path string ("session" or a fallback note), not a dict.
    timeout = bool(result.get("timeout") or primary.get("timeout") or _timed_out(primary))
    holes = node.holes
    status = "timeout" if timeout else node.status
    lines = [_render("compile_filed", node=node.id, outcome=reply.outcome(status, holes), filing=filing)]
    if timeout:
        lines.append(_render("timeout", seconds=engine.lean_timeout()))
    error_lines, errors, incomplete = _error_lines(name, run_id, node, projection, result)
    lines.extend(error_lines)
    if holes:
        lines.append(_render("open_holes"))
    lines.extend(
        [
            _render(
                "hole_item",
                hole=f"{node.id}.h{hole['index']}",
                line=hole["line"],
                goal=reply.goal_summary(hole.get("goal"), limit=None) or "n/a",
            )
            for hole in holes
        ]
    )
    if node.status == "closed":
        price = result.get("price_row")
        if isinstance(price, str):
            lines.append(price)
        elif isinstance(price, dict):
            lines.append(
                _render(
                    "price",
                    node=node.id,
                    tokens=price.get("tokens", result.get("tokens", "n/a")),
                    heartbeats=price.get("hb", result.get("heartbeat", "n/a")),
                    versions=price.get("versions", "n/a"),
                )
            )
    last_line = max((item.get("line") or 0 for item in errors), default=0)
    facts = [_render("errors_incomplete", node=node.id, line=last_line)] if incomplete else []
    # Every attempt on this proof text leaves one ledger row, this one included.
    attempts = sum(
        1
        for event in _history_rows
        if event.get("kind") in ("probe", "repeat", "candidate")
        and (event.get("proof_id") or event.get("candidate_id")) == node.proof_id
    )
    repeat = attempts > 1
    if repeat:
        facts.append(_render("repeat_fact", node=node.id, count=attempts))
    return {
        "item": {
            "ref": node.id,
            "ok": True,
            "lines": lines,
            "error": None,
            "node": node.id,
            "status": status,
            "errors": errors,
            "holes": holes,
            "price": result.get("price_row"),
            "repeat": repeat,
            "attempts": node.attempts,
            "derivations": node.derivations,
            "eligibility": campaign.proof_eligibility(_history_rows, node.proof_id),
            "verification": status,
        },
        "facts": facts,
    }


def _focus_proof(run_id: str) -> tuple[str, str]:
    actor_node = _actor_focus_id(run_id)
    if actor_node is not None:
        return actor_node.id, actor_node.proof_text
    projection = _nodes(run_id)[1]
    node = next((item for item in projection.nodes if item.proof_id == projection.focus), None)
    if node is None:
        raise ValueError("focus")
    return node.id, node.proof_text


def _token_items(name: str, run_id: str, request: dict, op: str | None) -> dict:
    focus_id, focus_text = _focus_proof(run_id)
    if request.get("base"):
        base_node = _node(run_id, request["base"])
        focus_id, focus_text = base_node.id, base_node.proof_text
    drafts = request.get("drafts") if op is None else [request[op].get("text")]
    if op == "merge":
        operation = dict(request[op])
        base = operation.get("base") or focus_id
        base_node = _node(run_id, base)
        focus_id, focus_text = base_node.id, base_node.proof_text
        takes = [
            {"text": _node(run_id, take["from"]).proof_text, "step": take["step"]} for take in operation.get("take", [])
        ]
        proof = graph.merge_steps(base_node.proof_text, takes)
        drafts = [proof] if proof else []
    if op == "splice":
        data = request["splice"]
        base = data.get("base") or focus_id
        old = _node(run_id, base).proof_text
        first, last = step_range(split_steps(old), data.get("steps", ""))
        old_text = "\n".join(
            step.text for step in split_steps(old)[split_steps(old).index(first) : split_steps(old).index(last) + 1]
        )
        new_text = data.get("text", "")
        count = snippet_tokens(new_text)
        old_count = snippet_tokens(old_text)
        base_id = _node(run_id, base).id
        line = _render(
            "token_splice", ref="op1", tokens=count, steps=data.get("steps", ""), base=base_id, old_tokens=old_count
        )
        return reply.reply(
            items=[
                {"ref": "op1", "ok": True, "lines": [line], "error": None, "tokens": count, "delta": count - old_count}
            ]
        )
    if op == "fill":
        data = request["fill"]
        node_ref, hole_ref = data.get("hole", "").split(".", 1)
        if not isinstance(node_ref, str):
            raise ValueError(node_ref)
        node = _node(run_id, node_ref)
        next(hole for hole in node.holes if f"{node.id}.h{hole['index']}" == f"{node_ref}.{hole_ref}")
        count = snippet_tokens(data.get("text", ""))
        return reply.reply(
            items=[
                {
                    "ref": "op1",
                    "ok": True,
                    "lines": [_render("token_fill", ref="op1", tokens=count, hole=data.get("hole", ""))],
                    "error": None,
                    "tokens": count,
                    "delta": count - snippet_tokens("sorry"),
                }
            ]
        )
    normalized = []
    errors = []
    statement = campaign.problem(name)["statement"]
    old_count = engine._proof_length(focus_text, statement)
    for index, draft in enumerate(drafts or [], 1):
        try:
            proof = campaign.normalize_draft(name, draft)
            count = engine._proof_length(proof, statement)
            line = _render("token_draft", ref=f"d{index}", tokens=count, base=focus_id, base_tokens=old_count)
            normalized.append(
                {
                    "ref": f"d{index}",
                    "ok": True,
                    "lines": [line],
                    "error": None,
                    "tokens": count,
                    "delta": count - old_count,
                }
            )
        except (TypeError, ValueError) as error:
            errors.append(_item_error(f"d{index}", "invalid_draft", error, ["string"], TOOL_FORMS["compile"]))
    return reply.reply(items=normalized + errors)


def _flat_splice(request: object) -> object:
    """Top-level `steps` and `text` (with an optional `base`) are a splice: the same as `{"splice": {...}}`."""
    if not isinstance(request, dict) or "splice" in request or not ({"steps", "text"} & request.keys()):
        return request
    if any(key in request for key in ("drafts", "fill", "merge")):
        return request
    splice = {key: request[key] for key in ("base", "steps", "text") if key in request}
    rest = {key: value for key, value in request.items() if key not in ("base", "steps", "text")}
    return {**rest, "splice": splice}


def compile_tool(theorem: str, run_id: str, request: dict) -> dict:
    with campaign.compile_authorization():
        return _compile_tool(theorem, run_id, request)


def _compile_tool(theorem: str, run_id: str, request: dict) -> dict:
    valid = ["drafts", "splice", "fill", "merge", "base", "node", "from", "note", "check"]
    shown = [*valid[:4], "steps", "text", *valid[4:]]
    if isinstance(request, dict) and "node" in request:
        # `node` is an alias of `base`; both given and different is a conflict.
        if request.get("base") and request["base"] != request["node"]:
            return _invalid("base_conflict", f"{request['base']} / {request['node']}", ["one base"], TOOL_FORMS["compile"])
        request = {**{k: v for k, v in request.items() if k != "node"}, "base": request.get("base") or request["node"]}
    request = _flat_splice(request)
    if _is_empty(request, "compile"):
        return _empty_error("compile")
    if not isinstance(request, dict):
        return _invalid("bad_arguments", request, shown, TOOL_FORMS["compile"])
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], shown, TOOL_FORMS["compile"])
    operations = [key for key in ("drafts", "splice", "fill", "merge") if key in request]
    if (
        len(operations) == 1
        and operations[0] in ("splice", "merge")
        and request.get("base")
        and isinstance(request[operations[0]], dict)
    ):
        inner = request[operations[0]]
        if inner.get("base") and inner["base"] != request["base"]:
            return _invalid(
                "base_conflict", f"{request['base']} / {inner['base']}", ["one base"], TOOL_FORMS["compile"]
            )
        request = {**request, operations[0]: {**inner, "base": request["base"]}}
    if len(operations) != 1:
        return _invalid(
            "bad_operation",
            ",".join(operations) or "none",
            ["drafts", "splice", "fill", "merge"],
            TOOL_FORMS["compile"],
        )
    op = None if operations[0] == "drafts" else operations[0]
    check = request.get("check", "lean")
    if check not in ("lean", "tokens"):
        return _invalid("bad_check", check, ["lean", "tokens"], TOOL_FORMS["compile"])
    if op is None:
        drafts = request["drafts"]
        limit = int(text.numbers().get("compile_max_drafts", 4))
        if not isinstance(drafts, list) or not 1 <= len(drafts) <= limit:
            return _invalid("bad_drafts", drafts, [f"1..{limit} strings"], TOOL_FORMS["compile"])
    else:
        drafts = None
        if not isinstance(request[op], dict):
            return _invalid("bad_operation", request[op], [op], TOOL_FORMS["compile"])
    if check == "tokens":
        try:
            return _token_items(theorem, run_id, request, op)
        except (IndexError, KeyError, OSError, StopIteration, TypeError, ValueError, RuntimeError) as error:
            return _invalid(
                "invalid_operation",
                error,
                ["existing node id", "existing hole id", "existing step id"],
                TOOL_FORMS["compile"],
            )

    outcomes: list[tuple[str, dict, str]] = []
    evidence_by_ref = {}
    if op is None and not request.get("base"):
        raw_drafts = request["drafts"]
        good_drafts = []
        normalized_drafts = []
        indexes = []
        item_errors = []
        for index, draft in enumerate(raw_drafts, 1):
            if not isinstance(draft, str) or not draft.strip():
                item_errors.append(
                    _item_error(f"d{index}", "invalid_draft", draft, ["nonempty string"], TOOL_FORMS["compile"])
                )
            else:
                good_drafts.append(draft)
                normalized_drafts.append(campaign.normalize_draft(theorem, draft))
                indexes.append(index)
        if good_drafts:
            receipts = []
            token = campaign._OPERATION_RECEIPTS.set(receipts)
            try:
                batch = campaign.probe_batch(
                    theorem,
                    run_id,
                    good_drafts,
                    note=request.get("note"),
                    named_parent=request.get("from"),
                )
            finally:
                campaign._OPERATION_RECEIPTS.reset(token)
            invocation_ids = {reference["event_id"] for receipt in receipts
                              for reference in receipt.get("evidence_refs", [])}
            invocation_attempts = [event for event in _history(run_id)
                                   if event.get("kind") == "attempt" and event.get("event_id") in invocation_ids]
            projection = _nodes(run_id)[1]
            for original_index, proof, row in zip(indexes, normalized_drafts, batch.get("drafts", []), strict=False):
                outcome = {key: value for key, value in row.items() if key != "index"}
                proof_id = hashlib.sha256((theorem + "\0" + proof).encode()).hexdigest()
                attempt = next((event for event in invocation_attempts if event.get("proof_id") == proof_id), None)
                if attempt is not None:
                    invocation_attempts.remove(attempt)
                outcome = _invocation_evidence(theorem, run_id, proof_id, outcome, attempt)
                evidence_by_ref[f"d{original_index}"] = outcome
                node = next((item for item in projection.nodes if item.proof_id == proof_id), None)
                if node is not None and campaign.proof_eligibility(_history(run_id), node.proof_id) != "eligible":
                    campaign.select_proof(run_id, node.proof_id)
                outcomes.append((f"d{original_index}", outcome, node.id if node else ""))
        items = list(item_errors)
        refs: dict[str, tuple[str, dict]] = {}
        facts = []
        handles = []
        for ref, outcome, node_ref in outcomes:
            node = next((item for item in _nodes(run_id)[1].nodes if item.id == node_ref), None)
            if node:
                key = node.proof_text
                if key in refs:
                    first_ref, first_item = refs[key]
                    items.append(
                        {
                            "ref": ref,
                            "ok": True,
                            "lines": [_render("duplicate", ref=first_ref)],
                            "error": None,
                            "same_as": first_ref,
                            "node": node.id,
                            "status": first_item.get("status"),
                            "errors": first_item.get("errors", []),
                            "holes": first_item.get("holes", []),
                            "price": first_item.get("price"),
                        }
                    )
                    continue
                item_result = _compile_item(
                    theorem, run_id, node.id, outcome, _filing_line(node, _nodes(run_id)[1], outcome)
                )
                item_result["item"]["ref"] = ref
                refs[key] = (ref, item_result["item"])
                items.append(item_result["item"])
                facts.extend(item_result["facts"])
                handles.append(node.id)
                continue
            items.append(
                _item_error(
                    ref, "compile_failed", outcome.get("error", "compile"), ["valid proof text"], TOOL_FORMS["compile"]
                )
            )
    else:
        items = []
        facts = []
        handles = []
        if op is None:
            operation_rows = [
                (index, {"type": "draft", "base": request["base"], "text": draft})
                for index, draft in enumerate(request["drafts"], 1)
            ]
        else:
            data = request[op]
            if op in ("splice", "merge"):
                data = {**data, "base": data.get("base") or _focus_ref(run_id)}
            operation_rows = [(1, {"type": op, **data})]
        for index, operation in operation_rows:
            ref = f"d{index}" if op is None else "op1"
            try:
                result = campaign.compile_operation(
                    theorem,
                    run_id,
                    operation,
                    note=request.get("note"),
                    named_parent=request.get("from"),
                )
                evidence_by_ref[ref] = result
                node = _node(run_id, result["node"])
                if campaign.proof_eligibility(_history(run_id), node.proof_id) != "eligible":
                    campaign.select_proof(run_id, node.proof_id)
                item_result = _compile_item(
                    theorem, run_id, node.id, result, _filing_line(node, _nodes(run_id)[1], result)
                )
                item_result["item"]["ref"] = ref
                items.append(item_result["item"])
                facts.extend(item_result["facts"])
                handles.append(node.id)
            except (OSError, KeyError, StopIteration, ValueError, RuntimeError) as error:
                evidence = getattr(error, "operation_evidence", None)
                if evidence and evidence.get("node"):
                    evidence_by_ref[ref] = evidence
                    node = _node(run_id, evidence["node"])
                    item_result = _compile_item(theorem, run_id, node.id, evidence,
                                                _filing_line(node, _nodes(run_id)[1], evidence))
                    item_result["item"]["ref"] = ref
                    items.append(item_result["item"])
                    facts.extend(item_result["facts"])
                    handles.append(node.id)
                else:
                    items.append(_item_error(
                        ref,
                        "invalid_operation",
                        error,
                        ["existing node id", "existing hole id", "existing step id"],
                        TOOL_FORMS["compile"],
                    ))
    closed_nodes = [item.get("node") for item in items if item.get("status") == "closed"]
    if closed_nodes:
        seconds = float(text.numbers().get("cross_version_wait_seconds", 10))
        campaign.autocheck(theorem, run_id, max_seconds=seconds, kinds=("full",))
        # The step table describes the newest best node; without its profile every step would read "pending".
        campaign.profile_in_call(theorem, run_id, [node for node in closed_nodes if node])
    # Everything below reads one snapshot taken after the in-call check.
    history, projection = _nodes(run_id)
    for item in items:
        if item.get("status") == "closed" and item.get("node"):
            _refresh_versions(item, history, projection)
            _mark_ineligible(item, projection)
        if item.get("node") and item.get("ref") in evidence_by_ref:
            _compile_evidence(theorem, run_id, item, history, projection, evidence_by_ref[item["ref"]])
    for left, right, parent, steps in graph.merge_offers(projection, set(handles)):
        if reply.first_time(run_id, f"merge:{left},{right}"):
            facts.append(_render("merge_offer", left=left, right=right, parent=parent, steps=", ".join(steps)))
    focus = next((node.id for node in projection.nodes if node.proof_id == projection.focus), None)
    lineage = _lineage(projection, handles or ([focus] if focus else []))
    result = reply.reply(facts=facts, items=items, handles=handles)
    return reply.attach_context(run_id, result, include_map=True, holes=_open_holes(projection, lineage))


def _goal_names(goal: str) -> tuple[str, list[str]]:
    """A goal's case tag and the names of its hypotheses (the words before ' :' on each unindented line)."""
    lines = goal.splitlines()
    case = lines[0].removeprefix("case ").strip() if lines and lines[0].startswith("case ") else ""
    names = []
    for line in lines[1:] if case else lines:
        if line.startswith("⊢"):
            break
        if line[:1].strip() and " : " in line:
            names.extend(line.split(" : ", 1)[0].split())
    return case, names


def _goal_cases(goals: list[str], cap: int) -> str:
    """A name map (one line per goal), then every goal as its own block, headed by its case tag (Lean's `case foo`
    line); goals past `cap` are not shown."""
    shown = goals[:cap]
    names = []
    for index, goal in enumerate(shown, 1):
        case, hypotheses = _goal_names(goal)
        listed = " ".join(hypotheses) or "none"
        if case:
            names.append(_render("goal_map_case", case=case, names=listed))
        else:
            names.append(_render("goal_map_untagged", index=index, count=len(goals), names=listed))
    blocks = []
    for index, goal in enumerate(shown, 1):
        if goal.splitlines()[0].startswith("case "):
            blocks.append(goal)
        else:
            blocks.append(_render("goal_untagged", index=index, count=len(goals)) + "\n" + goal)
    return "\n".join(names) + "\n\n" + "\n\n".join(blocks)


def _target_lines(lines: list[str]) -> set[int]:
    """Goal identities, conclusion lines, and their indented continuations."""
    protected: set[int] = set()
    untagged = re.escape(text.template("replies/tools.goal_untagged").strip())
    untagged = untagged.replace(re.escape("{index}"), r"\d+").replace(re.escape("{count}"), r"\d+")
    active = False
    for index, line in enumerate(lines):
        if (line.startswith("case ") and ":" not in line) or re.fullmatch(untagged, line):
            protected.add(index)
        if line.startswith("⊢"):
            active = True
            protected.add(index)
        elif active and (not line or line[0].isspace()):
            protected.add(index)
        else:
            active = False
    return protected


def _preview_keeping_targets(shown: str, limit: int) -> str:
    """Shorten a goal view without dropping a conclusion. The caller keeps the untrimmed text."""
    if len(shown) <= limit:
        return shown
    lines = shown.splitlines()
    protected = _target_lines(lines)
    droppable = [index for index in range(len(lines)) if index not in protected]
    omitted = 0
    while len("\n".join(lines)) > limit and droppable:
        lines.pop(droppable.pop(0))
        protected = _target_lines(lines)
        droppable = [index for index in range(len(lines)) if index not in protected]
        omitted += 1
    body = "\n".join(lines)
    if omitted:
        body += "\n" + _render("try_goals_cut", count=omitted)
    return body


def _try_goals(item: dict) -> str:
    """The goals a snippet leaves. Hypotheses may be shortened; each ⊢ target stays whole."""
    goals = _open_goal_text(item)
    if not goals:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", goals) if block.strip()]
    cap = int(text.numbers().get("goal_cases_max", 12))
    shown = _goal_cases(blocks, cap)
    preview = _preview_keeping_targets(shown, int(text.numbers().get("goal_try_chars", 1500)))
    if len(blocks) > cap:
        preview += "\n" + _render("goal_cases_omitted", count=len(blocks) - cap, cap=cap)
    return preview


def goal_tool(theorem: str, run_id: str, request: dict) -> dict:
    if _is_empty(request, "goal"):
        return _empty_error("goal")
    valid = ["node", "hole", "line", "try"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["goal"])
    limit = int(text.numbers().get("goal_try_max", 6))
    tries = request.get("try", [])
    if not isinstance(tries, list) or len(tries) > limit:
        return _invalid("bad_try", tries, [f"0..{limit} strings"], TOOL_FORMS["goal"])
    try:
        if request.get("hole") and "." in request["hole"]:
            node_ref, hole_ref = request["hole"].split(".", 1)
        else:
            node_ref, hole_ref = request.get("node"), request.get("hole")
        if not isinstance(node_ref, str):
            raise ValueError(node_ref)
        node = _node(run_id, node_ref)
        proof = node.proof_text
        hole = None
        if hole_ref:
            match = re.fullmatch(r"h([1-9][0-9]*)", hole_ref)
            if not match:
                raise ValueError(hole_ref)
            hole = next(item for item in node.holes if item["index"] == int(match.group(1)))
            proof_line = hole["line"]
        else:
            line_value = request.get("line")
            if line_value is None:
                return _invalid(
                    "missing_position",
                    text.render("messages/errors.goal_position"),
                    ["line (1-based proof line)", "hole (nN.hK)"],
                    TOOL_FORMS["goal"],
                )
            proof_line = int(line_value)
            count = len(proof.splitlines())
            if not 1 <= proof_line <= count:
                raise ValueError(_render("goal_line_range", line=proof_line, count=count))
        earlier = [
            item
            for item in (_primary(_node_result(run_id, node.proof_id)).get("diagnostics") or [])
            if item.get("severity") == "error" and (item.get("proof_line") or 0) < proof_line
        ]
        if earlier:
            err = min(earlier, key=lambda item: item.get("proof_line", 0))
            return reply.reply(
                items=[
                    _item_error(
                        "goal",
                        "goal_blocked",
                        text.render("messages/errors.goal_blocked", line=proof_line, error_line=err.get("proof_line")),
                        [f"a line up to {err.get('proof_line')}"],
                        TOOL_FORMS["goal"],
                        [
                            _render(
                                "error_item",
                                id="error",
                                line=err.get("proof_line", "?"),
                                message=err.get("message", "").splitlines()[0],
                            )
                        ],
                    )
                ]
            )
        row = campaign.problem(theorem)
        version, commit = engine.versions(row)[0]
        built = engine.candidate_file(row, proof, version, commit)
        file_line = built["start_line"] + proof_line - 1
        position = {"line": file_line - 1, "column": 0}
        answer = engine.lean_goals(
            row, built["path"], built["text"], built["head"], position["line"], position["column"]
        )
        if answer is None:
            return reply.reply(
                items=[
                    _item_error(
                        "goal",
                        "lsp_unavailable",
                        proof_line,
                        ["reachable LSP lane"],
                        TOOL_FORMS["goal"],
                    )
                ]
            )
        goals = [str(goal).strip() for goal in (answer or {}).get("goals") or [] if str(goal).strip()]
        raw_goal = (answer or {}).get("rendered") or "\n".join(goals)
        rendered = raw_goal
        extra = [_render("try_replaces")] if tries else []
        if len(goals) > 1:
            cap = int(text.numbers().get("goal_cases_max", 12))
            rendered = _goal_cases(goals, cap)
            if len(goals) > cap:
                extra.append(_render("goal_cases_omitted", count=len(goals) - cap, cap=cap))
        if not rendered:
            rendered = _render("no_goal", line=proof_line)
        items = [
            {
                "ref": "goal",
                "ok": True,
                "lines": [_render("goal_item", node=node.id, line=proof_line, goal=rendered), *extra],
                "error": None,
                "goal": raw_goal,
                "goals": goals,
            }
        ]
        if tries:
            if hole is not None:
                absolute = built["start_line"] + hole["line"] - 2
                marker = built["text"].splitlines()[absolute]
                column = marker.find("sorry")
                lsp_hole = {
                    "line": absolute,
                    "end_line": absolute,
                    "column": column,
                    "end_column": column + len("sorry"),
                }
            else:
                step = next(item for item in split_steps(proof) if item.first_line <= proof_line <= item.last_line)
                start = built["start_line"] + step.first_line - 2
                end = built["start_line"] + step.last_line - 2
                final_line = built["text"].splitlines()[end]
                lsp_hole = {
                    "line": start,
                    "end_line": end,
                    "column": 0,
                    "end_column": len(final_line),
                }
            valid_tries = []
            valid_indexes = []
            for index, snippet in enumerate(tries, 1):
                if not isinstance(snippet, str) or not snippet.strip():
                    items.append(
                        _item_error(
                            f"t{index}",
                            "invalid_snippet",
                            snippet,
                            ["nonempty string"],
                            TOOL_FORMS["goal"],
                        )
                    )
                else:
                    valid_tries.append(snippet)
                    valid_indexes.append(index)
            tested = (
                engine.lean_try(row, built["path"], built["text"], built["head"], lsp_hole, valid_tries)
                if valid_tries
                else {"results": []}
            )
            for index, item in zip(valid_indexes, (tested or {}).get("results", []), strict=False):
                snippet = tries[index - 1]
                # The try lane measures no heartbeats, so the line shows only what was measured: the verdict and tokens.
                lines = [_render("try_item", index=index, verdict=_try_verdict(item), tokens=snippet_tokens(snippet))]
                left = _try_goals(item)
                if left:
                    lines.append(left)
                open_goals = _open_goal_text(item)
                items.append(
                    {
                        "ref": f"t{index}",
                        "ok": not item.get("timeout") and (item.get("returncode") == 0 or bool(open_goals)),
                        "lines": lines,
                        # The verdict line already says how the snippet failed; a second error line would repeat it.
                        "error": None,
                        "tokens": snippet_tokens(snippet),
                        "delta": snippet_tokens(snippet) - snippet_tokens("sorry"),
                        "goals": open_goals or item.get("goals_after"),
                        "output": item.get("output"),
                    }
                )
        return reply.attach_context(run_id, reply.reply(items=items), include_map=False)
    except (IndexError, KeyError, OSError, StopIteration, TypeError, ValueError, RuntimeError) as error:
        detail = str(error)
        if not detail or detail == "None":
            detail = " ".join(f"{key} {request[key]}" for key in ("node", "hole", "line") if request.get(key)) or "{}"
        return _invalid(
            "invalid_goal", detail, ["existing node id", "existing hole id", "1-based proof line"], TOOL_FORMS["goal"]
        )


def _open_goal_text(item: dict) -> str:
    """Goals left by a snippet. A closed snippet stays closed even if its log mentions unsolved goals."""
    goals = str(item.get("goals_after") or "").strip()
    output = str(item.get("output") or "")
    marker = output.find("unsolved goals")
    if not goals and item.get("returncode") not in (0, None) and marker >= 0:
        rest = output[marker:].split("\n", 1)
        kept = []
        for line in (rest[1] if len(rest) > 1 else "").splitlines():
            if re.match(r"\S+:\d+:\d+: ", line):
                break
            kept.append(line)
        goals = "\n".join(kept).strip()
    return goals


def _try_verdict(item: dict) -> str:
    """One snippet's outcome: timed out, open goals, its first error, or closed."""
    if item.get("timeout"):
        return _render("try_timeout")
    output = str(item.get("output") or "")
    found = re.search(r"\berror: (.*)", output) if item.get("returncode") != 0 else None
    goals = _open_goal_text(item)
    if goals and (found is None or found.group(1).startswith("unsolved goals")):
        count = len(re.findall(r"^⊢", goals, re.M)) or 1
        return _render("try_open", count=count)
    if item.get("returncode") != 0:
        if found:
            rest = output[found.start(1) :].splitlines()
            message = " ".join(
                line.strip() for line in rest[:2] if line.strip() and not re.match(r"\S+:\d+:\d+: ", line)
            )
            return _render("try_error", message=message or found.group(1).strip())
        return _render("try_error", message=output.strip().splitlines()[0] if output.strip() else "-")
    return _render("try_closed")


def _missing_line(row: dict, label: str) -> str | None:
    """First line of an exact-name miss that has visible names under a prefix of it."""
    if not row.get("missing") or not row.get("siblings"):
        return None
    return _render(
        "search_missing", query=label, prefix=row.get("sibling_prefix", ""), names=", ".join(row["siblings"])
    )


def _capped_hits(hits: list[dict]) -> list[dict]:
    """Every hit that names the query's declaration, then at most `search_fuzzy_hits` loose matches, in rank order."""
    limit = int(text.numbers().get("search_fuzzy_hits", 5))
    loose = 0
    kept = []
    for hit in hits:
        if hit.get("why") in ("fuzzy", "substring"):
            loose += 1
            if loose > limit:
                continue
        kept.append(hit)
    return kept


def _signature_preview(signature: str, limit: int) -> str:
    """Keep the end of a long signature, where the conclusion sits. Backticks stay out of the cell."""
    flat = reply.cell(signature, max(len(signature) * 2, 1))
    if len(flat) <= limit:
        return flat
    available = max(1, limit - len(_render("signature_clipped", signature="")))
    start = len(flat) - available
    if start > 0 and flat[start] == "|" and flat[start - 1] == "\\":
        start -= 1
    return _render("signature_clipped", signature=flat[start:].lstrip())


def _relevant_suggestion(query: str, suggestion: str) -> bool:
    """A suggestion is relevant when it continues the queried name, not a distant edit."""
    left, right = query.casefold(), suggestion.casefold()
    return len(left) >= 3 and (right.startswith(left) or left.startswith(right))


def _search_row(hit: dict) -> str:
    """One table row: the name once, its signature without the restated name, the place, and why it matched."""
    name = str(hit.get("name") or str(hit.get("handle", "")).removeprefix("decl:"))
    signature = str(hit.get("signature", ""))
    signature = signature.removeprefix(f"{name} : ")
    module = hit.get("module", "")
    place = module if hit.get("line") is None else _render("search_place", module=module, line=hit["line"])
    why = hit.get("why", "")
    if hit.get("match"):
        why = f"{why}: {hit['match']}"
    chars = int(text.numbers().get("search_signature_chars", 200))
    return _render(
        "search_row",
        name=reply.cell(name, 120),
        signature=_signature_preview(signature, chars),
        place=place,
        why=reply.cell(why, 80),
    )


def _empty_forms(code: object, kind: object) -> list[str]:
    if code == "empty_query" and kind in ("name", "type", "text"):
        return [_render(f"search_empty_{kind}")]
    return ["nonempty query"]


def search_tool(theorem: str, run_id: str, request: dict) -> dict:
    if _is_empty(request, "search"):
        return _empty_error("search")
    valid = ["queries", "kind", "after"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["search"])
    after = request.get("after")
    if after is not None and not isinstance(after, str):
        return _invalid("bad_after", after, [_render("search_form")], TOOL_FORMS["search"])
    queries = request.get("queries")
    if queries is None and after is not None:
        # The after form alone lists every completion of the prefix: one empty suffix.
        queries = [""]
    if not isinstance(queries, list):
        return _invalid("bad_queries", queries, [_render("search_form")], TOOL_FORMS["search"])
    kind = request.get("kind", "name")
    string_queries = [(index, query) for index, query in enumerate(queries) if isinstance(query, str)]
    found = search.search(theorem, [query for _, query in string_queries], kind=kind, after=after)
    by_index = dict(zip((index for index, _ in string_queries), found.get("queries", []), strict=False))
    items, handles, exact = [], [], 0
    for index, query in enumerate(queries):
        if index not in by_index:
            items.append(_item_error(f"q{index + 1}", "invalid_query", query, ["string"], TOOL_FORMS["search"]))
            continue
        row = by_index[index]
        query = row.get("query", "")
        # The after form without queries has an empty query: its prefix names the miss instead.
        label = str(query) or (after or "")
        error = row.get("error")
        if error and error.get("code") == "not_found":
            error = None
        missing = _missing_line(row, label)
        head = _render("search_head", query=label)
        if error:
            suggestions = error.get("suggestions") or row.get("suggestions") or []
            items.append(
                _item_error(
                    str(query),
                    error.get("code", "search_error"),
                    error.get("input", query),
                    error.get("valid") or _empty_forms(error.get("code"), kind),
                    TOOL_FORMS["search"],
                    [
                        head,
                        *([missing] if missing else []),
                        _render(
                            "search_miss",
                            query=label,
                            reason=error.get("code", "not found"),
                            suggestions=", ".join(suggestions) or "none",
                        ),
                    ],
                )
            )
            continue
        lines = [head, *([missing] if missing else [])]
        shown_hits = _capped_hits(row.get("hits", []))
        if shown_hits:
            lines.append(text.template("replies/tools.search_cols").strip())
        for hit in shown_hits:
            handles.append(hit.get("handle") or f"decl:{hit.get('name', '')}")
            lines.append(_search_row(hit))
        if any(hit.get("why") == "exact" for hit in shown_hits):
            exact += 1
        carried = row.get("suggestions") or []
        suggestions = carried or [
            name
            for name in ((row.get("error") or {}).get("suggestions") or [])
            if _relevant_suggestion(label, str(name))
        ]
        if not shown_hits and not missing:
            lines.append(
                _render(
                    "search_miss",
                    query=label,
                    reason=row.get("hint") or "no hit",
                    suggestions=", ".join(suggestions) or "none",
                )
            )
        elif row.get("hint"):
            lines.append(_render("search_hint", hint=row["hint"]))
        items.append(
            {
                "ref": str(query),
                "ok": True,
                "lines": lines,
                "error": None,
                "hits": row.get("hits", []),
                "hint": row.get("hint"),
                "suggestions": suggestions,
                "dropped": row.get("dropped"),
            }
        )
    first = next((item for item in items if item.get("lines")), None)
    if first is not None:
        first["lines"] = [_render("search_result", queries=len(queries), exact=exact), *first["lines"]]
    # The ledger keeps what the compaction memory needs from each hit, not the ranking details.
    hits = [
        {
            "name": hit.get("name", ""),
            "handle": hit.get("handle") or f"decl:{hit.get('name', '')}",
            "module": hit.get("module", ""),
            "signature": hit.get("signature", ""),
        }
        for item in items
        for hit in item.get("hits", [])
    ]
    campaign._append(campaign.run_dir(run_id), {"kind": "search", "hits": hits})
    return reply.attach_context(run_id, reply.reply(items=items, handles=handles), include_map=False)


# A leading `<source>:` (the packet prints sources as `arklib:path`) is dropped; a range is optional.
_FILE_HANDLE = re.compile(r"(?:[A-Za-z_][\w-]*:)?([^\s:]+\.lean)(?::(?:first-last|([1-9][0-9]*)-([1-9][0-9]*)))?")


def _file_read(theorem: str, run_id: str, handle: str) -> dict:
    """`<path>.lean:first-last` inside the run's Lean project or its dependencies, with file line numbers."""
    valid = ["decl:<qualified-name>[:20-50]", "<path>.lean:20-50"]
    match = _FILE_HANDLE.fullmatch(handle)
    if not match or match.group(1).startswith("/") or ".." in match.group(1).split("/"):
        return _invalid("bad_handle", handle, valid, TOOL_FORMS["read"])
    path = match.group(1)
    size = int(text.numbers().get("read_source_lines", 400))
    # Without a range the read starts at the top of the file, capped at one read's size.
    first = int(match.group(2) or 1)
    last = int(match.group(3)) if match.group(3) else first + size - 1
    if last < first:
        return _invalid("bad_handle", handle, ["first <= last"], TOOL_FORMS["read"])
    end = min(last, first + size - 1)
    try:
        result = campaign.source_range(theorem, path, first, end)
    except ValueError as error:
        return _invalid("unknown_handle", str(error).rstrip("."), valid, TOOL_FORMS["read"])
    campaign._append(
        campaign.run_dir(run_id),
        {"kind": "read", "handle": path, "first": result.get("first"), "last": result.get("last")},
    )
    lines = [_render("read_range", file=path, first=result.get("first", first), last=result.get("last", end))]
    lines.extend(result.get("text", "").splitlines())
    continuation = result.get("next_first")
    facts = [f"{path}:{continuation}-{continuation + size - 1}"] if continuation else []
    return reply.attach_context(
        run_id,
        reply.reply(facts=facts, items=[{"ref": path, "ok": True, "lines": lines, "error": None, "source": result}]),
        include_map=False,
    )


def _decl_read(theorem: str, run_id: str, handle: str) -> dict:
    if not handle.startswith("decl:"):
        return _file_read(theorem, run_id, handle)
    match = re.fullmatch(r"(decl:[^:\s]+)(?::(?:first-last|([1-9][0-9]*)-([1-9][0-9]*)))?", handle)
    if not match:
        return _invalid("bad_handle", handle, ["decl:<qualified-name>[:20-50]"], TOOL_FORMS["read"])
    canonical, first, last = match.groups()
    name = canonical.removeprefix("decl:")
    if name == theorem or theorem.endswith("." + name):
        # The run's own theorem is not in the search index: its pinned proof is the reference node.
        projection = _nodes(run_id)[1]
        original = next((node for node in projection.nodes if node.origin == "reference"), None)
        node_id = original.id if original else "n1"
        shown = read_tool(theorem, run_id, {"node": node_id, "view": "source"})
        shown["facts"] = [_render("own_theorem", handle=canonical, node=node_id), *shown.get("facts", [])]
        return shown
    resolved = search.resolve_handle(theorem, canonical)
    unknown_valid = ["decl:<name> from search", "node:n1"]
    if resolved is None:
        return _invalid("unknown_handle", canonical, unknown_valid, TOOL_FORMS["read"])
    # Ranges are file line numbers; without one the read covers the declaration only.
    base = int(resolved.get("line") or 1)
    size = int(text.numbers().get("read_source_lines", 400))
    start = int(first) if first else base
    indexed_end = resolved.get("end_line")
    end = int(last) if last else (int(indexed_end) if isinstance(indexed_end, int) and indexed_end >= start else None)
    end = None if end is None else min(end, start + size - 1)
    try:
        result = campaign.source_range(theorem, canonical, start, end)
    except ValueError as error:
        # Indexed but without pinned source (e.g. a generated or syntax declaration).
        return _invalid("unknown_handle", str(error).rstrip("."), unknown_valid, TOOL_FORMS["read"])
    campaign._append(
        campaign.run_dir(run_id),
        {"kind": "read", "handle": canonical, "first": result.get("first"), "last": result.get("last")},
    )
    lines = [
        _render(
            "read_source",
            file=result.get("path", ""),
            first=result.get("first", start),
            last=result.get("last", start),
            name=name,
        )
    ]
    lines.extend(result.get("text", "").splitlines())
    continuation = result.get("next_first")
    facts = [f"{canonical}:{continuation}-{continuation + size - 1}"] if continuation else []
    return reply.attach_context(
        run_id,
        reply.reply(
            facts=facts, items=[{"ref": canonical, "ok": True, "lines": lines, "error": None, "source": result}]
        ),
        include_map=False,
    )


# Rows of the cost tree view: the costliest nodes by points.
TREE_ROWS = 30


def _outline(theorem: str, run_id: str, node, wanted: object) -> tuple[list[str] | None, dict]:
    """The step table of a node (step, lines, tokens, heartbeats, pts, first line); with `wanted`, that step's full
    goal before it and the hypotheses that changed after it. Goals come from the recorded step goals."""
    steps = node.steps  # carries the recorded step goals; split_steps(proof) would drop them
    data = {"steps": [step.__dict__ for step in steps], "holes": node.holes}
    if wanted is not None:
        step = next((item for item in steps if item.id == wanted), None)
        if step is None:
            return None, data
        if not step.before and not step.after:
            campaign.step_goals_in_call(theorem, run_id, node.proof_id)
            step = next((item for item in _node(run_id, node.id).steps if item.id == wanted), step)
        lines = [_render("read_step", step=step.id, first=step.first_line, last=step.last_line)]
        if step.before:
            lines.append(_render("read_step_before", goal=step.before))
        if step.after:
            known = reply.hypothesis_set(step.before)
            lines.append(_render("read_step_after", goal=reply.compact_goal(step.after, known)))
        return _cut_outline(lines), data
    try:
        rows = {row["id"]: row for row in campaign.price_table(theorem, run_id, node.id)["rows"]}
    except (ValueError, OSError, StopIteration):
        rows = {}
    lines = [text.template("replies/tools.read_outline_cols").strip()]
    for step in steps:
        row = rows.get(step.id, {})
        first_line = next((line.strip() for line in step.text.splitlines() if line.strip()), "")
        lines.append(
            _render(
                "read_outline_row",
                step=step.id,
                first=step.first_line,
                last=step.last_line,
                tokens=reply.shown(row.get("tokens")),
                heartbeats=reply.shown(row.get("incl_hb")),
                text=reply.cell(first_line, 60),
            )
        )
    lines.append(_render("read_outline_hint"))
    return _cut_outline(lines), data


def _cut_outline(lines: list[str]) -> list[str]:
    """The outline within `outline_max_chars`; lines that do not fit are counted, not shown."""
    limit = int(text.numbers().get("outline_max_chars", 6000))
    kept, size = [], 0
    for line in lines:
        if size + len(line) + 1 > limit and kept:
            break
        kept.append(line)
        size += len(line) + 1
    if len(kept) < len(lines):
        kept.append(_render("read_outline_cut", count=len(lines) - len(kept), limit=limit))
    return kept


# A handle naming a node or hole reads exactly like the `node` or `hole` parameter.
_NODE_HANDLE = re.compile(r"node:(n[1-9][0-9]*)")
_HOLE_HANDLE = re.compile(r"hole:(n[1-9][0-9]*\.h[1-9][0-9]*)")


def _handle_as_target(request: dict) -> dict:
    handle = request.get("handle")
    if not isinstance(handle, str):
        return request
    node = _NODE_HANDLE.fullmatch(handle)
    hole = _HOLE_HANDLE.fullmatch(handle)
    if not node and not hole:
        return request
    key, value = ("node", node.group(1)) if node else ("hole", hole.group(1))
    rest = {name: item for name, item in request.items() if name != "handle"}
    return {**rest, key: value}


def _node_choices(run_id: str) -> list[str]:
    """The newest saved node ids, or the id form when none can be listed."""
    try:
        ids = [item.id for item in _nodes(run_id)[1].nodes]
    except (OSError, ValueError, KeyError):
        ids = []
    return ids[-8:] or [_render("read_node_form")]


def _hole_choices(run_id: str, hole_ref: object) -> list[str]:
    """Open hole ids of the named node when it resolves, else the full id form."""
    try:
        node = _node(run_id, str(hole_ref).split(".", 1)[0])
        choices = [f"{node.id}.h{row['index']}" for row in node.holes]
    except (OSError, ValueError, KeyError, StopIteration):
        choices = []
    return choices[:8] or ["nN.hK"]


def read_tool(theorem: str, run_id: str, request: dict) -> dict:
    if _is_empty(request, "read"):
        return _empty_error("read")
    valid = ["handle", "node", "hole", "experiment", "ref", "view", "against", "step"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["read"])
    if request.get("ref"):
        others = [key for key in ("handle", "node", "hole", "experiment") if request.get(key)]
        if others:
            return _invalid("bad_target", "ref", ["ref alone"], TOOL_FORMS["read"])
        return _read_evidence(run_id, request["ref"])
    if request.get("experiment"):
        others = [key for key in ("handle", "node", "hole") if request.get(key)]
        if others:
            return _invalid("bad_target", "experiment", ["experiment alone"], TOOL_FORMS["read"])
        return _read_experiment(run_id, request["experiment"])
    request = _handle_as_target(request)
    view = request.get("view", "source")
    tree_page = 1
    if isinstance(view, str) and view.startswith("tree"):
        if view == "tree":
            tree_page = 1
            view = "tree"
        elif re.fullmatch(r"tree:[1-9][0-9]*", view):
            tree_page = int(view.split(":", 1)[1])
            view = "tree"
        else:
            return _invalid("bad_view", view, ["tree", "tree:<page>"], TOOL_FORMS["read"])
    if request.get("handle") and view != "source":
        return _invalid("bad_view", view, ["source"], TOOL_FORMS["read"])
    if request.get("step") and view != "outline":
        return _invalid("bad_argument", "step", ["step with view outline"], TOOL_FORMS["read"])
    if request.get("against") and view != "diff":
        return _invalid("bad_argument", "against", ["against with view diff"], TOOL_FORMS["read"])
    targets = [key for key in ("handle", "node", "hole") if request.get(key)]
    if view == "map" and not targets:
        # The map covers the whole graph, so it needs no target.
        return reply.attach_context(run_id, reply.reply(), include_map=True, force_map=True)
    if len(targets) != 1:
        return _invalid("bad_target", ",".join(targets) or "none", ["one of handle, node, hole"], TOOL_FORMS["read"])
    if targets[0] == "handle":
        return _decl_read(theorem, run_id, request["handle"])
    target = targets[0]
    if target == "hole":
        hole_ref = request["hole"]
        try:
            node_ref, hole = hole_ref.split(".", 1)
            node = _node(run_id, node_ref)
            item = next(row for row in node.holes if f"h{row['index']}" == hole)
            if view != "source":
                return _invalid("bad_view", view, ["source"], TOOL_FORMS["read"])
            lines = [_render("read_hole", hole=hole_ref, line=item["line"], goal=item.get("goal") or "n/a")]
            return reply.attach_context(
                run_id,
                reply.reply(
                    items=[
                        {
                            "ref": hole_ref,
                            "ok": True,
                            "lines": lines,
                            "error": None,
                            "hole": item,
                            "fills": item.get("fills", []),
                        }
                    ]
                ),
            )
        except (ValueError, IndexError, StopIteration):
            return _invalid("invalid_hole", hole_ref, _hole_choices(run_id, hole_ref), TOOL_FORMS["read"])
    try:
        node = _node(run_id, request["node"])
    except (ValueError, StopIteration):
        return _invalid("unknown_node", request.get("node"), _node_choices(run_id), TOOL_FORMS["read"])
    projection = _nodes(run_id)[1]
    lines = []
    data = {}
    if view == "source":
        lines = [
            _render("read_node_source", node=node.id),
            *(
                _render("source_line", line=number, text=line)
                for number, line in enumerate(node.proof_text.splitlines(), 1)
            ),
        ]
        data["source"] = node.proof_text
    elif view == "prices":
        price = campaign.price_table(theorem, run_id, node.id)
        lines = str(price.get("text") or "").splitlines()
        data["prices"] = price
    elif view == "diff":
        against = request.get("against")
        parent_id = against or ((node.edge or {}).get("from") or [None])[0]
        if not isinstance(parent_id, str):
            return _invalid("invalid_against", parent_id, [item.id for item in projection.nodes], TOOL_FORMS["read"])
        try:
            other = _node(run_id, parent_id)
        except (ValueError, TypeError, StopIteration):
            return _invalid("invalid_against", parent_id, [item.id for item in projection.nodes], TOOL_FORMS["read"])
        diff = list(
            difflib.unified_diff(
                other.proof_text.splitlines(),
                node.proof_text.splitlines(),
                fromfile=other.id,
                tofile=node.id,
                lineterm="",
            )
        )
        lines = [_render("read_diff", node=node.id, against=other.id, change=f"{len(diff)} lines"), *diff]
        data["diff"] = diff
    elif view == "outline":
        lines, data = _outline(theorem, run_id, node, request.get("step"))
        if lines is None:
            return _invalid("unknown_step", request.get("step"), [step.id for step in node.steps], TOOL_FORMS["read"])
    elif view == "tree":
        tree = campaign.cost_tree(theorem, run_id, node.id, page=tree_page, page_size=TREE_ROWS)
        if not tree["profiled"]:
            lines = [_render("read_tree_pending", node=node.id)]
        else:
            evidence = tree["evidence"]
            shown_rows = evidence["page"]
            lines = [
                _render(
                    "read_tree_head",
                    node=node.id,
                    proof=evidence["proof_id"],
                    page=evidence["page_index"],
                    pages=evidence["page_count"],
                ),
                text.template("replies/tools.read_tree_cols").strip(),
            ]
            if evidence["has_columns"]:
                lines.insert(1, text.template("packet/price-table.coordinates").strip())
            lines += [
                _render(
                    "read_tree_row",
                    line=row["range"],
                    text=reply.cell(row["text"]),
                    kind=row["kind"],
                    tokens=row["tokens"],
                    heartbeats=row["incl_hb"],
                    own=row["self_hb"],
                )
                for row in shown_rows
            ]
            if evidence["omitted_on_page"]:
                lines.append(
                    _render(
                        "read_tree_more",
                        count=evidence["omitted_on_page"],
                        retrieval=evidence["next_retrieval"],
                    )
                )
            totals = {
                "measured": reply.shown(tree["measured"]),
                "attributed": reply.shown(tree["attributed"]),
                "rest": reply.shown(tree["unattributed"]),
            }
            if tree.get("floor") is not None and isinstance(tree["unattributed"], int):
                floor = tree["floor"]
                lines.append(
                    _render("read_tree_total_floor", **totals, floor=floor, after=max(0, tree["unattributed"] - floor))
                )
            else:
                lines.append(_render("read_tree_total", **totals))
        data["tree"] = tree
    elif view == "map":
        result = reply.attach_context(
            run_id,
            reply.reply(items=[{"ref": node.id, "ok": True, "lines": [], "error": None}]),
            include_map=True,
            force_map=True,
        )
        return result
    else:
        return _invalid("bad_view", view, ["source", "prices", "diff", "outline", "map", "tree"], TOOL_FORMS["read"])
    return reply.attach_context(
        run_id,
        reply.reply(items=[{"ref": node.id, "ok": True, "lines": lines, "error": None, **data}]),
        include_map=False,
    )


def _read_evidence(run_id: str, reference: str) -> dict:
    """Follow one compaction reference. Missing and uncommitted references are not found."""
    from arena.memory import original_evidence

    found = original_evidence(run_id, reference)
    if found is None:
        return _invalid("unknown_argument", reference, [], TOOL_FORMS["read"])
    if found.get("experiment_id") and "code" in found:
        return _read_experiment(run_id, found["experiment_id"])
    if found.get("kind") == "proof":
        lines = [found["text"]]
        return reply.attach_context(
            run_id,
            reply.reply(items=[{"ref": reference, "ok": True, "lines": lines, "error": None, "source": found["text"]}]),
            include_map=False,
        )
    lines = [json.dumps(found, ensure_ascii=False, sort_keys=True)]
    return reply.attach_context(
        run_id,
        reply.reply(items=[{"ref": reference, "ok": True, "lines": lines, "error": None, "record": found}]),
        include_map=False,
    )


def _read_experiment(run_id: str, reference: str) -> dict:
    found = experiments.retrieve(run_id, reference)
    if found is None:
        return _invalid("unknown_experiment", reference, [], TOOL_FORMS["read"])
    if found["code_status"] == "missing":
        lines = [_render("read_experiment_missing", experiment=reference)]
    elif found["code_status"] == "ambiguous":
        lines = [_render("read_experiment_ambiguous", experiment=reference)]
    else:
        # The outcome row already rendered this evidence. Read it back instead of projecting it again.
        lines = [line for line in (found.get("rendered") or []) if isinstance(line, str)]
        if not lines:
            lines = [
                _render(
                    "read_experiment",
                    experiment=found["experiment_id"],
                    outcome=found["outcome"],
                    validity=found["validity"],
                ),
                found["code"],
            ]
            if found.get("diagnostic"):
                lines.append(found["diagnostic"])
    return reply.attach_context(
        run_id,
        reply.reply(items=[{"ref": found["experiment_id"], "ok": True, "lines": lines, "error": None, **found}]),
        include_map=False,
    )


_MARK = re.compile(r"(?:.*:\sinfo:\s)?ARENA_MARK\s(\d+)")
_INFO_COMMAND = re.compile(r"#(?:check_failure|check|print|eval|reduce|synth|where|help)\b")


def _scratch_messages(output: str) -> list[dict]:
    """Every Lean message in order. Info text prints without a position (`trace_state`, `#check`). An `ARENA_MARK n`
    line, put in front of each info command by `scratch_tool`, starts that command's info message and names its
    snippet line. Other unpositioned text before any positioned message is an info message with line None; later
    it continues the message before it, except right after a goal state (its `⊢` target and the indented lines
    under it), where it starts a new info message."""
    found: list[dict] = []
    in_target = False
    previous_blank = False
    for line in output.splitlines():
        if not line.strip():
            previous_blank = True
            continue
        match = engine._HEADER.match(line)
        mark = _MARK.fullmatch(line.strip())
        if match:
            found.append({"severity": match["severity"], "line": int(match["line"]), "message": [match["rest"]]})
            in_target = False
        elif mark:
            found.append({"severity": "info", "line": None, "message": [], "mark": int(mark.group(1))})
            in_target = False
        elif found:
            ended = in_target and not line[0].isspace() and not previous_blank
            if ended:
                found.append({"severity": "info", "line": None, "message": [line]})
                in_target = line.startswith("⊢")
            else:
                found[-1]["message"].append(line)
                if line.startswith("⊢"):
                    in_target = True
                elif in_target and not line[0].isspace():
                    in_target = False
        else:
            found.append({"severity": "info", "line": None, "message": [line]})
            in_target = line.startswith("⊢")
        previous_blank = False
    result: list[dict] = []
    for item in found:
        lines = item["message"]
        # A goal state at the end of a command's info text is `trace_state` output of the declaration after it.
        first = next((index for index, line in enumerate(lines) if line.startswith("⊢")), None)
        start = reply._goal_start(lines, first) if first is not None and "mark" in item else 0
        if "mark" in item and first is not None and start > 0:
            result.append({**item, "message": "\n".join(lines[:start]).strip()})
            result.append({"severity": "info", "line": None, "message": "\n".join(lines[start:]).strip()})
        else:
            result.append({**item, "message": "\n".join(lines).strip()})
    return result


_UNKNOWN_NAME = re.compile(r"Unknown\s(?:constant|identifier)\s`([^`\s]+)`")
_DECLARATION_START = re.compile(
    r"(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable)\s+)*(?:example|theorem|lemma)\b"
)
# The measure definition without its bare trailing call, which would measure the snippet's first command a second time.
# Lean prints info messages without a position, so the values are read in the order the declarations ran.
_MEASURE_DEFINITION = engine.HEARTBEAT_WRAPPER.removesuffix("arena_measure_heartbeats\n")
_ARENA_LINE = re.compile(r"(?:.*:\sinfo:\s)?ARENA_HEARTBEATS\s(\d+)")
# not-model-facing: Lean code injected in front of every scratch snippet: no unused-variable lint, and a mark that
# names the snippet line of each info command's output.
_SNIPPET_PREFIX = (
    "set_option linter.unusedVariables false\n"  # log: Lean source, not model text
    "open Lean Elab Command in\n"
    'elab "arena_mark " n:num : command => logInfo m!"ARENA_MARK {n.getNat}"\n'
)


def _measured_snippet(code: str) -> tuple[str, list[int]]:
    """The snippet with the heartbeat measure in front of each top-level declaration and a mark in front of each
    info command, on the command's own line, so no line of the snippet moves. A declaration right after a doc
    comment or an attribute line stays unmeasured: the measure would separate it from its doc comment or attribute."""
    lines, starts, previous = [], [], ""
    for number, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        if _DECLARATION_START.match(line) and not previous.endswith("-/") and not previous.startswith("@["):
            starts.append(number)
            lines.append("arena_measure_heartbeats " + line)
        elif _INFO_COMMAND.match(line):
            lines.append(f"arena_mark {number} " + line)
        else:
            lines.append(line)
        if stripped:
            previous = stripped
    return "\n".join(lines) + ("\n" if code.endswith("\n") else ""), starts


def _binder_hypotheses(theorem: str, errors: list[dict]) -> set[str]:
    """Hypotheses in these goals named only by the theorem's own binders: the statement's context, which every
    goal repeats. A shadowed binder prints as `name✝`, so a rebound name is never matched."""
    statement = campaign.problem(theorem).get("statement") or ""
    head = statement.split(":=")[0]
    names = set(re.findall(r"[({\[⦃]\s*([^:(){}\[\]⦃⦄]+?)\s*:", head))
    binders = {name for group in names for name in group.split()}
    found: set[str] = set()
    for item in errors:
        for hypothesis in reply.hypothesis_set(item.get("goal")):
            declared = hypothesis.split(" : ", 1)[0].split()
            if declared and set(declared) <= binders:
                found.add(hypothesis)
    return found


def _statement_context(projection) -> set[str]:
    """The hypotheses every goal of this theorem starts with: those of the first recorded step goal."""
    for node in projection.nodes:
        for step in node.steps:
            if step.before and "⊢" in step.before:
                return reply.hypothesis_set(step.before)
    return set()


def _body_tokens(span: str) -> int:
    """Tokens after the declaration's first `:=`: the statement it restates is not counted."""
    _head, separator, rest = span.partition(":=")
    return snippet_tokens(rest if separator else span)


def _warning_text(message: str) -> str:
    """A warning on one line: its first line, without notes and strikethrough marks."""
    first = next((line for line in plain_diff(message).splitlines() if line.strip()), "")
    return " ".join(first.split())


def _error_text(message: str, known: set[str], limit: int) -> str:
    """An error with its goal state reduced to the hypotheses the theorem does not already have; notes dropped."""
    kept = [line for line in plain_diff(message).splitlines() if not line.startswith("Note:")]
    compact = reply.compact_message("\n".join(kept), known, int(text.numbers().get("goal_hyp_chars", 1000)))
    if any(line.startswith("⊢") for line in compact.splitlines()):
        return _preview_keeping_targets(compact, limit)
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


_TOPLEVEL = re.compile(r"(?m)^(def|theorem|lemma|abbrev|axiom|instance|class|structure|inductive|import)\b")
_COMMAND = re.compile(r"#(?:check|print|eval|reduce)\b")


def _scratch_form(request: dict) -> str:
    has_code = "code" in request
    anchored = "replacement" in request or "at" in request
    if has_code and anchored:
        return "mixed"
    return "anchored" if anchored else "general"


def _nonpromotion_reason(code: str) -> str:
    stripped = code.lstrip()
    if _COMMAND.match(stripped):
        return "general_check"
    if stripped.startswith("example"):
        return "unrelated_example"
    return "ambiguous_snippet"


def _proof_local(code: str) -> bool:
    return _TOPLEVEL.search(code) is None


def _frozen_anchor(run_id: str, anchor: dict) -> dict | str:
    """Revalidate a stored snapshot against canonical saved artifacts, never caller paths."""
    from arena.orchestration import _resolve_anchor

    scope = "step" if "hole" in anchor or "steps" in anchor else "proof"
    resolved = _resolve_anchor(campaign.run_dir(run_id), scope, anchor)
    if isinstance(resolved, str):
        return resolved
    if any(anchor.get(key) != value for key, value in resolved.items()):
        return "anchor_changed"
    return resolved


def _scratch_anchor(run_id: str, request: dict, *, full_target: bool = False) -> dict | str:
    """Resolve once. Jobs retain their recorded snapshot; caller hashes confer no authority."""
    from arena.orchestration import _resolve_anchor, jobs

    supplied = request.get("at")
    inherited = None
    job_id = os.environ.get("ARENA_JOB_ID")
    if job_id:
        snapshot = next(
            (job for job in jobs(campaign.run_dir(run_id), [job_id])["jobs"] if job.get("job_id") == job_id),
            None,
        )
        if snapshot is not None:
            inherited = snapshot.get("anchor")
    if supplied is None:
        if isinstance(inherited, dict):
            return _frozen_anchor(run_id, inherited)
        if full_target:
            try:
                node, _proof = _focus_proof(run_id)
            except (KeyError, StopIteration, ValueError):
                return "node"
            return _resolve_anchor(campaign.run_dir(run_id), "proof", {"node": node})
        return "anchor"
    if not isinstance(supplied, dict):
        return "anchor"
    resolved = _resolve_anchor(campaign.run_dir(run_id), "step", supplied)
    if isinstance(resolved, str):
        return resolved
    if isinstance(inherited, dict):
        frozen = _frozen_anchor(run_id, inherited)
        if isinstance(frozen, str):
            return frozen
        if resolved != frozen:
            return "ambiguous_anchor"
        return frozen
    return resolved


def _embeddable_scratch(code: str) -> bool:
    """Conservatively admit proof-local tactics, not Lean commands or declarations."""
    from arena.forbidden import remove_comments

    source = remove_comments(code)
    commands = re.compile(
        r"(?m)^\s*(?:@\[|#|(?:private|protected|noncomputable|unsafe)\b|"
        r"(?:def|theorem|lemma|example|abbrev|axiom|instance|class|structure|inductive|"
        r"opaque|import|namespace|section|end|open|export|variable|universe|set_option|"
        r"attribute|include|omit)\b)"
    )
    return commands.search(source) is None and official_filter()(re.sub(r"\bsorry\b", "trivial", code)) is None



def _promotion_item(experiment_id: str, code: str, outcome: str, lines: list[str], promotion: dict, *, ok: bool = True):
    return {
        "ref": experiment_id,
        "ok": ok,
        "lines": lines,
        "error": None,
        "experiment_id": experiment_id,
        "outcome": outcome,
        "code": code,
        "promotion": promotion,
        "validity": "not_a_target_candidate",
        "compatibility": "not_checked",
        "cold": "not_checked",
    }


def _scratch_promote(
    theorem: str, run_id: str, request: dict, helpers: list[str], *, source_code: str | None = None,
    body_offset: int | None = None, original_request: dict | None = None,
) -> dict:
    limit = int(text.numbers().get("scratch_max_chars", 4000))
    replacement = request.get("replacement")
    if not isinstance(replacement, str) or not replacement.strip():
        return _invalid("bad_replacement", "empty", [f"1..{limit} characters"], TOOL_FORMS["scratch"])
    if len(replacement) > limit:
        return _invalid(
            "bad_replacement", f"{len(replacement)} characters", [f"1..{limit} characters"], TOOL_FORMS["scratch"]
        )
    if re.search(r"(?m)^\s*import\b", replacement):
        return _invalid("bad_replacement", "import", ["no import lines"], TOOL_FORMS["scratch"])
    label = official_filter()(re.sub(r"\bsorry\b", "trivial", replacement))
    if label:
        return _invalid("forbidden", label, ["no forbidden constructs"], TOOL_FORMS["scratch"])
    anchor = _scratch_anchor(run_id, request, full_target=source_code is not None)
    if isinstance(anchor, str):
        return _invalid("bad_anchor", anchor, [_render("scratch_anchor_form")], TOOL_FORMS["scratch"])
    submitted_code = replacement if source_code is None else source_code
    context = {"form": "anchored" if source_code is None else "full_target", "anchor": anchor}
    if body_offset is not None:
        context["body_range"] = {"start": body_offset, "end": len(submitted_code)}
    accepted = experiments.accept(
        run_id, submitted_code, helpers, context=context,
        request=request if original_request is None else original_request,
    )
    experiment_id = accepted["experiment_id"]
    if accepted.get("replayed"):
        return _read_experiment(run_id, experiment_id)
    started = time.perf_counter()
    digest = accepted["code_sha256"]

    def close(outcome: str, promotion: dict, lines: list[str], *, ok: bool = True, diagnostic: str | None = None):
        experiments.finish(
            run_id,
            experiment_id,
            code=submitted_code,
            digest=digest,
            outcome=outcome,
            raw=None,
            rendered=lines,
            elapsed_ms=experiments.elapsed_since(started),
            input_ref=accepted["input_ref"],
            diagnostic=diagnostic,
            context=context,
            promotion=promotion,
            compatibility="not_checked",
            cold="not_checked",
        )
        evidence = experiments.retrieve(run_id, experiment_id)
        item = _promotion_item(experiment_id, submitted_code, outcome, lines, evidence["promotion"], ok=ok)
        response = reply.reply(ok=ok, items=[{**item, **{k: evidence[k] for k in evidence if k not in item}}])
        if diagnostic == "run_stopped":
            response["error"] = reply.request_error("run_stopped", run_id, [], TOOL_FORMS["scratch"])
        return response

    from arena.run_control import read_state

    if read_state(campaign.run_dir(run_id)).get("stopped"):
        promotion = {"state": "not_promoted", "reason": "run_stopped"}
        lines = [_render("scratch_not_promoted", reason="run_stopped")]
        closed = close("recorded", promotion, lines, ok=False, diagnostic="run_stopped")
        closed["ok"] = False
        closed["error"] = reply.request_error("run_stopped", run_id, [], TOOL_FORMS["scratch"])
        return closed
    prefix, missing = _scratch_helpers(run_id, helpers)
    if missing:
        promotion = {"state": "not_promoted", "reason": "dependency_missing", "helpers": missing}
        lines = [_render("scratch_not_promoted", reason="dependency_missing")]
        closed = close("dependency_missing", promotion, lines, ok=False, diagnostic="dependency_missing")
        closed["error"] = reply.request_error("dependency_missing", ",".join(missing), [], TOOL_FORMS["scratch"])
        return closed
    # The materialized prefix includes transitive dependencies, so validate all of it.
    if not _embeddable_scratch(prefix):
        promotion = {"state": "not_promoted", "reason": "helper_not_embeddable"}
        lines = [_render("scratch_not_promoted", reason="helper_not_embeddable")]
        return close("recorded", promotion, lines, ok=False, diagnostic="helper_not_embeddable")
    if not _embeddable_scratch(replacement):
        reason = _nonpromotion_reason(replacement)
        return close("recorded", {"state": "not_promoted", "reason": reason},
                     [_render("scratch_not_promoted", reason=reason)], ok=False, diagnostic=reason)
    if _scratch_cancelled(run_id):
        return close("cancelled", {"state": "not_promoted", "reason": "cancelled"},
                     [_render("scratch_cancelled")], ok=False, diagnostic="cancelled")
    embedded = prefix + replacement
    if source_code is not None:
        proof = submitted_code
        if prefix:
            import textwrap

            body = replacement.lstrip()
            if not re.match(r"by(?:\s|$)", body):
                reason = "helper_not_embeddable"
                return close("recorded", {"state": "not_promoted", "reason": reason},
                             [_render("scratch_not_promoted", reason=reason)], ok=False)
            body = prefix + textwrap.dedent(body[2:]).lstrip("\r\n")
            proof = submitted_code[:body_offset] + "by\n" + textwrap.indent(body, "  ")
        operation = {"type": "draft", "base": anchor["node"], "text": proof}
    elif "hole" in anchor:
        operation = {"type": "fill", "hole": anchor["hole"], "text": embedded}
    else:
        step_ids = anchor.get("step_ids") or []
        if not step_ids:
            promotion = {"state": "not_promoted", "reason": "anchor"}
            return close("recorded", promotion, [_render("scratch_not_promoted_anchor")], ok=False)
        spec = step_ids[0] if len(step_ids) == 1 else f"{step_ids[0]}-{step_ids[-1]}"
        operation = {"type": "splice", "base": anchor["node"], "steps": spec, "text": embedded}
    operation["experiment_id"] = experiment_id
    # Admission is checked again after dependency construction, just before submission.
    from arena.run_control import submission_barrier

    submission_barrier("before_promotion", campaign.run_dir(run_id))
    if _scratch_cancelled(run_id) or read_state(campaign.run_dir(run_id)).get("stopped"):
        reason = "cancelled" if _scratch_cancelled(run_id) else "run_stopped"
        return close(reason, {"state": "not_promoted", "reason": reason},
                     [_render("scratch_not_promoted", reason=reason)], ok=False, diagnostic=reason)
    try:
        with campaign.compile_authorization():
            result = campaign.compile_operation(theorem, run_id, operation, named_parent=anchor["proof_id"])
    except Exception as error:
        reason = "run_stopped" if read_state(campaign.run_dir(run_id)).get("stopped") else "invalid_operation"
        evidence = getattr(error, "operation_evidence", {})
        promotion = {"state": "not_promoted", "reason": reason,
                     **{key: value for key, value in evidence.items() if key not in {"raw_result", "edge"}}}
        if "edge" in evidence:
            promotion["derivation"] = evidence["edge"]
        return close("recorded", promotion, [str(error)], ok=False, diagnostic=str(error))
    try:
        raw_result = result.get("raw_result") or result
        status = campaign._verification_outcome(raw_result)
        complete = result.get("complete", not bool(raw_result.get("contains_sorry")))
        passed = status == "passed" and complete
        parent_result = _node_result(run_id, anchor["proof_id"])
        parent_tokens = parent_result.get("tokens")
        deltas = {}
        if isinstance(parent_tokens, int) and isinstance(result.get("tokens"), int):
            deltas["tokens"] = result["tokens"] - parent_tokens
        if status == "passed" and campaign._verification_outcome(parent_result) == "passed":
            # Heartbeats are comparable only on the same pinned version.
            heartbeat_deltas = {
                version: info["heartbeats"] - parent_info["heartbeats"]
                for version, info in (raw_result.get("compat") or {}).items()
                for parent_info in [(parent_result.get("compat") or {}).get(version, {})]
                if isinstance(info.get("heartbeats"), int) and isinstance(parent_info.get("heartbeats"), int)
            }
            if heartbeat_deltas:
                deltas["heartbeats_by_version"] = heartbeat_deltas
        history = _history(run_id)
        full_result = result.get("full_result")
        full = campaign._verification_outcome(full_result) if isinstance(full_result, dict) else "not_checked"
        if full == "passed" and len(full_result.get("compat") or {}) != len(campaign.versions(campaign.problem(theorem))):
            full = "inconclusive"
        if full_result is None and any(
            job["id"] == result.get("proof_id") for job in campaign._autocheck_jobs(campaign._summaries(history))
        ):
            full = "pending"
        node = _node(run_id, result["node"])
        cold = next((row for row in reversed(history) if row.get("kind") == "cold_verification"
                     and row.get("candidate_id") == node.proof_id), None)
        cold = campaign._cold_view(campaign.run_dir(run_id), history, cold)
        verification = {
            "fast": status if complete else "incomplete",
            "full": full,
            "cold": "not_checked" if cold is None else cold.get("outcome") or (
                "passed" if cold.get("confirmed") else (
                    "proof_error" if campaign._verification_outcome(cold) == "proof_error" else "inconclusive"
                )
            ),
        }
        promotion = {
            "state": "promoted" if passed else "failed" if status == "proof_error" else "not_promoted",
            "node": node.id,
            "proof_id": node.proof_id,
            "derivation": result.get("edge"),
            "attempt_id": result.get("attempt_id"),
            "attempt_ids": [result["attempt_id"]] if result.get("attempt_id") else [],
            "derivation_id": result.get("derivation_id"),
            "construction_operation_id": result.get("construction_operation_id"),
            "evaluation_id": result.get("evaluation_id"),
            "evaluation_ref": result.get("evaluation_ref"),
            "deltas": deltas,
            "verification": verification,
            "diagnostics": {version: value.get("diagnostics", [])
                            for version, value in (raw_result.get("compat") or {}).items()},
        }
        if not passed:
            promotion["reason"] = "incomplete" if not complete else status
        outcome = "success" if passed else "failure" if status == "proof_error" else "incomplete" if not complete else status
        lines = [
            _render("scratch_experiment", experiment=experiment_id, outcome=outcome),
            _render(
                "scratch_promoted" if passed else "scratch_filed_unpromoted",
                node=node.id,
                fast=verification["fast"],
                full=verification["full"],
                cold=verification["cold"],
                **({} if passed else {"reason": promotion["reason"]}),
            ),
        ]
        if status == "proof_error" and not passed:
            lines.extend(_error_lines(theorem, run_id, node, _nodes(run_id)[1], raw_result)[0])
        best = _best_label(history, node.proof_id) if passed else None
        promotion["best"] = best
        if best:
            lines.append(
                _render(
                    "scratch_best",
                    best=best,
                    node=node.id,
                )
            )
        for name, delta in deltas.items():
            if name == "heartbeats_by_version" and isinstance(delta, dict):
                for version, change in delta.items():
                    lines.append(_render("compile_heartbeat_delta", version=version, delta=change))
            else:
                lines.append(_render("scratch_delta", name=name, delta=delta))
    except Exception as error:
        references = {key: result.get(key) for key in (
            "node", "proof_id", "attempt_id", "derivation_id", "construction_operation_id",
            "evaluation_id", "evaluation_ref", "edge",
        )}
        references["derivation"] = references.pop("edge")
        promotion = {"state": "not_promoted", "reason": "processing_error", **references}
        return close("processing_error", promotion, [str(error)], ok=False, diagnostic=str(error))
    return close(outcome, promotion, lines, ok=True)


def scratch_tool(theorem: str, run_id: str, request: dict) -> dict:
    """Retain isolated experiments and submit exact target proofs through normal compile."""
    if _is_empty(request, "scratch"):
        return _empty_error("scratch")
    valid = ["code", "replacement", "at", "helpers", "note"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["scratch"])
    prior = experiments.replay_request(run_id, request)
    if prior is not None:
        return _read_experiment(run_id, prior["experiment_id"])
    if _scratch_form(request) == "mixed":
        return _invalid("mixed_form", "code+replacement", ["code", "replacement+at"], TOOL_FORMS["scratch"])
    if _scratch_form(request) == "anchored":
        helpers = request.get("helpers", [])
        if not isinstance(helpers, list) or any(not isinstance(item, str) or not item for item in helpers):
            return _invalid("bad_helpers", helpers, ["experiment ids"], TOOL_FORMS["scratch"])
        return _scratch_promote(theorem, run_id, request, helpers)
    helpers = request.get("helpers", [])
    if not isinstance(helpers, list) or any(not isinstance(item, str) or not item for item in helpers):
        return _invalid("bad_helpers", helpers, ["experiment ids"], TOOL_FORMS["scratch"])
    limit = int(text.numbers().get("scratch_max_chars", 4000))
    code = request.get("code")
    if not isinstance(code, str) or not code.strip():
        return _invalid("bad_code", "empty", [f"1..{limit} characters"], TOOL_FORMS["scratch"])
    if len(code) > limit:
        return _invalid("bad_code", f"{len(code)} characters", [f"1..{limit} characters"], TOOL_FORMS["scratch"])
    if re.search(r"(?m)^\s*import\b", code):
        return _invalid("bad_code", "import", ["no import lines"], TOOL_FORMS["scratch"])
    # sorry is allowed in scratch: it is checked as a neutral word, so every other construct is still refused.
    label = official_filter()(re.sub(r"\bsorry\b", "trivial", code))
    if label:
        return _invalid("forbidden", label, ["no forbidden constructs"], TOOL_FORMS["scratch"])
    discovery_error = None
    try:
        problem = campaign.problem(theorem)
        statement = problem.get("statement")
    except Exception as error:
        problem, statement = {}, None
        discovery_error = error
    if isinstance(statement, str) and statement.strip():
        start = len(code) - len(code.lstrip())
        # Models often repeat the header's own `open`/`set_option` lines before the statement; the target file has them.
        preamble = {line.strip() for line in (problem.get("header") or "").splitlines()
                    if line.strip() and not line.startswith("import")}
        while (end := code.find("\n", start)) >= 0 and code[start:end].strip() in preamble:
            start = end + 1 + len(code[end + 1:]) - len(code[end + 1:].lstrip())
        head = statement
        if code.startswith(head, start):
            assignment = re.match(r"\s*:=", code[start + len(head):])
            if assignment is not None:
                body_offset = start + len(head) + assignment.end()
                body = code[body_offset:]
                if body.strip() and _embeddable_scratch(body):
                    return _scratch_promote(
                        theorem, run_id, {"replacement": body}, helpers,
                        source_code=code, body_offset=body_offset, original_request=request,
                    )
    digest = hashlib.sha256(code.encode()).hexdigest()
    earlier = sum(
        1
        for event in _history(run_id)
        if event.get("kind") == "scratch"
        and event.get("code_sha256") == digest
        and event.get("phase") in {None, "accepted"}
    )
    # Retain the exact input before context construction or Lean can fail; instrumentation is not the source.
    accepted = experiments.accept(run_id, code, helpers, request=request)
    experiment_id = accepted["experiment_id"]
    if accepted.get("replayed"):
        return _read_experiment(run_id, experiment_id)
    started = time.perf_counter()
    execution = {"stage": "construction", "context": {"theorem_run": run_id}, "raw": None}
    try:
        if discovery_error is not None:
            raise discovery_error
        return _scratch_check(theorem, run_id, code, helpers, accepted, earlier, started, execution)
    except Exception as error:
        outcome = (
            "cancelled"
            if _scratch_cancelled(run_id)
            else {
                "construction": "construction_error",
                "execution": "execution_error",
                "processing": "processing_error",
            }[execution["stage"]]
        )
        experiments.finish(
            run_id,
            experiment_id,
            code=code,
            digest=digest,
            outcome=outcome,
            raw=execution["raw"],
            rendered=[str(error)],
            elapsed_ms=experiments.elapsed_since(started),
            input_ref=accepted["input_ref"],
            diagnostic=str(error),
            context=execution["context"],
            promotion={
                "state": "not_promoted",
                "reason": outcome if outcome in {"cancelled", "dependency_missing"} else _nonpromotion_reason(code),
            },
        )
        evidence = experiments.retrieve(run_id, experiment_id)
        return reply.reply(
            ok=False,
            items=[{"ref": experiment_id, "ok": False, "lines": [str(error)], "error": None, **evidence}],
        )


def _scratch_cancelled(run_id: str) -> bool:
    job_id = os.environ.get("ARENA_JOB_ID")
    if not job_id:
        return False
    from arena.orchestration import jobs

    snapshots = jobs(campaign.run_dir(run_id), [job_id])["jobs"]
    activation_id = os.environ.get("ARENA_ACTIVATION_ID")
    for job in snapshots:
        activations = job["activations"] if activation_id else [job]
        for activation in activations:
            if activation_id and activation["activation_id"] != activation_id:
                continue
            if activation["state"] in {"cancelling", "cancelled"}:
                return True
    return False


def _scratch_helpers(run_id: str, helpers: list[str]) -> tuple[str, list[str]]:
    """Materialize only named dependencies, in dependency order, inside this one scratch file."""
    code, missing = [], []
    included, visiting = set(), set()

    def include(reference):
        if reference in visiting:
            missing.append(reference)
            return
        if reference in included:
            return
        retained = experiments.retrieve(run_id, reference)
        if retained is None or retained.get("code_status") != "retained":
            missing.append(reference)
            return
        visiting.add(reference)
        for dependency in retained.get("helpers", []):
            include(dependency)
        visiting.remove(reference)
        included.add(reference)
        value = retained["code"]
        code.append(value + ("" if value.endswith("\n") else "\n"))

    for reference in helpers:
        include(reference)
    return "".join(code), missing


def _scratch_check(theorem, run_id, code, helpers, accepted, earlier, started, execution):
    experiment_id = accepted["experiment_id"]
    digest = accepted["code_sha256"]
    helper_prefix, missing = _scratch_helpers(run_id, helpers)
    if missing or _scratch_cancelled(run_id):
        outcome = "dependency_missing" if missing else "cancelled"
        lines = [] if missing else [_render("scratch_cancelled")]
        experiments.finish(
            run_id,
            experiment_id,
            code=code,
            digest=digest,
            outcome=outcome,
            raw=None,
            rendered=lines,
            elapsed_ms=experiments.elapsed_since(started),
            input_ref=accepted["input_ref"],
            diagnostic=outcome if missing else None,
            promotion={"state": "not_promoted", "reason": outcome},
        )
        evidence = experiments.retrieve(run_id, experiment_id)
        return reply.reply(
            ok=not missing,
            error=reply.request_error("dependency_missing", ",".join(missing), [], TOOL_FORMS["scratch"])
            if missing
            else None,
            items=[{"ref": experiment_id, "ok": not missing, "lines": lines, "error": None, **evidence}],
        )
    checked_code = helper_prefix + code
    row = campaign.problem(theorem)
    version, commit = engine.versions(row)[0]
    context = {
        "theorem_run": run_id,
        "version": version,
        "commit": commit,
        "helpers": helpers,
        "helper_prefix_lines": helper_prefix.count("\n"),
    }
    execution["context"] = context
    # The snippet takes the target declaration's place in the same file the compile tool checks.
    measured_code, measured_starts = _measured_snippet(checked_code)
    built = engine.candidate_file(row, measured_code, version, commit)
    facts = [_render("scratch_repeat", count=earlier + 1)] if earlier else []
    if helper_prefix:
        facts.append(_render("scratch_helper_lines", line=helper_prefix.count("\n") + 1))
    code_lines = checked_code.splitlines()
    declarations = [number for number, line in enumerate(code_lines, 1) if _DECLARATION_START.match(line)]
    # The prefix goes in front of the snippet as compile's measure does; its lines are mapped back below.
    inserted = _SNIPPET_PREFIX + (_MEASURE_DEFINITION if measured_starts else "")
    wrapper_start = built["text"][: built["head"]].count("\n") + 1
    # The doc comment and attributes in front of the replaced declaration would attach to the snippet's first
    # command (`#check` then fails to parse); blank them, keeping the line count.
    orphans = built["text"][built["head"] : built["offset"]]
    lean_text = (
        built["text"][: built["head"]] + inserted + "\n" * orphans.count("\n") + built["text"][built["offset"] :]
    )
    context.update(
        {
            "project": str(built["path"]),
            "source_sha256": hashlib.sha256(lean_text.encode()).hexdigest(),
            "prefix_sha256": hashlib.sha256(lean_text[: built["head"]].encode()).hexdigest(),
        }
    )
    if _scratch_cancelled(run_id):
        experiments.finish(
            run_id,
            experiment_id,
            code=code,
            digest=digest,
            outcome="cancelled",
            raw=None,
            rendered=[_render("scratch_cancelled")],
            elapsed_ms=experiments.elapsed_since(started),
            input_ref=accepted["input_ref"],
            context=context,
            promotion={"state": "not_promoted", "reason": "cancelled"},
        )
        return _read_experiment(run_id, experiment_id)
    execution["stage"] = "execution"
    denied = None
    try:
        output = engine.run_lean(
            row, built["path"], lean_text, prefix_end=built["head"], request_class=engine.actor_request_class()
        )
    except engine.LeanInconclusive as error:
        output, denied = None, error
    execution["stage"] = "processing"
    execution["raw"] = None if output is None else output[1]
    experiments.record_raw(run_id, experiment_id, output, context=context)
    lines: list[str] = []
    heartbeats: dict[int, int] = {}
    errors = warnings = 0
    messages: list[tuple[int | None, dict]] = []
    known = _statement_context(_nodes(run_id)[1])
    message_chars = int(text.numbers().get("scratch_message_chars", 3000))
    info_rows: list[str] = []
    warning_lines: dict[str, list[int]] = {}
    body: list[str] = []
    hidden: list[dict] = []
    if denied is not None:
        body.append(_render("scratch_inconclusive", cause=denied.cause, admission=denied.admission))
    elif output is None:
        body.append(_render("scratch_timeout"))
    else:
        measured_values, kept = [], []
        for raw_line in output[1].splitlines():
            found = _ARENA_LINE.fullmatch(raw_line.strip())
            if found:
                measured_values.append(int(found.group(1)))
            else:
                kept.append(raw_line)
        if len(measured_values) == len(measured_starts):
            heartbeats = dict(zip(measured_starts, measured_values, strict=True))
        for message in _scratch_messages("\n".join(kept)):
            candidate_line = message["line"]
            if candidate_line is not None:
                candidate_line, in_wrapper = engine.map_measured_line(
                    candidate_line, wrapper_start, inserted.count("\n")
                )
                if in_wrapper:
                    if message["severity"] == "error":
                        hidden.append(message)
                    continue
            snippet_line = candidate_line - built["start_line"] + 1 if candidate_line else None
            # Messages before the snippet come from the harness wrapper; sorry warnings are the allowed sorry itself.
            if snippet_line is not None and snippet_line < 1:
                if message["severity"] == "error":
                    hidden.append(message)
                continue
            if (
                message["severity"] == "warning"
                and "declaration uses" in message["message"]
                and "sorry" in message["message"]
            ):
                continue
            messages.append((snippet_line, message))
            if message["severity"] == "info":
                number = message.get("mark") or snippet_line
                command = code_lines[number - 1].strip() if number and number <= len(code_lines) else None
                info_rows.append(
                    _render(
                        "scratch_info_row",
                        line=number if number else "-",
                        command=reply.cell(command, 60) if command else "-",
                        output=reply.cell(message["message"], int(text.numbers().get("scratch_output_chars", 300))),
                    )
                )
            elif message["severity"] == "warning":
                warnings += 1
                warning_lines.setdefault(_warning_text(message["message"]), []).append(snippet_line or 0)
            else:
                errors += 1
                body.append(
                    _render(
                        "scratch_message",
                        line=snippet_line if snippet_line is not None else "-",
                        severity=message["severity"],
                        message=_error_text(message["message"], known, message_chars),
                    )
                )
        for warning, at in warning_lines.items():
            more = f" {_render('scratch_also', lines=', '.join(str(n) for n in at[1:]))}" if len(at) > 1 else ""
            body.append(_render("scratch_message", line=at[0] or "-", severity="warning", message=warning) + more)
        if info_rows:
            body.append(text.template("replies/tools.scratch_info_cols").strip())
            body.extend(info_rows)
        seen_names: list[str] = []
        for _snippet_line, message in messages:
            for name in _UNKNOWN_NAME.findall(message["message"]):
                if name not in seen_names:
                    seen_names.append(name)
        for name in seen_names:
            prefix, siblings = search.sibling_names(theorem, name)
            if siblings:
                body.append(_render("scratch_unknown_names", name=name, prefix=prefix, names=", ".join(siblings)))
    spans = [(start, campaign.declaration_end(code_lines, start)) for start in declarations]
    body_total = sum(_body_tokens("\n".join(code_lines[start - 1 : end])) for start, end in spans)
    if measured_starts and output is not None:
        from arena.scoring import reference as scoring_reference

        price_rates = rates(*scoring_reference(theorem), len(engine.versions(row)))
        for start, end in spans:
            hb = heartbeats.get(start)
            if hb is None:
                continue
            tokens = _body_tokens("\n".join(code_lines[start - 1 : end]))
            points = tokens * price_rates["points_per_token"] + hb / 1000 * price_rates["points_per_1k_hb"]
            body.append(_render("scratch_decl_cost", line=start, tokens=tokens, heartbeats=hb, points=round(points, 1)))
    if output is not None and output[0] != 0 and not errors:
        # Errors outside the snippet (the wrapper) still fail the run; show their text, never a bare count.
        for message in hidden:
            errors += 1
            body.append(
                _render(
                    "scratch_message",
                    line="-",
                    severity="error",
                    message=_error_text(message["message"], known, message_chars),
                )
            )
        if not errors:
            errors = 1
            body.append(_render("scratch_process_failed", returncode=output[0]))
    status = _render("scratch_ok" if output is not None and not errors else "scratch_failed")
    if denied is not None:
        status = _render("scratch_inconclusive_status")
    if declarations:
        lines.append(_render("scratch_result_body", status=status, errors=errors, warnings=warnings, tokens=body_total))
    else:
        lines.append(_render("scratch_result", status=status, errors=errors, warnings=warnings))
    lines.extend(body)
    outcome = (
        "cancelled"
        if _scratch_cancelled(run_id)
        else "inconclusive"
        if denied is not None
        else "timeout"
        if output is None
        else "failure"
        if errors
        else "success"
    )
    lines.append(_render("scratch_experiment", experiment=experiment_id, outcome=outcome))
    lines.append(_render("scratch_not_promoted", reason=_nonpromotion_reason(code)))
    raw = None if output is None else output[1]
    experiments.finish(
        run_id,
        experiment_id,
        code=code,
        digest=digest,
        outcome=outcome,
        raw=raw,
        rendered=lines,
        elapsed_ms=experiments.elapsed_since(started),
        input_ref=accepted["input_ref"],
        context=context,
        promotion={"state": "not_promoted", "reason": _nonpromotion_reason(code)},
    )
    item = {
        "ref": experiment_id,
        "ok": True,
        "lines": lines,
        "error": None,
        "repeat": bool(earlier),
        "experiment_id": experiment_id,
        "outcome": outcome,
        "code": code,
        "promotion": {"state": "not_promoted", "reason": _nonpromotion_reason(code)},
        "validity": "not_a_target_candidate",
        "compatibility": "not_checked",
        "cold": "not_checked",
    }
    return reply.reply(facts=facts, items=[item])
