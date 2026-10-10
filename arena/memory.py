"""Harness-built memory for after a context compaction.

Pi compacts older turns into a model-written summary, which can drop what the run has already found.
The harness therefore restates it from its own ledger: the best verified candidate, the routes tried,
the ideas and how they went, the latest failures and the allowance left. The model writes and maintains
nothing; the text is rebuilt from `frontier` each time and injected once, right after a compaction.
"""

from __future__ import annotations

from arena.routes import routes_text

MAX_IDEAS = 8
MAX_FAILURES = 3


def _metrics(row: dict | None) -> str:
    if not row:
        return "none yet"
    score = (
        f"proxy {row['proxy']} (verified)"
        if row.get("proxy") is not None
        else f"est. proxy {row.get('estimated_proxy')} (not yet verified)"
    )
    return f"{row['candidate']} {score}, {row.get('tokens')} tok, {row.get('heartbeats')} HB"


def _idea(idea: dict) -> str:
    attempts = idea.get("attempts", 0)
    best = idea.get("best")
    outcome = (
        f"best {_metrics(best)}"
        if best
        else (f"last failure {idea['last_failure']}" if idea.get("last_failure") else "no scored proof")
    )
    return f'{idea["id"]} "{idea.get("title", "")}" [{idea.get("status", "?")}]: {attempts} attempt{"s" if attempts != 1 else ""}, {outcome}'


def memory_text(front: dict, spent_usd: float | None = None, cap_usd: float | None = None) -> str:
    """The memory block, a pure function of `frontier` output and the settled spend."""
    best = next((row for row in [front.get("best")] if row), None)
    verified = [row for row in [best] if row and row.get("proxy") is not None]
    lines = [
        "[arena memory] Context was just compacted. This is the harness's own record of the run; "
        "it replaces nothing you must write and needs no reply."
    ]
    lines.append(
        "Best verified candidate: "
        + (
            _metrics(verified[0]) + f"; arena_candidate {verified[0]['candidate']} returns its source."
            if verified
            else "none verified yet" + (f"; leading unverified: {_metrics(best)}" if best else "")
        )
    )
    lines.append("Routes tried (harness fingerprints): " + routes_text(front.get("routes") or []))
    ideas = front.get("ideas") or []
    shown = sorted(ideas, key=lambda idea: (idea.get("status") != "active", -idea.get("attempts", 0)))[:MAX_IDEAS]
    lines.append(
        "Ideas: "
        + ("; ".join(_idea(idea) for idea in shown) if shown else "none recorded")
        + (f" (+{len(ideas) - len(shown)} more)" if len(ideas) > len(shown) else "")
    )
    failures = (front.get("recent_failures") or [])[-MAX_FAILURES:]
    lines.append(
        "Latest failures: "
        + (
            "; ".join(f"{row['ref']} ({row.get('idea_id') or 'no idea'}): {row['error']}" for row in failures)
            if failures
            else "none"
        )
    )
    if front.get("advisory"):
        lines.append(f"Blocker: {front['advisory']}")
    lines.append(
        f"Work so far: {front.get('candidates', 0)} candidates, {front.get('evaluations', 0)} evaluations, {front.get('probes', 0)} probes."
    )
    if spent_usd is not None and cap_usd is not None:
        lines.append(f"Allowance: ${spent_usd:.4f} of ${cap_usd:g} spent, ${max(0.0, cap_usd - spent_usd):.4f} left.")
    return "\n".join(lines)


def memory(run_id: str, spent_usd: float | None = None, cap_usd: float | None = None) -> dict:
    from arena.campaign import frontier

    return {"ok": True, "text": memory_text(frontier(run_id), spent_usd, cap_usd)}
