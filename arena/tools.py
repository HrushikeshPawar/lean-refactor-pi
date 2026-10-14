"""Python handlers for the v7 five-tool protocol surface."""

from __future__ import annotations

import difflib
import hashlib
import re

from arena import campaign, engine, graph, reply, salvage, search, text
from arena.prices import snippet_tokens
from arena.steps import parse, split_steps, step_range

TOOL_FORMS = {
    "compile": ["drafts[1..N]", "splice{base,steps,text}", "fill{hole,text}", "merge{base,take}"],
    "goal": ["node+hole", "node+line", "hole:nN.hK", "try:[snippets]"],
    "search": ["queries:[strings]", "kind:name|type|text", "after:prefix"],
    "read": ["handle:decl:<name>", "node:nN", "hole:nN.hK", "view:source|prices|diff|outline|map"],
    "finish": ["{}"],
}


def _history(run_id: str) -> list[dict]:
    return campaign.events(campaign.run_dir(run_id))


def _nodes(run_id: str) -> tuple[list[dict], graph.Graph]:
    history = _history(run_id)
    return history, graph.Graph.from_history(history, campaign._proof_reader(campaign.run_dir(run_id)))


def _node(run_id: str, reference: str):
    history, projection = _nodes(run_id)
    proof_id = campaign.resolve_node_ref(history, reference)
    return next(item for item in projection.nodes if item.proof_id == proof_id)


def _focus_ref(run_id: str) -> str:
    _history_rows, projection = _nodes(run_id)
    node = next((item for item in projection.nodes if item.proof_id == projection.focus), None)
    if node is None:
        raise ValueError("focus")
    return node.id


def _empty_error(tool: str) -> dict:
    valid = {
        "compile": ["drafts", "splice", "fill", "merge", "base", "from", "note", "check"],
        "goal": ["node", "hole", "line", "try"],
        "search": ["queries", "kind", "after"],
        "read": ["handle", "node", "hole", "view", "against"],
        "finish": [],
    }[tool]
    return reply.error_reply("empty_arguments", "{}", valid, TOOL_FORMS[tool])


def _is_empty(request: object, tool: str) -> bool:
    if not isinstance(request, dict):
        return True
    if tool == "finish":
        return False
    keys = {
        "compile": ("drafts", "splice", "fill", "merge", "base", "from", "note", "check"),
        "goal": ("node", "hole", "line", "try"),
        "search": ("queries", "kind", "after"),
        "read": ("handle", "node", "hole", "view", "against"),
        "finish": (),
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
    edge = node.edge or {}
    sources = edge.get("from") or []
    if edge.get("type") == "filled_from" and sources:
        parent = next((item for item in projection.nodes if item.proof_id == sources[0]), None)
        operation = edge.get("operation") or {}
        hole = operation.get("hole", "")
        return _render("filing_fill", node=node.id, parent=parent.id if parent else "n?", hole=hole.split(".")[-1])
    if edge.get("type") == "edited_from" and sources:
        parent = next((item for item in projection.nodes if item.proof_id == sources[0]), None)
        operation = edge.get("operation") or {}
        if operation.get("steps"):
            return _render(
                "filing_splice", node=node.id, parent=parent.id if parent else "n?", steps=operation["steps"]
            )
        return _render("filing_draft", node=node.id, parent=parent.id if parent else "n?")
    if edge.get("type") == "merged_from" and sources:
        parents = ",".join(
            next((item.id for item in projection.nodes if item.proof_id == source), "n?") for source in sources
        )
        return _render("filing_merge", node=node.id, parents=parents)
    if edge.get("type") == "filed_under_focus" and sources:
        parent = next((item for item in projection.nodes if item.proof_id == sources[0]), None)
        return _render("filing_focus", node=node.id, focus=parent.id if parent else "n?")
    return _render("filing_root", node=node.id)


def message_goal(message: str) -> str | None:
    """The goal Lean prints under the first line of a diagnostic (case tag, hypotheses, `⊢`), without the tactic's own report."""
    body: list[str] = []
    for line in message.split("\n")[1:]:
        if line.startswith("["):
            break
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
            checked = campaign.evaluate(name, replacement, "probe")
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
            message_goal(item.get("message", "")) or item.get("goal") or goal_by_line.get(item.get("proof_line"))
        )
        item["id"] = f"{node.id}.e{index}"
        item["line"] = item.get("proof_line")
    return ordered, incomplete


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
    timeout = bool(result.get("timeout") or primary.get("timeout"))
    errors, incomplete = all_errors(name, run_id, node, result)
    if errors:
        errors = reply.deduplicate_diagnostics(run_id, node.id, errors)
    holes = node.holes
    status = "timeout" if timeout else node.status
    lines = [_render("compile_item", node=node.id, filing=filing, status=status)]
    if timeout:
        lines.append(_render("timeout"))
    for item, branches in _branch_groups(errors):
        lines.append(
            _render(
                "error_item",
                id=item["id"],
                line=item.get("line") or "?",
                message=item.get("message", "").splitlines()[0],
            )
        )
        if branches:
            lines.append(_render("error_branches", count=branches))
        if item.get("goal"):
            lines.append(_render("error_goal", goal=item["goal"]))
    lines.extend(
        [
            _render("hole_item", hole=f"{node.id}.h{hole['index']}", line=hole["line"], goal=hole.get("goal") or "n/a")
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
    facts = [_render("errors_incomplete")] if incomplete else []
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
        },
        "facts": facts,
    }


