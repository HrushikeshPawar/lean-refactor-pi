"""Replay a journaled run: the exact request the model saw, and the v7 surfaces for that turn."""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from arena.run_control import committed_operation_ids
from arena.traces import expand_journal, post_hook_bytes

ROOT = Path(__file__).resolve().parents[1]
_ADDENDUM = "<addendum>"
_ADDENDUM_END = "</addendum>"
_TOOL_KINDS = {"tool_call", "tool_result"}


class ReplayError(Exception):
    """The run cannot be replayed, or the requested turn or node is not in it."""


@dataclass
class Turn:
    number: int
    request: dict
    rows: list[dict] = field(default_factory=list)


@dataclass
class Run:
    directory: Path
    config: dict
    journal: list[dict]
    ledger: list[dict]
    cost: list[dict]
    turns: list[Turn]
    payloads: dict[str, bytes]


def split_request(payload: object) -> dict:
    """Split an OpenAI chat post-hook payload into the four stored texts.

    `system` is the text of `messages[0]` before `<addendum>`, `skill` the text between the addendum
    markers, `packet` the first user message, `tools` the canonical JSON of `tools`. A payload that
    does not match returns the missing parts as empty strings. `messages` is returned unchanged.
    """
    if not isinstance(payload, dict):
        return {"system": "", "skill": "", "tools": "", "packet": "", "messages": []}
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []
    system, skill = "", ""
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        system, skill = _split_tags(_block_text(messages[0].get("content")))
    packet = ""
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            packet = _block_text(message.get("content"))
            break
    tools = ""
    if "tools" in payload:
        try:
            tools = json.dumps(payload["tools"], separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            tools = ""
    return {"system": system, "skill": skill, "tools": tools, "packet": packet, "messages": messages}


def load_run(run_id: str, runs_root: Path | None = None) -> Run:
    """Load one journaled run. A directory with no trace journal cannot be replayed."""
    directory = _directory(run_id, runs_root)
    journal_path = directory / "trace-journal.jsonl"
    if not journal_path.is_file():
        raise ReplayError(f"no trace journal: {run_id} predates the journal and cannot be replayed")
    stored = [json.loads(line) for line in journal_path.read_text().splitlines() if line]
    config_path = directory / "run-config.json"
    config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    loaded = Run(
        directory,
        config if isinstance(config, dict) else {},
        expand_journal(stored),
        _jsonl(directory / "ledger.jsonl"),
        _jsonl(directory / "cost-ledger.jsonl"),
        [],
        post_hook_bytes(stored),
    )
    _group(loaded)
    return loaded


def request_parts(turn: Turn, run_directory: Path) -> dict:
    """System, skill, tools and packet for one request.

    Blob hashes win when the row has them. Messages always come from the post-hook payload.
    """
    request = turn.request
    post = request.get("post_hook")
    split = split_request(post) if isinstance(post, dict) else split_request({})
    blobs = request.get("blobs")
    if not isinstance(blobs, dict):
        return split
    parts = {"system": "", "skill": "", "tools": "", "packet": "", "messages": split["messages"]}
    for key in ("system", "skill", "tools", "packet"):
        digest = blobs.get(key)
        if not digest:
            continue
        path = Path(run_directory) / "blobs" / str(digest)
        if not path.is_file():
            raise ReplayError(f"missing blob {digest}")
        parts[key] = path.read_text(encoding="utf-8")
    return parts


def node_turn(run: Run, node: str) -> int:
    """The turn that created `node`.

    A creating ledger row that carries `tool_call_id` joins on that id. Older rows join when the
    journal tool-call window encloses the ledger timestamp. Journal timestamps are milliseconds;
    ledger timestamps are seconds.
    """
    proof_id = _resolve(run.ledger, node)
    event = _creator(run.ledger, proof_id)
    if event is None:
        raise ReplayError(f"node {node} is not in the ledger")
    tool_call = event.get("tool_call_id")
    if tool_call:
        matches = [item.number for item in run.turns if _has_tool_call(item, tool_call)]
        if not matches:
            raise ReplayError(f"node {node} has no tool call {tool_call}")
        return matches[0]
    enclosed = []
    for item in run.turns:
        window = _window(item)
        ts = event.get("ts")
        if (
            window is not None
            and isinstance(ts, (int, float))
            and not isinstance(ts, bool)
            and window[0] <= ts <= window[1]
        ):
            enclosed.append((window[1] - window[0], item.number))
    if not enclosed:
        raise ReplayError(f"node {node} has no enclosing tool call")
    enclosed.sort()
    return enclosed[0][1]


def created_nodes(run: Run, turn: int) -> list[str]:
    """Graph ids of the nodes created in `turn`, earliest first."""
    item = _turn(run, turn)
    created = [event for event in _creators(run.ledger) if _created_in(event, item)]
    created.sort(key=lambda event: event.get("ts") or 0)
    return [_graph_id(run.ledger, _proof_id(event)) for event in created]


def render_turn(run: Run, turn: int, raw: bool = False) -> list[tuple[str, str]]:
    """Operator view of one turn. `raw` is the exact post-hook payload and nothing else."""
    item = _turn(run, turn)
    if raw:
        return [("Payload", raw_payload(run, turn).decode())]
    parts = request_parts(item, run.directory)
    messages = parts["messages"] if isinstance(parts["messages"], list) else []
    response = _response(item)
    sections = [
        ("Run config", json.dumps(run.config, indent=2, ensure_ascii=False)),
        ("System prompt", str(parts["system"])),
        ("Skill", str(parts["skill"])),
        ("Packet", str(parts["packet"])),
        ("Tools", _tool_lines(str(parts["tools"]))),
        ("Messages", "\n\n".join(_format_message(message) for message in messages if isinstance(message, dict))),
    ]
    sections.extend(
        (_result_title(row), _result_body(row))
        for previous in run.turns
        if previous.number < item.number
        for row in previous.rows
        if row.get("kind") == "tool_result"
    )
    sections.extend(
        [
            ("Thinking", _thinking(response)),
            ("Response", _response_text(response)),
            ("Tool calls", _call_lines(item)),
            ("Usage", _usage_text(response)),
        ]
    )
    return sections


def raw_payload(run: Run, turn: int) -> bytes:
    """Exact restored post-hook bytes for one turn, with no extra newline."""
    item = _turn(run, turn)
    request_id = item.request.get("id")
    if isinstance(request_id, str) and request_id in run.payloads:
        return run.payloads[request_id]
    hook = item.request.get("post_hook")
    if isinstance(hook, str):
        return hook.encode()
    if isinstance(hook, dict):
        return json.dumps(hook, ensure_ascii=False, separators=(",", ":")).encode()
    raise ReplayError(f"request {request_id} has no post-hook payload")


def rerender_v7(run: Run, turn: int) -> list[tuple[str, str]]:
    """The v7 surfaces for this turn, in `V7_SECTIONS` order. A section that cannot be built is empty."""
    _turn(run, turn)
    return [render(run, turn) for render in V7_SECTIONS.values()]


class IndexRow(TypedDict):
    turn: int
    ts: float | None
    tools: list[str]
    settled_usd: float | None


def index_rows(run: Run) -> list[IndexRow]:
    """One row per turn: number, request time (epoch seconds), tools called, settled cost."""
    rows: list[IndexRow] = []
    for item in run.turns:
        response = _response(item)
        rows.append(
            {
                "turn": item.number,
                "ts": _request_seconds(item),
                "tools": [str(row.get("name") or "") for row in item.rows if row.get("kind") == "tool_call"],
                "settled_usd": None if response is None else response.get("settled_usd"),
            }
        )
    return rows


def format_index(run: Run) -> str:
    """One line per turn: number, request time (ISO 8601 UTC), tools called, settled cost."""
    lines = []
    for row in index_rows(run):
        seconds = row["ts"]
        clock = "-" if seconds is None else datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        price = "-" if row["settled_usd"] is None else str(row["settled_usd"])
        lines.append(f"{row['turn']} {clock} {','.join(row['tools']) or '-'} {price}")
    return "\n".join(lines)


def _packet_body(run: Run, turn: int) -> str:
    del turn
    theorem = run.config.get("theorem")
    if not isinstance(theorem, str) or not theorem:
        return ""
    from arena.context import render_packet

    return render_packet(theorem, cache_only=True)


def _nodes_body(run: Run, turn: int) -> str:
    from arena.graph import Graph

    item = _turn(run, turn)
    history = _history_before(run, item)
    graph = Graph.from_history(
        history, _proof_reader(run.directory), committed_operations=committed_operation_ids(run.directory)
    )
    ids = {node.proof_id: node.id for node in graph.nodes}
    evaluated = {event.get("candidate_id") for event in history if event.get("kind") == "evaluation"}
    lines = []
    for node in graph.nodes:
        status, tokens, heartbeats, score = node.status, node.tokens, node.heartbeats, node.score
        passed = sum(1 for value in node.versions.values() if value)
        compat = f"{passed}/{len(node.versions)}"
        if node.origin == "reference" and node.proof_id not in evaluated:
            # The ledger never evaluates the pinned original, so the graph's `broken` only means "no
            # result". Show that, with the published denominators the score is measured against.
            status, compat = "unevaluated", "-"
            published = _published_reference(run.config.get("theorem") or _theorem(history))
            if published is not None:
                from arena.scoring import REFERENCE_SCORE

                (tokens, heartbeats), score = published, REFERENCE_SCORE
        parents = ",".join(ids.get(parent, parent) for parent in _parents(history, node.proof_id, node.edge))
        lines.append(
            f"{node.id} {status} tokens={_shown(tokens)} heartbeats={_shown(heartbeats)} "
            f"compat={compat} score={_shown(score)} parent={parents or '-'}"
        )
    return "\n".join(lines)


def _map_body(run: Run, turn: int) -> str:
    from arena.campaign import map_view_from
    from arena.reply import _map_lines

    history = _history_before(run, _turn(run, turn))
    if not history:
        return ""
    return "\n".join(_map_lines(map_view_from(history, run.directory)))


def _theorem(history: list[dict]) -> str:
    return str(history[0].get("theorem") or "") if history else ""


def _published_reference(theorem: object) -> tuple[int, int] | None:
    if not isinstance(theorem, str) or not theorem:
        return None
    from arena.scoring import reference

    try:
        return reference(theorem)
    except Exception:
        # Unknown rows (fixtures, imported runs) have no published denominators; the row still shows.
        return None


# The v7 finish tool description as the model saw it. Pi no longer offers finish; replay keeps showing it for old runs.
_V7_FINISH_DESCRIPTION = (  # not-model-facing
    "End the run. Returns the archive and the points left per axis. "
    "Offered when at most {pct}% of the spend limit remains."
)


def _tools_body(run: Run, turn: int) -> str:
    from arena import text

    lines = [f"{name}: {text.render(f'tools/{name}.description')}" for name in ("compile", "goal", "search", "read")]
    if _finish_open(run, _turn(run, turn)):
        lines.append(f"finish: {_V7_FINISH_DESCRIPTION.format(pct=text.numbers()['finish_remaining_pct'])}")
    return "\n".join(lines)


def _safe(title: str, build: Callable[[Run, int], str]) -> Callable[[Run, int], tuple[str, str]]:
    def render(run: Run, turn: int) -> tuple[str, str]:
        try:
            return title, build(run, turn)
        except Exception:
            return title, ""

    return render


# `map` is re-rendered for every turn; live, the map is only delivered when its hash changed.
# `tools` is the D42 list: finish is absent until the final tenth of the spend limit, so a v6 tool
# list is not shown here.
V7_SECTIONS: dict[str, Callable[[Run, int], tuple[str, str]]] = {
    "packet": _safe("Packet", _packet_body),
    "nodes": _safe("Nodes", _nodes_body),
    "map": _safe("Map (re-rendered at this turn; live, sent only when its hash changed)", _map_body),
    "tools": _safe("Tools", _tools_body),
}


def _group(run: Run) -> None:
    requests = [row for row in run.journal if row.get("kind") == "request"]
    by_number: dict[int, Turn] = {}
    by_id: dict[str, Turn] = {}
    for index, request in enumerate(requests, start=1):
        number = request["turn"] if _number(request.get("turn")) else index
        item = Turn(int(number), request)
        run.turns.append(item)
        by_number[item.number] = item
        if isinstance(request.get("id"), str):
            by_id[request["id"]] = item
    for row in run.journal:
        if row.get("kind") == "request":
            continue
        item = by_number.get(row["turn"]) if _number(row.get("turn")) else None
        if item is None and isinstance(row.get("id"), str):
            item = by_id.get(row["id"])
        if item is not None:
            item.rows.append(row)


def _directory(run_id: str, runs_root: Path | None) -> Path:
    direct = Path(run_id)
    if direct.is_dir():
        return direct
    if runs_root is not None and (runs_root / run_id).is_dir():
        return runs_root / run_id
    for candidate in (ROOT / run_id, ROOT / "runs" / "pi-budget" / run_id):
        if candidate.is_dir():
            return candidate
    return direct


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _split_tags(text: str) -> tuple[str, str]:
    start = text.find(_ADDENDUM)
    if start < 0:
        return text, ""
    end = text.find(_ADDENDUM_END, start + len(_ADDENDUM))
    skill = text[start + len(_ADDENDUM) : end] if end >= 0 else ""
    return text[:start], skill


def _block_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _turn(run: Run, number: int) -> Turn:
    for item in run.turns:
        if item.number == number:
            return item
    raise ReplayError(f"turn {number} is not in the journal")


def _response(item: Turn) -> dict | None:
    for row in item.rows:
        if row.get("kind") == "response":
            return row
    return None


def _request_seconds(item: Turn) -> float | None:
    ts = item.request.get("ts")
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts) / 1000
    return None


