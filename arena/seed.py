"""Seeded runs: a new run starts from the graph and the history of an earlier, ended run."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from pathlib import Path

from arena import campaign, reply
from arena import text as agent_text

# Ledger rows that belong to the earlier session's own bookkeeping rather than to the graph.
SKIPPED_KINDS = frozenset(
    {
        "init",
        "scratch",
        "search",
        "read",
        "repeat",
        "restart",
        "stall",
        "compaction",
        "cache_alarm",
        "closing_drain",
        "cold_verification",
        "finish",
        "limit",
        "control",
        "seeded",
    }
)
# Ids of the earlier session's tool calls and requests mean nothing in the new session.
DROPPED_FIELDS = ("tool_call_id", "request_id", "turn")
CARRIED_DIRECTORIES = ("proofs", "blobs", "diagnostics")

# The digest never shows a call to this tool: the earlier session's way of ending must not reach the new model.
HIDDEN_TOOL = "finish"

DIGEST_CHARS = 24_000  # the session digest; the most recent turns win when it is trimmed
DIGEST_TEXT_CHARS = 1_200  # one reasoning or text block
DIGEST_ARGUMENT_CHARS = 400  # one tool call's arguments
DIGEST_STRING_CHARS = 160  # one string inside the arguments
DIGEST_OUTCOME_CHARS = 220  # one tool result


def check_seed(seed: Path) -> None:
    """The seed must be an ended run: a summary and a ledger."""
    if not seed.is_dir():
        raise ValueError(f"seed run {seed} is not a directory")  # not-model-facing
    if not (seed / "summary.json").is_file():
        raise ValueError(f"seed run {seed} has no summary.json; it is not finished or stopped")  # not-model-facing
    if not (seed / "ledger.jsonl").is_file():
        raise ValueError(f"seed run {seed} has no ledger.jsonl")  # not-model-facing


def _graph_rows(history: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in event.items() if key not in DROPPED_FIELDS}
        for event in history[1:]
        if event.get("kind") not in SKIPPED_KINDS
    ]


def _append_all(directory: Path, events: list[dict]) -> None:
    """The ledger rows written in one append, keeping each row's own time."""
    data = "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events).encode()
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def carry_over(name: str, run_id: str, seed: Path) -> dict:
    """Copy the seed's graph into a run whose `init` row is already written; return the seed's best."""
    check_seed(seed)
    directory = campaign.run_dir(run_id)
    history = campaign.events(seed)
    if not history or history[0].get("kind") != "init" or history[0].get("theorem") != name:
        raise ValueError(f"seed run {seed} is not a run of {name}")  # not-model-facing
    for folder in CARRIED_DIRECTORIES:
        if (seed / folder).is_dir():
            shutil.copytree(seed / folder, directory / folder, dirs_exist_ok=True)
    rows = _graph_rows(history)
    carried = [*campaign.events(directory), *rows]
    summaries = campaign._summaries(carried)
    best = campaign._best([row for row in summaries if row["verified"]])
    start = best or next((row for row in summaries if row["origin"] == "reference"), summaries[0])
    proof = campaign._proof_reader(directory)(start["id"])
    if proof is None:
        raise ValueError(f"seed run {seed} has no stored proof for its best node")  # not-model-facing
    carried = len(rows)
    rows += [
        {
            "kind": "seeded",
            "source_run": seed.name,
            "best_proxy": best["score"] if best else None,
            "best_candidate": start["id"],
            "events": carried,
        },
        {"kind": "focus", "proof_id": start["id"], "reason": "seed"},
        {"kind": "current", "candidate_id": start["id"]},
    ]
    _append_all(directory, rows)
    campaign.materialize(name, run_id, proof)
    campaign.write_state(run_id)
    return {"best_proxy": start["score"], "events": carried}


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _shorten(value, limit: int = DIGEST_STRING_CHARS):
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, list):
        return [_shorten(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _shorten(item, limit) for key, item in value.items()}
    return value


def _outcome(result: dict) -> str:
    """The first lines of a tool result, minus its section header."""
    body = "\n".join(block.get("text", "") for block in result.get("content") or [] if block.get("type") == "text")
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
    return _clip(" | ".join(lines[:2]), DIGEST_OUTCOME_CHARS)


def _session_rows(seed: Path) -> list[dict]:
    rows = []
    for path in sorted((seed / "session").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") == "message" and isinstance(row.get("message"), dict):
                rows.append(row["message"])
    return rows


def digest_turns(seed: Path) -> list[str]:
    """One block per assistant turn: readable reasoning, text, each call with its arguments and outcome."""
    messages = _session_rows(seed)
    results = {message.get("toolCallId"): message for message in messages if message.get("role") == "toolResult"}
    blocks = []
    for number, message in enumerate((item for item in messages if item.get("role") == "assistant"), 1):
        lines = [agent_text.render("messages/prior-work.turn", number=number)]
        for part in message.get("content") or []:
            kind = part.get("type")
            if kind == "thinking" and (part.get("thinking") or "").strip():
                lines.append(
                    agent_text.render("messages/prior-work.reasoning", text=_clip(part["thinking"], DIGEST_TEXT_CHARS))
                )
            elif kind == "text" and (part.get("text") or "").strip():
                lines.append(agent_text.render("messages/prior-work.said", text=_clip(part["text"], DIGEST_TEXT_CHARS)))
            elif kind == "toolCall" and part.get("name") != HIDDEN_TOOL:
                arguments = json.dumps(_shorten(part.get("arguments") or {}), ensure_ascii=False)
                lines.append(
                    agent_text.render(
                        "messages/prior-work.call",
                        name=part.get("name", ""),
                        arguments=_clip(arguments, DIGEST_ARGUMENT_CHARS),
                    )
                )
                result = results.get(part.get("id"))
                if result is not None:
                    lines.append(agent_text.render("messages/prior-work.result", outcome=_outcome(result)))
        if len(lines) > 1:  # a turn with only unreadable reasoning has nothing to show
            blocks.append("\n".join(lines))
    return blocks


def session_digest(seed: Path, limit: int = DIGEST_CHARS) -> str:
    """The turns that fit `limit` characters, most recent first kept; says how many earlier turns are left out."""
    blocks = digest_turns(seed)
    kept: list[str] = []
    used = 0
    for block in reversed(blocks):
        if kept and used + len(block) + 1 > limit:
            break
        kept.append(block)
        used += len(block) + 1
    kept.reverse()
    omitted = len(blocks) - len(kept)
    head = [agent_text.render("messages/prior-work.omitted", count=omitted)] if omitted else []
    return "\n".join([*head, *kept])


def prior_work(run_id: str, seed: Path) -> str:
    """The section added to a seeded run's first prompt: the graph map, then the digest of the earlier session."""
    shown = reply.map_text(run_id)
    # The model has seen every carried row and node; the first reply must not repeat them as news.
    reply.mark_delivered(run_id, len(campaign.events(campaign.run_dir(run_id))) - 1, shown)
    return "\n".join(
        [
            agent_text.render("messages/prior-work.heading"),
            "",
            agent_text.render("messages/prior-work.map_heading"),
            shown,
            "",
            agent_text.render("messages/prior-work.digest_heading"),
            session_digest(seed),
            "",
        ]
    )
