"""The orchestrator's view of delegate, jobs, cancel and await_results: short lines with `jobN` and `nN` ids.

The full result stays in the tool's details for the harness; only this text reaches the model."""

from __future__ import annotations

from pathlib import Path

from arena import campaign, ideas, orchestration, text


def _render(key: str, **values) -> str:
    return text.render(f"replies/team.{key}", **values)


def _anchor(anchor: dict | None) -> str:
    anchor = anchor or {}
    if isinstance(anchor.get("nodes"), list):
        return _render("anchor_merge", nodes=", ".join(anchor["nodes"]))
    if anchor.get("hole"):
        return _render("anchor_hole", hole=anchor["hole"])
    steps = anchor.get("steps")
    if isinstance(steps, list) and len(steps) == 2:
        return _render("anchor_steps", node=anchor.get("node", "n?"), first=steps[0], last=steps[1])
    return _render("anchor_node", node=anchor.get("node", "n?"))


def _node(node) -> str:
    if node.score is None:
        return _render("node_unscored", node=node.id)
    return _render("node_scored", node=node.id, score=round(node.score, 2))


def _reject(result: dict) -> str:
    if result.get("hint"):
        return _render("reject", hint=result["hint"])
    return _render("reject_bare", reason=result.get("reason") or result.get("category") or "rejected")


def render(action: str, result: dict, directory: Path) -> str:
    if result.get("ok") is False:
        return _reject(result)
    labels = orchestration.job_labels(directory)

    def job(job_id) -> str:
        return labels.get(job_id, str(job_id))

    if action == "delegate":
        state = result.get("state", "?")
        if result.get("messaged") and not result.get("reused"):
            return _render("delegate_messaged", job=job(result.get("job_id")))
        if result.get("reused"):
            return _render("delegate_reused", job=job(result.get("job_id")), state=state)
        if result.get("resumed"):
            return _render("delegate_resumed", job=job(result.get("job_id")), state=state)
        return _render("delegate_started", job=job(result.get("job_id")), state=state,
                       scope=result.get("scope", "?"), anchor=_anchor(result.get("anchor")))
    if action == "card":
        saved = _render("card_saved", version=result.get("version"))
        return f"{saved} {orchestration.card_floor_text(result.get('unmeasured') or [])}" if result.get("floor") else saved
    if action == "cancel":
        return _render("cancel_done", job=job(result.get("job_id")), state=result.get("state", "?"))
    if action == "jobs":
        return _jobs(result, directory, job)
    if action == "await_results":
        return _await(result, directory, job)
    raise ValueError(f"no team reply for {action}")


def _take(sent: dict, kind: str, fingerprint: object, calls: int) -> bool:
    """True when this notice is new for sol: its fingerprint changed. Records the send in `sent` (kind to
    fingerprint and the sol call count at the send)."""
    last = sent.get(kind)
    if last is not None and last["fp"] == fingerprint:
        return False
    sent[kind] = {"fp": fingerprint, "call": calls}
    return True


def notices(directory: Path, bucket: dict, action: str | None) -> tuple[list[str], list[str]]:
    """The merge-started, shorter-node and attempt log notices new for sol since its last tool call, as (kinds, lines).

    The attempt log digest (see ideas.digest) is the delta since sol's previous digest, so each change is said once."""
    sent = bucket.setdefault("notices", {})
    calls = bucket.get("calls", 0)
    kinds: list[str] = []
    lines: list[str] = []
    digest = ideas.lines_for(directory, "sol", bucket)[1]
    if digest:
        kinds.append("ideas")
        lines += digest
    for item in orchestration.merge_jobs(directory):
        if item["creator"] == "harness" and _take(sent, f"merge_started:{item['job_id']}", True, calls):
            kinds.append("merge_started")
            lines.append(_render("merge_started", job=item["label"], nodes=", ".join(item["nodes"])))
    for item in orchestration.token_short(directory):
        if _take(sent, f"token_short:{item['node']}", True, calls):
            if "token_short" not in kinds:
                kinds.append("token_short")
            lines.append(_render("token_short", node=item["node"], saved=item["saved"], best=item["best"],
                                 tokens=item["tokens"], heartbeats=item["heartbeats"],
                                 steps=_costly_steps(directory, item["proof_id"])))
    return kinds, lines