def _window(item: Turn) -> tuple[float, float] | None:
    stamps = [
        float(row["ts"]) / 1000
        for row in item.rows
        if row.get("kind") in _TOOL_KINDS
        and isinstance(row.get("ts"), (int, float))
        and not isinstance(row.get("ts"), bool)
    ]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def _has_tool_call(item: Turn, tool_call: object) -> bool:
    return any(row.get("kind") in _TOOL_KINDS and row.get("tool_call_id") == tool_call for row in item.rows)


def _created_in(event: dict, item: Turn) -> bool:
    tool_call = event.get("tool_call_id")
    if tool_call:
        return _has_tool_call(item, tool_call)
    window = _window(item)
    ts = event.get("ts")
    return bool(
        window is not None
        and isinstance(ts, (int, float))
        and not isinstance(ts, bool)
        and window[0] <= ts <= window[1]
    )


def _proof_id(event: dict) -> str:
    if event.get("kind") == "probe":
        return str(event.get("proof_id") or "")
    return str(event.get("candidate_id") or "")


def _creators(history: list[dict]) -> list[dict]:
    seen: set[str] = set()
    found = []
    for event in history:
        if event.get("kind") not in {"candidate", "probe"}:
            continue
        proof_id = _proof_id(event)
        if not proof_id or proof_id in seen:
            continue
        seen.add(proof_id)
        found.append(event)
    return found