def _focus_proof(run_id: str) -> tuple[str, str]:
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


def compile_tool(theorem: str, run_id: str, request: dict) -> dict:
    valid = ["drafts", "splice", "fill", "merge", "base", "from", "note", "check"]
    if _is_empty(request, "compile"):
        return _empty_error("compile")
    if not isinstance(request, dict):
        return _invalid("bad_arguments", request, valid, TOOL_FORMS["compile"])
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["compile"])
    operations = [key for key in ("drafts", "splice", "fill", "merge") if key in request]
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
            batch = campaign.probe_batch(
                theorem,
                run_id,
                good_drafts,
                note=request.get("note"),
                named_parent=request.get("from"),
            )
            projection = _nodes(run_id)[1]
            for original_index, proof, row in zip(indexes, normalized_drafts, batch.get("drafts", []), strict=False):
                outcome = {key: value for key, value in row.items() if key != "index"}
                proof_id = hashlib.sha256((theorem + "\0" + proof).encode()).hexdigest()
                node = next((item for item in projection.nodes if item.proof_id == proof_id), None)
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
                node = _node(run_id, result["node"])
                item_result = _compile_item(
                    theorem, run_id, node.id, result, _filing_line(node, _nodes(run_id)[1], result)
                )
                item_result["item"]["ref"] = ref
                items.append(item_result["item"])
                facts.extend(item_result["facts"])
                handles.append(node.id)
            except (OSError, KeyError, StopIteration, ValueError, RuntimeError) as error:
                items.append(
                    _item_error(
                        ref,
                        "invalid_operation",
                        error,
                        ["existing node id", "existing hole id", "existing step id"],
                        TOOL_FORMS["compile"],
                    )
                )
    closed_nodes = [item.get("node") for item in items if item.get("status") == "closed"]
    if closed_nodes:
        seconds = float(text.numbers().get("cross_version_wait_seconds", 10))
        campaign.autocheck(theorem, run_id, max_seconds=seconds, kinds=("full",))
    result = reply.reply(facts=facts, items=items, handles=handles)
    return reply.attach_context(run_id, result, include_map=True)


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
        goals = (answer or {}).get("goals") or []
        rendered = (answer or {}).get("rendered") or "\n".join(goals)
        if not rendered:
            rendered = _render("no_goal", line=proof_line)
        items = [
            {
                "ref": "goal",
                "ok": True,
                "lines": [_render("goal_item", node=node.id, line=proof_line, goal=rendered)],
                "error": None,
                "goal": rendered,
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
                items.append(
                    {
                        "ref": f"t{index}",
                        "ok": not item.get("timeout") and item.get("returncode") == 0,
                        "lines": lines,
                        # The verdict line already says how the snippet failed; a second error line would repeat it.
                        "error": None,
                        "tokens": snippet_tokens(snippet),
                        "delta": snippet_tokens(snippet) - snippet_tokens("sorry"),
                        "goals": item.get("goals_after"),
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


def _try_verdict(item: dict) -> str:
    """One snippet's outcome: timed out, its first error, the goals it leaves open, or closed."""
    if item.get("timeout"):
        return _render("try_timeout")
    if item.get("returncode") != 0:
        output = str(item.get("output") or "")
        found = re.search(r"\berror: (.*)", output)
        if found:
            rest = output[found.start(1) :].splitlines()
            message = " ".join(
                line.strip() for line in rest[:2] if line.strip() and not re.match(r"\S+:\d+:\d+: ", line)
            )
            return _render("try_error", message=message or found.group(1).strip())
        return _render("try_error", message=output.strip().splitlines()[0] if output.strip() else "-")
    goals = str(item.get("goals_after") or "")
    count = len(re.findall(r"^⊢", goals, re.M))
    if goals.strip():
        return _render("try_open", count=count or 1)
    return _render("try_closed")


def search_tool(theorem: str, run_id: str, request: dict) -> dict:
    if _is_empty(request, "search"):
        return _empty_error("search")
    queries = request.get("queries")
    if not isinstance(queries, list):
        return _invalid("bad_queries", queries, ["list of strings"], TOOL_FORMS["search"])
    valid = ["queries", "kind", "after"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["search"])
    kind = request.get("kind", "name")
    string_queries = [(index, query) for index, query in enumerate(queries) if isinstance(query, str)]
    found = search.search(theorem, [query for _, query in string_queries], kind=kind, after=request.get("after"))
    by_index = dict(zip((index for index, _ in string_queries), found.get("queries", []), strict=False))
    items, handles = [], []
    for index, query in enumerate(queries):
        if index not in by_index:
            items.append(_item_error(f"q{index + 1}", "invalid_query", query, ["string"], TOOL_FORMS["search"]))
            continue
        row = by_index[index]
        query = row.get("query", "")
        error = row.get("error")
        if error:
            suggestions = error.get("suggestions") or row.get("suggestions") or []
            items.append(
                _item_error(
                    str(query),
                    error.get("code", "search_error"),
                    error.get("input", query),
                    error.get("valid", ["nonempty query"]),
                    TOOL_FORMS["search"],
                    [
                        _render(
                            "search_miss",
                            query=query,
                            reason=error.get("code", "not found"),
                            suggestions=", ".join(suggestions) or "none",
                        )
                    ],
                )
            )
            continue
        lines = []
        for hit in row.get("hits", []):
            handle = hit.get("handle") or f"decl:{hit.get('name', '')}"
            handles.append(handle)
            lines.append(
                _render(
                    "search_hit_unplaced" if hit.get("line") is None else "search_hit",
                    handle=handle,
                    signature=hit.get("signature", ""),
                    module=hit.get("module", ""),
                    why=hit.get("why", ""),
                    **({} if hit.get("line") is None else {"line": hit["line"]}),
                )
            )
        suggestions = row.get("suggestions") or []
        if not lines:
            lines.append(
                _render(
                    "search_miss",
                    query=query,
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


def _decl_read(theorem: str, run_id: str, handle: str) -> dict:
    match = re.fullmatch(r"(decl:[^:\s]+)(?::([1-9][0-9]*)-([1-9][0-9]*))?", handle)
    if not match:
        return _invalid("bad_handle", handle, ["decl:<qualified-name>[:first-last]"], TOOL_FORMS["read"])
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
    start = int(first) if first else resolved.get("line", 1)
    end = int(last) if last else start + int(text.numbers().get("read_source_lines", 400)) - 1
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
            "read_source", source=canonical, first=result.get("first", first or 1), last=result.get("last", last or "?")
        )
    ]
    lines.extend(result.get("text", "").splitlines())
    continuation = result.get("next_first")
    facts = (
        [f"{canonical}:{continuation}-{continuation + int(text.numbers().get('read_source_lines', 400)) - 1}"]
        if continuation
        else []
    )
    return reply.attach_context(
        run_id,
        reply.reply(
            facts=facts, items=[{"ref": canonical, "ok": True, "lines": lines, "error": None, "source": result}]
        ),
        include_map=False,
    )


def read_tool(theorem: str, run_id: str, request: dict) -> dict:
    if _is_empty(request, "read"):
        return _empty_error("read")
    valid = ["handle", "node", "hole", "view", "against"]
    unknown = sorted(set(request) - set(valid))
    if unknown:
        return _invalid("unknown_argument", unknown[0], valid, TOOL_FORMS["read"])
    view = request.get("view", "source")
    if request.get("handle") and view != "source":
        return _invalid("bad_view", view, ["source"], TOOL_FORMS["read"])
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
        except (ValueError, IndexError, StopIteration) as error:
            return _invalid("invalid_hole", error, [], TOOL_FORMS["read"])
    try:
        node = _node(run_id, request["node"])
    except (ValueError, StopIteration):
        return _invalid("unknown_node", request.get("node"), [], TOOL_FORMS["read"])
    projection = _nodes(run_id)[1]
    lines = []
    data = {}
    if view == "source":
        lines = [_render("read_node_source", node=node.id), *node.proof_text.splitlines()]
        data["source"] = node.proof_text
    elif view == "prices":
        price = campaign.price_table(theorem, run_id, node.id)
        # A value not measured yet is stored as None; the model sees "n/a", never Python's None.
        total = {key: "n/a" if value is None else value for key, value in price.get("total", {}).items()}
        lines = [
            _render(
                "read_price_row",
                node=node.id,
                tokens=total.get("tokens", "n/a"),
                heartbeats=total.get("heartbeats", "n/a"),
                versions=total.get("versions", "n/a"),
            )
        ]
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
        steps = node.steps  # carries the recorded step goals; split_steps(proof) would drop them
        holes = node.holes
        # Goals come from the recorded step goals; a step without them shows its lines only.
        lines = []
        for step in steps:
            lines.append(_render("read_step", step=step.id, first=step.first_line, last=step.last_line))
            if step.before:
                lines.append(_render("read_step_before", goal=step.before))
            if step.after:
                lines.append(_render("read_step_after", goal=step.after))
        data["steps"] = [step.__dict__ for step in steps]
        data["holes"] = holes
    elif view == "map":
        result = reply.attach_context(
            run_id,
            reply.reply(items=[{"ref": node.id, "ok": True, "lines": [], "error": None}]),
            include_map=True,
            force_map=True,
        )
        return result
    else:
        return _invalid("bad_view", view, ["source", "prices", "diff", "outline", "map"], TOOL_FORMS["read"])
    return reply.attach_context(
        run_id,
        reply.reply(items=[{"ref": node.id, "ok": True, "lines": lines, "error": None, **data}]),
        include_map=False,
    )


def finish_tool(theorem: str, run_id: str, request: dict | None = None) -> dict:
    if request not in (None, {}):
        return _invalid("bad_arguments", request, [], TOOL_FORMS["finish"])
    history, _projection = _nodes(run_id)
    map_data = campaign.map_view(run_id)
    archive = (
        ", ".join(
            f"{row['letter']}:{row['node']} {'-' if row['score'] is None else row['score']}"
            for row in map_data.get("archive", [])
        )
        or "empty"
    )
    state = campaign.state(run_id)
    baseline = state.get("baseline") or {}
    best = state.get("best") or {}

    def left(axis: str) -> float | str:
        reference = baseline.get(axis)
        value = best.get(axis)
        if not isinstance(reference, (int, float)) or not reference or not isinstance(value, (int, float)):
            return "unknown"
        saved = 100 * (1 - value / reference)
        return round(max(0.0, (100 - saved) / 3), 1)

    compatibility = (
        round(
            max(
                0.0,
                100 * (1 - sum(best.get("versions", {}).values()) / max(1, len(history[0].get("versions") or [1]))) / 3,
            ),
            1,
        )
        if best.get("versions")
        else "unknown"
    )
    facts = [
        _render("finish_archive", archive=archive),
        _render("finish_points", tokens=left("tokens"), heartbeats=left("heartbeats"), compatibility=compatibility),
    ][: int(text.numbers().get("finish_points_lines", 4))]
    campaign._append(campaign.run_dir(run_id), {"kind": "finish"})
    return reply.attach_context(run_id, reply.reply(facts=facts, stop=True))