def _costly_steps(directory: Path, proof_id: str) -> str:
    """The node's costliest steps with their tokens and heartbeats, by points at stake."""
    from arena import campaign, reply

    try:
        rows = campaign.step_costs(directory, proof_id)[: text.numbers()["token_short_steps"]]
    except (OSError, ValueError, KeyError):
        rows = []
    return ", ".join(_render("token_short_step", step=row["step"], tokens=reply.shown(row["tokens"]),
                             heartbeats=reply.shown(row["heartbeats"])) for row in rows)


def sol_notices(run_id: str, action: str, result: dict) -> dict:
    """Add sol's new notices to a tool reply's `context`; the text the model reads is unchanged. Workers get no
    notices."""
    from arena import reply

    if reply.current_actor() != "sol" or not isinstance(result, dict):
        return result
    with reply._delivery_lock(run_id):
        state = reply._load(run_id)
        bucket = reply._bucket(state, "sol")
        bucket["calls"] = bucket.get("calls", 0) + 1
        kinds, lines = notices(campaign.run_dir(run_id), bucket, action)
        reply._write_actor(run_id, "sol", bucket, state)
    return reply.add_context(result, [["", *lines]], kinds) if lines else result


def open_requests(directory: Path) -> list[str]:
    """Worker asks and floor claims the orchestrator has not acted on (see orchestration.open_requests), or []."""
    from arena import reply

    requests = orchestration.open_requests(directory)
    if not requests:
        return []
    lines = [_render("open_requests_head")]
    for item in requests:
        if item["ask"]:
            lines.append(_render("open_ask", job=item["job"], version=item["version"],
                                 ask=" ".join(item["ask"].split())))
        if item["floor"]:
            lines.append(_render("open_floor", job=item["job"], version=item["version"]))
        if item.get("unmeasured"):
            lines.append(_render("open_unmeasured", job=item["job"],
                                 names=", ".join(f"`{n}`" for n in item["unmeasured"])))
    floor = next((item for item in requests if item["floor"]), None)
    if floor is not None:
        status = orchestration.island_status(directory, floor["job_id"]) or {}
        route = status.get("route")
        nodes = [node for node in orchestration.proof_nodes(directory).values()
                 if node.status == "closed" and node.route is not None and node.route != route and node.score is not None]
        families = reply._plateau_families(nodes, route)
        axes = reply._plateau_axes(nodes)
        candidates = " ".join(["; ".join(families), *([axes] if axes else [])]).strip()
        options = _render("floor_options", route=route or "its shape", candidates=candidates) if candidates \
            else _render("floor_none")
        lines.append(_render("floor_push", options=options))
    return lines


def _jobs(result: dict, directory: Path, job) -> str:
    found = result.get("jobs") or []
    if not found:
        return _render("jobs_none")
    nodes = orchestration.proof_nodes(directory)
    used = sum(1 for item in found if item.get("occupies_slot"))
    lines = [_render("jobs_head", used=used, slots=orchestration.slot_limit(directory))]
    cards = {row["job_id"]: row for row in orchestration.current_cards(directory).values() if row.get("job_id")}
    for item in found:
        saved = [nodes[f["proof_id"]] for f in item.get("findings") or [] if f.get("proof_id") in nodes]
        scored = [node for node in saved if node.score is not None]
        top = max(scored, key=lambda node: node.score) if scored else (saved[-1] if saved else None)
        listed = _render("nodes_summary", count=len(saved), best=_node(top)) if top else _render("nodes_none")
        if item.get("scope") in ("island", "trim"):
            lines.append(orchestration.island_line(directory, item["job_id"], job(item["job_id"]), item.get("state", "?")))
        else:
            lines.append(_render("job_line", job=job(item["job_id"]), state=item.get("state", "?"),
                                 scope=item.get("scope", "?"), anchor=_anchor(item.get("anchor")), nodes=listed))
        lines.append(_render("job_task", task=" ".join(str(item.get("task", "")).split())))
        ask = orchestration.open_ask(directory, item["job_id"]) if item.get("state") in orchestration._live_states else None
        if ask:
            lines.append(_render("job_open_ask", ask=ask[: text.numbers()["open_ask_chars"]]))
        card = cards.get(item["job_id"])
        shown = [f"{name}: {' '.join(card['fields'][name].split())}" for name in ("focus", "asks")
                 if card and card["fields"].get(name)]
        if shown:
            lines.append(_render("job_card", fields=" | ".join(shown)))
    return "\n".join(lines)