def _creator(history: list[dict], proof_id: str) -> dict | None:
    for event in _creators(history):
        if _proof_id(event) == proof_id:
            return event
    return None


def _resolve(history: list[dict], reference: str) -> str:
    from arena.campaign import resolve_node_ref

    try:
        return resolve_node_ref(history, reference)
    except ValueError:
        raise ReplayError(f"node {reference} is not in the ledger") from None


def _graph_id(history: list[dict], proof_id: str) -> str:
    from arena.campaign import _graph_node_id

    try:
        return _graph_node_id(history, proof_id)
    except KeyError:
        raise ReplayError(f"node {proof_id} is not in the ledger") from None


def _history_before(run: Run, item: Turn) -> list[dict]:
    cutoff = _request_seconds(item)
    if cutoff is None:
        return []
    return [
        event
        for event in run.ledger
        if isinstance(event.get("ts"), (int, float)) and not isinstance(event.get("ts"), bool) and event["ts"] < cutoff
    ]


def _parents(history: list[dict], proof_id: str, edge: dict | None) -> list[str]:
    if isinstance(edge, dict) and isinstance(edge.get("from"), list) and edge["from"]:
        return [str(parent) for parent in edge["from"]]
    for event in history:
        if event.get("kind") == "candidate" and event.get("candidate_id") == proof_id:
            parents = event.get("parents") or []
            return [str(parent) for parent in parents] if isinstance(parents, list) else []
        if event.get("kind") == "probe" and event.get("proof_id") == proof_id:
            parent = event.get("parent")
            if parent:
                return [str(parent)]
            parents = event.get("parents") or []
            return [str(parent) for parent in parents] if isinstance(parents, list) else []
    return []


