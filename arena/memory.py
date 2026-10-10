"""Harness-built memory for after a context compaction.

Pi compacts older turns into a model-written summary, which can drop what the run has already found.
The harness therefore restates it from its own ledger: the best verified candidate, the routes tried,
the ideas and how they went, the latest failures and the allowance left. The model writes and maintains
nothing; the text is rebuilt from `frontier` each time and injected once, right after a compaction.
"""

from __future__ import annotations

from arena.routes import routes_text
from arena.text import numbers, render

MAX_IDEAS = int(numbers()["max_ideas"])
MAX_FAILURES = int(numbers()["max_failures"])


def _metrics(row: dict | None) -> str:
    if not row:
        return render("messages/compaction-memory.metrics_none")
    values = {
        "candidate": row["candidate"],
        "proxy": row["proxy"] if row.get("proxy") is not None else row.get("estimated_proxy"),
        "tokens": row.get("tokens"),
        "heartbeats": row.get("heartbeats"),
    }
    key = "metrics_verified" if row.get("proxy") is not None else "metrics_estimated"
    return render(f"messages/compaction-memory.{key}", **values)


def _idea(idea: dict) -> str:
    attempts = idea.get("attempts", 0)
    best = idea.get("best")
    outcome = (
        render("messages/compaction-memory.idea_best", metrics=_metrics(best))
        if best
        else (
            render("messages/compaction-memory.idea_failure", failure=idea["last_failure"])
            if idea.get("last_failure")
            else render("messages/compaction-memory.idea_empty")
        )
    )
    return render(
        "messages/compaction-memory.idea",
        id=idea["id"],
        title=idea.get("title", ""),
        status=idea.get("status", "?"),
        attempts=attempts,
        s="" if attempts == 1 else "s",
        outcome=outcome,
    )


def memory_text(front: dict, spent_usd: float | None = None, cap_usd: float | None = None) -> str:
    """The memory block, a pure function of `frontier` output and the settled spend."""
    best = next((row for row in [front.get("best")] if row), None)
    verified = [row for row in [best] if row and row.get("proxy") is not None]
    lines = [render("messages/compaction-memory.header")]
    if verified:
        best_line = render(
            "messages/compaction-memory.best_verified",
            metrics=_metrics(verified[0]),
            candidate=verified[0]["candidate"],
        )
    else:
        best_line = render("messages/compaction-memory.none_verified")
        if best:
            best_line += render("messages/compaction-memory.leading_unverified", metrics=_metrics(best))
    lines.append(best_line)
    lines.append(render("messages/compaction-memory.routes", routes=routes_text(front.get("routes") or [])))
    ideas = front.get("ideas") or []
    shown = sorted(ideas, key=lambda idea: (idea.get("status") != "active", -idea.get("attempts", 0)))[:MAX_IDEAS]
    lines.append(
        render(
            "messages/compaction-memory.ideas",
            ideas="; ".join(_idea(idea) for idea in shown) if shown else "none recorded",
            more=(
                render("messages/compaction-memory.idea_more", count=len(ideas) - len(shown))
                if len(ideas) > len(shown)
                else ""
            ),
        )
    )
    failures = (front.get("recent_failures") or [])[-MAX_FAILURES:]
    lines.append(
        render(
            "messages/compaction-memory.failures",
            failures=(
                "; ".join(
                    render(
                        "messages/compaction-memory.failure",
                        ref=row["ref"],
                        idea=row.get("idea_id") or "no idea",
                        error=row["error"],
                    )
                    for row in failures
                )
                if failures
                else "none"
            ),
        )
    )
    if front.get("advisory"):
        lines.append(render("messages/compaction-memory.blocker", advisory=front["advisory"]))
    lines.append(
        render(
            "messages/compaction-memory.work",
            candidates=front.get("candidates", 0),
            evaluations=front.get("evaluations", 0),
            probes=front.get("probes", 0),
        )
    )
    if spent_usd is not None and cap_usd is not None:
        lines.append(
            render(
                "messages/compaction-memory.allowance", spent=spent_usd, cap=cap_usd, left=max(0.0, cap_usd - spent_usd)
            )
        )
    return "\n".join(lines)


def memory(run_id: str, spent_usd: float | None = None, cap_usd: float | None = None) -> dict:
    from arena.campaign import frontier

    return {"ok": True, "text": memory_text(frontier(run_id), spent_usd, cap_usd)}
