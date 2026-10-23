"""The orchestrator's plan: each save is a versioned `plan` ledger row that replaces the whole plan.

Validation is strict on shape and on the two standing steps. The lines below are what the orchestrator reads after its
jobs, delegate and await_results replies; the worker packets never carry the plan, so the packet stays fixed for a session.
"""

from __future__ import annotations

from pathlib import Path

from arena import orchestration, run_control, text

KINDS = ("shape", "step", "trim", "merge", "heartbeats", "tokens")
STATUSES = ("open", "running", "done", "failed")
_LIVE = ("open", "running")
_STANDING = ("shape", "merge")
_FIELDS = ("target", "kind", "expect", "cards", "status", "note")


def plan_rows(directory: Path) -> list[dict]:
    """Every saved plan version, oldest first. Row: {type, version, actor_id, best, steps, warnings}."""
    return [row for row in orchestration._history(directory) if row.get("type") == "plan"]


def current_plan(directory: Path) -> dict | None:
    rows = plan_rows(directory)
    return rows[-1] if rows else None


def _normal(step: dict) -> dict | None:
    """The stored form of one step, or None when a required field is missing or not a string."""
    if not isinstance(step, dict) or set(step) - set(_FIELDS):
        return None
    if not all(isinstance(step.get(name), str) and step[name].strip() for name in ("target", "expect")):
        return None
    if step.get("kind") not in KINDS or step.get("status") not in STATUSES:
        return None
    stored = {name: " ".join(str(step[name]).split()) for name in ("target", "kind", "expect", "status")}
    for name in ("cards", "note"):
        if step.get(name):
            stored[name] = " ".join(str(step[name]).split())
    return stored


def _problem(steps: list, previous: dict | None) -> tuple[str, dict] | None:
    """(reply key, values) for a plan that must not be saved, else None."""
    if not isinstance(steps, list) or not steps:
        return ("plan_steps", {})
    if len(steps) > text.numbers()["plan_max_steps"]:
        return ("plan_count", {})
    if not all(_normal(step) for step in steps):
        return ("plan_steps", {})
    stored = [_normal(step) for step in steps]
    if any(step["status"] in _LIVE for step in stored):
        earlier = (previous or {}).get("steps", [])
        for kind in _STANDING:
            kept = any(step["kind"] == kind for step in stored)
            tried = any(step["kind"] == kind and step["status"] in ("done", "failed") for step in earlier)
            if not kept and not tried:
                return ("plan_required", {"kind": kind})
    return None


def _warnings(steps: list[dict]) -> list[str]:
    """Plan facts the orchestrator should fix, shown beside the saved version."""
    return [text.render("replies/team.plan_failed_note", step=step["target"])
            for step in steps if step["status"] == "failed" and not step.get("note")]


def save_plan(directory: Path, *, operation_id: str, run_id: str, actor_id: str, session_id: str, steps: list) -> dict:
    """Validate and commit the whole plan as the next version, or refuse it with a hint."""
    if not operation_id or not run_id or not actor_id or not session_id:
        return orchestration._reject(operation_id, "identity")
    if actor_id != "sol":
        return orchestration._reject(operation_id, "actor", hint="replies/team.plan_actor")
    with run_control.control_lock(directory):
        previous = current_plan(directory)
        problem = _problem(steps, previous)
        if problem is not None:
            key, values = problem
            return {"ok": False, "category": "invalid_input", "reason": key, "operation_id": operation_id,
                    "hint": text.render(f"replies/team.{key}", **values)}
        stored = [_normal(step) for step in steps]
        best = orchestration.run_best(directory)
        version = (previous or {}).get("version", 0) + 1
        warnings = _warnings(stored)
        row = {"type": "plan", "actor_id": actor_id, "version": version, "best": None if best is None else best.id,
               "steps": stored, "warnings": warnings}
        try:
            applied = run_control._apply_locked(
                directory,
                {"operation_id": operation_id, "kind": "plan", "arguments": {"steps": steps}, "run_id": run_id,
                 "actor_id": actor_id, "session_id": session_id},
                lambda ctx: [ctx.append_ledger(row)],
            )
        except run_control.OperationRejected as error:
            return orchestration._reject(operation_id, error.category)
    orchestration._wake()
    return {**applied, "version": version, "warnings": warnings}


def lines(directory: Path) -> list[str]:
    """The plan block (open and running steps) and the nudges that follow it, for await_results and jobs replies."""
    plan = current_plan(directory)
    if plan is None:
        return [text.render("replies/team.plan_missing")]
    best = orchestration.run_best(directory)
    live = [step for step in plan["steps"] if step["status"] in _LIVE]
    out = []
    if live:
        out.append(text.render("replies/team.plan_head", version=plan["version"]))
        out += [text.render("replies/team.plan_step", target=step["target"], kind=step["kind"], expect=step["expect"])
                for step in live]
    shown_best = best.id if best is not None else text.render("replies/team.plan_original")
    if best is not None and plan.get("best") != best.id:
        out.append(text.render("replies/team.plan_stale", node=best.id, was=plan.get("best") or shown_best))
    if not live:
        out.append(text.render("replies/team.plan_empty", node=shown_best))
    return out
