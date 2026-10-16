"""Seeded runs: a new run starts from the graph and the history of an earlier, ended run."""

from __future__ import annotations

import fcntl
import hashlib
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
        "golf",
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


def read_seed_proof(name: str, path: Path) -> str:
    """The proof text of a seed file, checked against the row's statement and forbidden constructs; no Lean."""
    try:
        proof = path.read_text().strip()
    except OSError as error:
        raise ValueError(f"seed proof {path} cannot be read: {error}") from error  # not-model-facing
    try:
        campaign.validate_proof(campaign.problem(name), proof)
    except ValueError as error:
        raise ValueError(f"seed proof {path} is not a proof of {name}: {error}") from error  # not-model-facing
    return proof


def _failed_versions(row: dict) -> str:
    """Which toolchains the seed proof failed, with the first error line of each."""
    evaluation = next((e for e in reversed(row["evaluations"]) if e["mode"] == "full"), None)
    compat = (evaluation or {}).get("result", {}).get("compat") or {}
    failed = [
        f"{version}: {_first_line(info.get('error') or info.get('output') or info.get('raw_output') or 'failed')}"
        for version, info in compat.items()
        if not info.get("passed")
    ]
    error = ((evaluation or {}).get("result") or {}).get("error")
    return "; ".join(failed) or str(error or "no evaluation result")


def _first_line(text: str) -> str:
    return next((line.strip() for line in str(text).splitlines() if line.strip()), "failed")[:200]


def start_from_proof(name: str, run_id: str, path: Path) -> dict:
    """Start a run whose `init` row (reference node) is written from a proof file.

    The proof is added as a candidate (origin "seed"), full-checked on every toolchain and cold-verified the way a
    submission is. Only a proof that passes everything becomes focus and current (with a `seeded` row); any failure raises
    ValueError and the run must not start. A proof equal to the reference is no seed (`reference` in the result)."""
    proof = read_seed_proof(name, path)
    directory = campaign.run_dir(run_id)
    history = campaign.events(directory)
    reference = campaign._candidate_ids(history)[0]
    if hashlib.sha256((name + "\0" + proof).encode()).hexdigest() == reference:
        return {"candidate_id": reference, "best_proxy": None, "reference": True}  # nothing to seed from
    result = campaign.record_evaluation(
        name,
        run_id,
        proof,
        "full",
        parents=[reference],
        hypothesis=f"Seed proof {path.name}",  # log: internal record # not-model-facing
        origin="seed",
        materialize_live=False,
        lane="batch",
        trigger="seed",
    )
    row = next(row for row in campaign._summaries(campaign.events(directory)) if row["id"] == result["candidate_id"])
    if not row["verified"] or row["score"] is None:
        raise ValueError(  # not-model-facing
            f"seed proof {path} does not pass every toolchain ({_failed_versions(row)})"
        )
    if campaign._used_session(row):
        cold = campaign.cold_verify(run_id, row)
        if not cold["confirmed"]:
            detail = cold.get("error") or f"passed {cold.get('passed')}, heartbeats {cold.get('cold_heartbeats')}"
            raise ValueError(f"seed proof {path} fails the cold verification ({detail})")  # not-model-facing
    for event in (
        {
            "kind": "seeded",
            "source_proof": str(path),
            "best_proxy": row["score"],
            "best_candidate": row["id"],
            "events": 0,
        },
        {"kind": "focus", "proof_id": row["id"], "reason": "seed"},
        {"kind": "current", "candidate_id": row["id"]},
    ):
        campaign._append(directory, event)
    campaign.materialize(name, run_id, proof)
    campaign.write_state(run_id)
    return {"candidate_id": row["id"], "best_proxy": row["score"]}


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


def prior_work(run_id: str, seed: Path | None = None) -> str:
    """The section added to a seeded run's first prompt: the graph map, then the digest of the earlier session
    (a run seeded from a proof file has no session, so only the map)."""
    shown = reply.map_text(run_id)
    # The model has seen every carried row and node; the first reply must not repeat them as news.
    reply.mark_delivered(run_id, len(campaign.events(campaign.run_dir(run_id))) - 1, shown)
    digest = [] if seed is None else [agent_text.render("messages/prior-work.digest_heading"), session_digest(seed), ""]
    return "\n".join(
        [
            agent_text.render("messages/prior-work.heading"),
            "",
            agent_text.render("messages/prior-work.map_heading"),
            shown,
            "",
            *digest,
        ]
    )