def _saved_summary(result: dict, directory: Path, event: dict, job) -> str:
    snapshot = next((item for item in result.get("jobs") or [] if item.get("job_id") == event.get("job_id")), {})
    nodes = orchestration.proof_nodes(directory)
    saved = [nodes[f["proof_id"]] for f in snapshot.get("findings") or [] if f.get("proof_id") in nodes]
    if not saved:
        return _render("await_cancel_empty", job=job(event.get("job_id")), state=event["state"])
    scored = [node for node in saved if node.score is not None]
    best = _node(max(scored, key=lambda node: node.score)) if scored else _node(saved[0])
    return _render("await_cancel_summary", job=job(event.get("job_id")), state=event["state"],
                   count=len(saved), best=best)


def _await(result: dict, directory: Path, job) -> str:
    reason = result.get("wake_reason")
    if reason == "timeout":
        items = [text.render("replies/await_results.timeout_job", job_id=job(item["job_id"]), state=item["state"],
                             quiet=round((item.get("quiet_s") or 0) / 60))
                 for item in result.get("quiet_jobs") or []]
        return text.render("replies/await_results.timeout", minutes=round(orchestration.await_timeout_s() / 60),
                           jobs="; ".join(items) or "none")
    lines = [_render("await_head")] if result.get("events") else []
    events = result.get("events") or []
    per_node = {}
    for event in events:
        if event.get("type") in ("worker_finding", "verification"):
            per_node.setdefault((event.get("job_id"), event.get("node")), []).append(event)
    done = set()
    for event in events:
        kind = event.get("type")
        node = event.get("node") or "n?"
        if event.get("score") is not None:
            node = _render("node_scored", node=node, score=round(event["score"], 2))
        if kind in ("worker_finding", "verification"):
            key = (event.get("job_id"), event.get("node"))
            if key in done:
                continue
            done.add(key)
            group = per_node[key]
            score = next((e["score"] for e in group if e.get("score") is not None), None)
            if score is not None:
                node = _render("node_scored", node=event.get("node") or "n?", score=round(score, 2))
            checks = [e for e in group if e.get("type") == "verification"]
            saved = any(e.get("type") == "worker_finding" for e in group)
            args = {"job": job(event.get("job_id")), "node": node}
            if saved and checks:
                lines.append(_render("await_finding_checked", state=checks[-1].get("state"), **args))
            elif saved:
                lines.append(_render("await_finding", **args))
            else:
                lines.append(_render("await_check", state=checks[-1].get("state"), **args))
        elif kind == "card":
            lines.append(_render("await_card", job=job(event.get("job_id")), version=event.get("version")))
        elif kind == "run_stop":
            lines.append(_render("await_stopped"))
        elif event.get("state"):
            key = "await_settled_reason" if event.get("reason") else "await_settled"
            lines.append(_render(key, job=job(event.get("job_id")), state=event["state"],
                                 **({"reason": event["reason"]} if event.get("reason") else {})))
            if event["state"] == "cancelled" or (event["state"] == "failed" and not event.get("report")):
                lines.append(_saved_summary(result, directory, event, job))
            elif event.get("report"):
                lines.append(_render("await_report", job=job(event.get("job_id")), report=" ".join(event["report"].split())))
    if reason == "run_stopped" and not any(event.get("type") == "run_stop" for event in result.get("events") or []):
        lines.append(_render("await_stopped"))
    if reason == "no_pending_work":
        lines.append(_render("await_no_work"))
    live = [item for item in result.get("jobs") or [] if item.get("state") in orchestration._live_states]
    if live and reason != "no_pending_work":
        lines.append(_render("await_running", jobs=", ".join(job(item["job_id"]) for item in live)))
        lines += [orchestration.island_line(directory, item["job_id"], job(item["job_id"]), item["state"])
                  for item in live if item.get("scope") in ("island", "trim")]
    return "\n".join(lines) or _render("await_no_work")
