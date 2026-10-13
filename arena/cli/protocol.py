#!/usr/bin/env python3
"""JSON interface between the Pi extension and one persistent Arena campaign.

Every failure is one line of JSON: `{"ok": false, "error": "..."}`.
"""

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from arena.campaign import (
    autocheck,
    candidate,
    compile_operation,
    declarations,
    evaluate_request,
    find,
    frontier,
    init,
    map_view,
    price_table,
    probe,
    probe_batch,
    profile_request,
    quote,
    record_idea,
    run_dir,
    set_decision,
    source_range,
    state,
    submission,
    write_state,
)
from arena.memory import memory

ACTIONS = (
    "init",
    "evaluate",
    "probe",
    "operation",
    "idea",
    "frontier",
    "candidate",
    "decision",
    "source",
    "declarations",
    "find",
    "profile",
    "prices",
    "quote",
    "autocheck",
    "state",
    "map",
    "submission",
    "memory",
)


def run(args: SimpleNamespace) -> dict:
    if args.action == "init":
        return init(args.theorem, args.run_id)
    if args.action == "evaluate":
        proof = args.proof_file.read_text() if args.proof_file else None
        return evaluate_request(
            args.theorem,
            args.run_id,
            proof,
            args.mode,
            args.parent,
            args.hypothesis,
            args.idea_id,
            args.candidate,
            args.from_probe,
        )
    if args.action == "probe":
        parent = args.parent[0] if args.parent else None
        if args.draft_file:
            if args.proof_file:
                raise ValueError("Use proof-file or draft-file, not both")
            return probe_batch(
                args.theorem, args.run_id, [path.read_text() for path in args.draft_file], args.idea_id, parent
            )
        if args.proof_file:
            return probe(args.theorem, args.run_id, args.proof_file.read_text(), args.idea_id, parent)
        raise ValueError("Pass proof-file or one to four draft-file values")
    if args.action == "operation":
        if not args.operation:
            raise ValueError("Pass --operation with a JSON object")
        return compile_operation(
            args.theorem,
            args.run_id,
            json.loads(args.operation),
            args.mode,
            args.idea_id,
        )
    if args.action == "idea":
        return record_idea(
            args.run_id,
            args.title,
            args.hypothesis,
            args.region,
            json.loads(args.expected_effect) if args.expected_effect else None,
            args.idea_id,
            args.status,
            args.reason,
        )
    if args.action == "frontier":
        return frontier(args.run_id)
    if args.action == "candidate":
        return candidate(args.theorem, args.run_id, args.candidate)
    if args.action == "decision":
        return set_decision(args.run_id, args.candidate, args.decision, args.reason)
    if args.action == "profile":
        return profile_request(
            args.theorem, args.run_id, args.candidate, args.proof_file.read_text() if args.proof_file else None
        )
    if args.action == "prices":
        return price_table(args.theorem, args.run_id, args.candidate)
    if args.action == "quote":
        items = json.loads(args.items) if args.items else None
        if not isinstance(items, list):
            raise ValueError("Pass --items with a JSON list of strings")
        against = json.loads(args.against) if args.against else None
        return quote(args.theorem, args.run_id, items, against)
    if args.action == "autocheck":
        return autocheck(args.theorem, args.run_id, args.max_seconds)
    if args.action == "state":
        return state(args.run_id)
    if args.action == "map":
        return map_view(args.run_id)
    if args.action == "memory":
        return memory(args.run_id, args.spent_usd, args.cap_usd)
    if args.action == "submission":
        return submission(args.run_id)
    if args.action == "source":
        return source_range(args.theorem, args.handle, args.first, args.last)
    if args.action == "declarations":
        return declarations(args.theorem, json.loads(args.items) if args.items else None, args.cursor)
    if args.action == "find":
        return find(args.theorem, json.loads(args.queries), args.limit)
    raise ValueError(f"Unsupported action: {args.action}")


def publish_state(run_id: str) -> None:
    """Refresh state.json after every action; it is derived data, so failures are ignored."""
    try:
        if (run_dir(run_id) / "ledger.jsonl").exists():
            write_state(run_id)
    except Exception:
        pass


@dataclass(frozen=True)
class ProtocolOptions:
    action: str
    theorem: str
    run_id: str
    proof_file: Path | None = None
    draft_file: list[Path] = field(default_factory=list)
    mode: Literal["fast", "full"] = "fast"
    parent: list[str] = field(default_factory=list)
    hypothesis: str = ""
    idea_id: str | None = None
    candidate: str | None = None
    from_probe: str | None = None
    operation: str | None = None
    handle: str | None = None
    first: int | None = None
    last: int | None = None
    items: str | None = None
    against: str | None = None
    queries: str | None = None
    cursor: str | None = None
    limit: int = 20
    decision: Literal["pursue", "park"] | None = None
    reason: str = ""
    title: str | None = None
    region: str | None = None
    expected_effect: str | None = None
    status: str | None = None
    max_seconds: float | None = None
    spent_usd: float | None = None
    cap_usd: float | None = None


def execute(options: ProtocolOptions) -> int:
    args = SimpleNamespace(**asdict(options))
    try:
        if args.action not in ACTIONS:
            raise ValueError(f"unknown action {args.action!r}")
        result = run(args)
        print(json.dumps(result, ensure_ascii=False))
        publish_state(args.run_id)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        message = " ".join(str(error).split()) or type(error).__name__
        print(json.dumps({"ok": False, "error": message[:400]}, ensure_ascii=False))
        return 2