def _proof_reader(directory: Path) -> Callable[[str], str | None]:
    def read(ident: str) -> str | None:
        path = directory / "proofs" / f"{ident}.lean"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    return read


def _limit_usd(config: dict) -> float | None:
    for key in ("limit_usd", "soft_cap_usd", "hard_cap_usd"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if number > 0:
            return number
    return None


def _spent_before(run: Run, item: Turn) -> float:
    request_ts = item.request.get("ts")
    request_id = item.request.get("id")
    chosen = []
    for row in run.cost:
        if row.get("kind") != "settle":
            continue
        if request_id is not None and row.get("id") == request_id:
            continue
        ts = row.get("ts")
        if (
            isinstance(request_ts, (int, float))
            and not isinstance(request_ts, bool)
            and isinstance(ts, (int, float))
            and not isinstance(ts, bool)
            and ts >= request_ts
        ):
            continue
        chosen.append(row)
    totals = [
        row
        for row in chosen
        if isinstance(row.get("spent_usd"), (int, float)) and not isinstance(row.get("spent_usd"), bool)
    ]
    if totals:
        last = max(totals, key=lambda row: row.get("ts") or 0)
        return float(last["spent_usd"])
    return sum(
        float(row["usd"])
        for row in chosen
        if isinstance(row.get("usd"), (int, float)) and not isinstance(row.get("usd"), bool)
    )


def _finish_open(run: Run, item: Turn) -> bool:
    from arena import text

    limit = _limit_usd(run.config)
    if limit is None:
        return False
    remaining = max(0.0, limit - _spent_before(run, item)) / limit
    fraction = float(text.numbers()["finish_remaining_pct"]) / 100
    return remaining <= fraction + 1e-12


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _shown(value: object) -> str:
    return "-" if value is None else str(value)


def _first_sentence(text: str) -> str:
    stripped = text.strip()
    match = re.search(r".+?\.", stripped)
    return match.group(0) if match else stripped


def _tool_lines(tools: str) -> str:
    if not tools:
        return ""
    try:
        items = json.loads(tools)
    except json.JSONDecodeError:
        return ""
    if not isinstance(items, list):
        return ""
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else item
        name = str(function.get("name") or "")
        sentence = _first_sentence(str(function.get("description") or ""))
        lines.append(f"{name}: {sentence}" if sentence else name)
    return "\n".join(lines)


def _format_message(message: dict) -> str:
    lines = [str(message.get("role") or "")]
    text = _block_text(message.get("content"))
    if text:
        lines.append(text)
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        lines.append(reasoning)
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = function.get("name") or call.get("name") or ""
        arguments = function.get("arguments")
        if arguments is None:
            arguments = call.get("arguments")
        rendered = (
            arguments
            if isinstance(arguments, str)
            else json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        )
        lines.append(f"{name} {rendered}")
    return "\n".join(lines)


def _result_title(row: dict) -> str:
    name = row.get("name") or ""
    return f"Tool result {name}".strip()


def _delivered(row: dict) -> str:
    result = row.get("result")
    if isinstance(result, dict):
        text = _block_text(result.get("content"))
        if text:
            return text
    base = row.get("delivered_text") or ""
    footer = row.get("footer") or ""
    if footer:
        return f"{base}\n{footer}" if base else str(footer)
    return str(base)


def _result_body(row: dict) -> str:
    delivered = _delivered(row)
    if not row.get("trimmed"):
        return delivered
    original = str(row.get("text") or "")
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(), delivered.splitlines(), fromfile="untrimmed", tofile="delivered", lineterm=""
        )
    )
    return f"{delivered}\n{diff}" if diff else delivered


def _thinking(response: dict | None) -> str:
    if not response:
        return ""
    parts = [
        str(block.get("thinking") or "")
        for block in response.get("content") or []
        if isinstance(block, dict) and block.get("type") == "thinking" and block.get("thinking")
    ]
    return "\n".join(parts)


def _response_text(response: dict | None) -> str:
    if not response:
        return ""
    text = response.get("text")
    if isinstance(text, str) and text:
        return text
    parts = [
        str(block.get("text") or "")
        for block in response.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    ]
    return "\n".join(parts)


def _call_lines(item: Turn) -> str:
    lines = []
    for row in item.rows:
        if row.get("kind") != "tool_call":
            continue
        lines.append(
            f"{row.get('name') or ''} {json.dumps(row.get('args'), ensure_ascii=False, separators=(',', ':'))}"
        )
    return "\n".join(lines)


def _usage_text(response: dict | None) -> str:
    if not response:
        return ""
    usage = response.get("usage")
    rendered = json.dumps(usage, ensure_ascii=False, separators=(",", ":")) if usage is not None else ""
    cost = response.get("settled_usd")
    cost_line = f"settled_usd={cost}"
    return f"{rendered}\n{cost_line}" if rendered else cost_line
