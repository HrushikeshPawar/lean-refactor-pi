"""Harness-built memory for compaction and fresh-context seeds."""

from __future__ import annotations

import re

from arena.run_control import committed_operation_ids
from arena.text import numbers, render


def _read_lines(events: list[dict]) -> list[str]:
    by_handle: dict[str, list[tuple[int, int]]] = {}
    order: list[str] = []
    for event in events:
        if event.get("kind") != "read" or not event.get("handle"):
            continue
        first, last = event.get("first"), event.get("last")
        if not isinstance(first, int) or not isinstance(last, int):
            continue
        handle = event["handle"]
        if handle in order:
            order.remove(handle)
        order.append(handle)
        by_handle.setdefault(handle, []).append((first, last))
    lines = []
    for handle in order:
        spans: list[list[int]] = []
        for first, last in sorted(by_handle[handle]):
            if spans and first <= spans[-1][1] + 1:
                spans[-1][1] = max(last, spans[-1][1])
            else:
                spans.append([first, last])
        lines.append(
            render("messages/compaction-memory.read", handle=handle, ranges=", ".join(f"{a}-{b}" for a, b in spans))
        )
    return lines[-int(numbers()["memory_read_entries"]) :]


def memory_text(state: dict, seed: bool = False) -> str:
    """Format only the supplied graph and provenance state."""
    best = state.get("best") or {}
    proof = best.get("proof", "")
    header = "seed_header" if seed else "compaction_header"
    lines = [render(f"messages/compaction-memory.{header}")]
    if best:
        lines.append(render("messages/compaction-memory.best", node=best["id"], price=best["price"], proof=proof))
    else:
        lines.append(render("messages/compaction-memory.no_best"))
    lines.append(render("messages/compaction-memory.map_heading"))
    lines.extend(state.get("map", []))
    used = [
        row
        for row in state.get("library", [])
        if re.search(r"(?<![\w'.])" + re.escape(row["name"]) + r"(?![\w'.])", proof)
    ][: int(numbers()["memory_library_lines"])]
    lines.append(render("messages/compaction-memory.library_heading"))
    lines.extend(
        render(
            "messages/compaction-memory.library", handle=row["handle"], module=row["module"], signature=row["signature"]
        )
        for row in used
    )
    lines.append(render("messages/compaction-memory.read_heading"))
    lines.extend(_read_lines(state.get("reads", [])))
    lines.append(render("messages/compaction-memory.holes_heading"))
    lines.extend(
        render("messages/compaction-memory.hole", hole=row["hole"], goal=row.get("goal") or "n/a")
        for row in state.get("holes", [])
    )
    strategy = state.get("strategy")
    if strategy:
        lines.append(render("messages/compaction-memory.strategy_heading"))
        lines.append(render("messages/compaction-memory.strategy", text=strategy))
    else:
        lines.append(render("messages/compaction-memory.no_strategy"))
    lines.append(render("messages/compaction-memory.jobs_heading"))
    lines.extend(
        render("messages/compaction-memory.job", job_id=row["job_id"], state=row["state"])
        for row in state.get("jobs", [])
    )
    lines.append(render("messages/compaction-memory.focus_heading"))
    lines.extend(
        render("messages/compaction-memory.focus", actor=actor, proof=proof)
        for actor, proof in state.get("focus", [])
    )
    lines.append(render("messages/compaction-memory.findings_heading"))
    for row in state.get("findings", []):
        if row.get("hypothesis"):
            lines.append(
                render(
                    "messages/compaction-memory.note",
                    actor=row["actor"],
                    text=row["text"],
                    hypothesis=row["hypothesis"],
                    ref=row["ref"],
                )
            )
        else:
            lines.append(
                render("messages/compaction-memory.finding", actor=row["actor"], text=row["text"], ref=row["ref"])
            )
    lines.append(render("messages/compaction-memory.evidence_heading"))
    lines.extend(
        render("messages/compaction-memory.evidence", kind=row["kind"], ref=row["ref"])
        for row in state.get("evidence", [])
    )
    return "\n".join(lines)


_FAILED_OUTCOMES = frozenset(
    {"failure", "timeout", "cancelled", "run_stopped", "dependency_missing", "processing_error", "recorded"}
)


def _event_ref(event: dict) -> str | None:
    for key in ("event_id", "experiment_id", "operation_id"):
        identity = event.get(key)
        if isinstance(identity, str) and identity:
            return identity
    return None


def _finding(event: dict, ref: str, text: str, hypothesis: str | None = None) -> dict | None:
    actor = event.get("actor_id")
    if not isinstance(actor, str) or not actor or not text:
        return None
    row = {"actor": actor, "text": text, "ref": ref}
    if hypothesis:
        row["hypothesis"] = hypothesis
    return row


