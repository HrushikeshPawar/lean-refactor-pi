"""Harness-built memory for compaction and fresh-context seeds."""

from __future__ import annotations

import re

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
    return "\n".join(lines)


def memory(run_id: str, spent_usd: float | None = None, cap_usd: float | None = None) -> dict:
    """Build compaction state from stored run records; spend is shown by the footer."""
    from arena import campaign, context, reply
    from arena.graph import Graph

    directory = campaign.run_dir(run_id)
    history = campaign.events(directory)
    graph = Graph.from_history(history, campaign._proof_reader(directory))
    graph_map = campaign.map_view(run_id)
    best_id = (graph_map.get("best") or {}).get("node")
    best_node = next((node for node in graph.nodes if node.id == best_id), None)
    best = None
    if best_node:
        theorem = history[0]["theorem"]
        table = campaign.price_table(theorem, run_id, best_node.id)["total"]
        best = {
            "id": best_node.id,
            "proof": best_node.proof_text,
            "price": render(
                "messages/compaction-memory.price",
                tokens=table["tokens"],
                heartbeats=table["heartbeats"],
                versions=table["versions"],
                score=f"{best_node.score:.2f}",
            ),
        }
    library: dict[str, dict] = {}
    if history:
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
        "map": reply._map_lines(graph_map),
        "library": list(library.values()),
        "reads": history,
        "holes": graph_map.get("open", []),
    }
    return {"ok": True, "text": memory_text(state)}
