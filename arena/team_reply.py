"""The orchestrator's view of delegate, jobs, cancel and await_results: short lines with `jobN` and `nN` ids.

The full result stays in the tool's details for the harness; only this text reaches the model."""

from __future__ import annotations

from pathlib import Path

from arena import orchestration, text


def _render(key: str, **values) -> str:
    return text.render(f"replies/team.{key}", **values)


def _anchor(anchor: dict | None) -> str:
    anchor = anchor or {}
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
    if action == "report":
        return _render("report_sent")
    if action == "cancel":
        return _render("cancel_done", job=job(result.get("job_id")), state=result.get("state", "?"))
    if action == "jobs":
        return _jobs(result, directory, job)
    if action == "await_results":
        return _await(result, directory, job)
    raise ValueError(f"no team reply for {action}")


def _jobs(result: dict, directory: Path, job) -> str:
    found = result.get("jobs") or []
    if not found:
        return _render("jobs_none")
    nodes = orchestration.proof_nodes(directory)
    used = sum(1 for item in found if item.get("occupies_slot"))
    lines = [_render("jobs_head", used=used, slots=orchestration._MODEL_SLOTS)]
    for item in found:
        saved = [nodes[f["proof_id"]] for f in item.get("findings") or [] if f.get("proof_id") in nodes]
        listed = ", ".join(_node(node) for node in saved) or _render("nodes_none")
        lines.append(_render("job_line", job=job(item["job_id"]), state=item.get("state", "?"),
                             scope=item.get("scope", "?"), anchor=_anchor(item.get("anchor")), nodes=listed))
        lines.append(_render("job_task", task=" ".join(str(item.get("task", "")).split())))
        report = next((row.get("report") for row in reversed(result.get("events") or [])
                       if row.get("job_id") == item["job_id"] and row.get("report")), None)
        if report:
            lines.append(_render("job_report", report=" ".join(report.split())))
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
        elif kind == "worker_note":
            lines.append(_render("await_note", job=job(event.get("job_id")), note=" ".join(str(event.get("note", "")).split())))
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
    running = [job(item["job_id"]) for item in result.get("jobs") or [] if item.get("state") in orchestration._live_states]
    if running and reason != "no_pending_work":
        lines.append(_render("await_running", jobs=", ".join(running)))
    return "\n".join(lines) or _render("await_no_work")