def _recovery(history: list[dict], jobs: list[dict], focus: list[tuple[str, str]]) -> dict:
    """References into the stored history. This projection does not write or start work."""
    from arena.campaign import current_strategy

    evidence = []
    findings = []
    for event in history:
        kind = event.get("kind")
        ref = _event_ref(event)
        if kind in ("derivation", "attempt") and ref:
            evidence.append({"kind": kind, "ref": ref})
        elif kind == "scratch" and event.get("phase") == "outcome" and ref:
            outcome = event.get("outcome")
            promotion = event.get("promotion") if isinstance(event.get("promotion"), dict) else {}
            failed = outcome in _FAILED_OUTCOMES and promotion.get("state") != "promoted"
            if failed:
                evidence.append({"kind": "experiment", "ref": event.get("experiment_id") or ref})
                reason = promotion.get("reason") or event.get("diagnostic") or outcome
                row = _finding(
                    event,
                    event.get("experiment_id") or ref,
                    render("messages/compaction-memory.failed_experiment", outcome=str(outcome), reason=str(reason)),
                )
                if row:
                    findings.append(row)
        elif kind == "observation" and ref:
            hypothesis = event.get("hypothesis_ref")
            row = _finding(event, ref, event.get("text") or "", hypothesis if isinstance(hypothesis, str) else None)
            if row:
                findings.append(row)
        elif kind == "candidate" and ref and isinstance(event.get("hypothesis"), str) and event["hypothesis"]:
            row = _finding(event, ref, event["hypothesis"], event.get("hypothesis_ref"))
            if row:
                findings.append(row)
    return {
        "strategy": current_strategy(history),
        "jobs": [{"job_id": job["job_id"], "state": job["state"]} for job in jobs],
        "focus": focus,
        "findings": findings,
        "evidence": evidence,
    }


def original_evidence(run_id: str, ref: str) -> dict | None:
    """The stored record or artifact named by a summary reference. The summary is not a substitute."""
    from arena import campaign, experiments

    directory = campaign.run_dir(run_id)
    history = campaign.events(directory)
    matches = [event for event in history if event.get("event_id") == ref]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return {"ref": ref, "records": matches}
    experiment = experiments.retrieve(run_id, ref)
    if experiment is not None:
        return experiment
    proof = campaign._proof_reader(directory)(ref)
    if proof is not None:
        return {"kind": "proof", "proof_id": ref, "text": proof}
    return None


def memory(run_id: str, spent_usd: float | None = None, cap_usd: float | None = None) -> dict:
    """Build compaction state from stored run records; spend is shown by the footer."""
    from arena import campaign, context, orchestration, reply
    from arena.graph import Graph

    directory = campaign.run_dir(run_id)
    history = campaign.events(directory)
    graph = Graph.from_history(
        history, campaign._proof_reader(directory), committed_operations=committed_operation_ids(directory)
    )
    theorem = history[0].get("theorem") if history else None
    graph_map = campaign.map_view(run_id) if theorem else {"best": None, "open": []}
    best_id = (graph_map.get("best") or {}).get("node")
    best_node = next((node for node in graph.nodes if node.id == best_id), None)
    best = None
    if best_node:
        theorem = history[0]["theorem"]
        # The best node's step rows and totals, from the same renderer as the packet and the read view.
        best = {
            "id": best_node.id,
            "proof": best_node.proof_text,
            "price": campaign.price_table(theorem, run_id, best_node.id)["text"],
        }
    library: dict[str, dict] = {}
    if history and theorem:
        for row in context.cached_context(history[0]["theorem"]).get("library", [])[: int(numbers()["packet_library"])]:
            if row.get("sig"):
                library[row["name"]] = {
                    "name": row["name"],
                    "handle": f"decl:{row['name']}",
                    "module": row["module"],
                    "signature": row["sig"],
                }
    for event in history:
        if event.get("kind") == "search":
            for row in event.get("hits", []):
                if row.get("name") and row.get("signature"):
                    library[row["name"]] = {
                        "name": row["name"],
                        "handle": row["handle"],
                        "module": row["module"],
                        "signature": row["signature"],
                    }
        elif event.get("kind") == "read" and str(event.get("handle", "")).startswith("decl:"):
            name = event["handle"][5:]
            if name not in library:
                from arena.search import resolve_handle

                row = resolve_handle(history[0]["theorem"], event["handle"])
                if row:
                    library[name] = {
                        "name": name,
                        "handle": event["handle"],
                        "module": row["module"],
                        "signature": row["signature"],
                    }
    state = {
        "best": best,
        # Open holes are listed once, in their own section with their goals, not again in the map.
        "map": reply._map_lines({**graph_map, "open": []}),
        "library": list(library.values()),
        "reads": history,
        "holes": graph_map.get("open", []),
    }
    recovered = _recovery(history, orchestration.jobs(directory)["jobs"], reply.actor_focuses(run_id))
    state.update(recovered)
    return {"ok": True, "text": memory_text(state), "jobs": recovered["jobs"], "evidence": recovered["evidence"]}
