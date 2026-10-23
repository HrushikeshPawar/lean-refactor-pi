"""Operator-facing presentation of a finished `arena run`: the rich summary, and one-line phase notes."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def node_names(directory: Path) -> dict[str, str]:
    """`#N` candidate label to the graph projection's node id (`n7`), as the viewer shows it; {} when unknown."""
    from arena.campaign import events
    from arena.viewer_data import node_labels

    try:
        return node_labels(directory, events(directory))
    except Exception:
        return {}


def candidate_node(directory: Path, candidate_id: str) -> str:
    """The node id of a candidate id (a proof hash), falling back to a short hash."""
    from arena.campaign import events
    from arena.viewer_data import _candidate_labels

    try:
        label = _candidate_labels(events(directory)).get(candidate_id)
        return node_names(directory).get(label or "", label or candidate_id[:8])
    except Exception:
        return candidate_id[:8]


def phase_note(directory: Path, event: dict) -> str | None:
    """A concise human line for a runtime event worth showing; None for the rest (they stay in the ledger)."""
    if event.get("kind") != "phase":
        return None
    phase, status = event.get("phase"), event.get("status")
    seconds = event.get("seconds")
    took = f" in {seconds:.1f} s" if isinstance(seconds, (int, float)) else ""
    if phase == "cold_verify":
        node = candidate_node(directory, event["candidate_id"]) if event.get("candidate_id") else "?"
        if status == "start":
            return f"cold verify {node} started"
        if status == "error":
            return f"cold verify {node}: not confirmed{took} ({str(event.get('error') or 'error')[:80]})"
        return f"cold verify {node}: {'confirmed' if event.get('confirmed') else 'not confirmed'}{took}"
    if phase == "closing_drain":
        if status == "start":
            return "closing drain: finishing queued checks"
        return f"closing drain {'failed' if status == 'error' else 'done'}{took}; {event.get('remaining', 0)} left"
    return None


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def _kv(rows: list[tuple[str, str | Text]]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column()
    for key, value in rows:
        table.add_row(key, value)
    return table


def _result(summary: dict, names: dict[str, str]) -> Panel:
    def name(label: str | None) -> str:
        return names.get(label or "", label or "?")

    answer = summary.get("submission") or {}
    verified = summary["progress"].get("best_verified_candidate")
    best = summary["progress"]["best"]
    rows: list[tuple[str, str | Text]] = []
    if answer.get("candidate"):
        cold = answer.get("verified_by") == "cold compile"
        rows.append(("best node", Text.assemble((name(answer["candidate"]), "bold green"), f"  proxy {answer['proxy']}")))
        rows.append(("size", f"{answer['tokens']} tokens, {answer['heartbeats']} HB"))
        rows.append(("cold verified", Text("yes", style="green") if cold else Text(f"no ({answer.get('verified_by')})", style="yellow")))
    elif verified:
        rows.append(("best node", Text.assemble((name(verified["candidate"]), "bold"), f"  proxy {verified['proxy']}")))
        rows.append(("size", f"{verified['tokens']} tokens, {verified['heartbeats']} HB"))
        rows.append(("cold verified", Text("not yet", style="yellow")))
    else:
        rows.append(("best node", Text("none (the original proof stands)", style="yellow")))
    highs = ", ".join(f"{label} {item['value']} ({name(item['candidate'])})" for label, key in
                      (("tokens", "tokens"), ("HB", "heartbeats"), ("proxy", "proxy")) if (item := best.get(key)))
    if highs:
        rows.append(("axis highs", highs))
    rows.append(("work", f"{summary['evaluations']} evaluations, {summary['probes']} probes; "
                         f"edits {summary['edits']['structural']} structural / {summary['edits']['local']} local"))
    title = f"{summary['run_id']} · {summary['theorem']} · {summary['model']} · stop {summary['stop_reason']}"
    return Panel(_kv(rows), title="Result", subtitle=title, title_align="left", subtitle_align="left", border_style="green")


def _spend(summary: dict, report: dict) -> Panel:
    cost = summary["cost"]
    rows: list[tuple[str, str | Text]] = [
        ("total", f"{_money(cost['spent_usd'])} of ${cost['limit_usd']} (remaining {_money(cost['remaining_usd'])})"),
        ("requests", f"{cost['requests']} ({cost['retries']} retries), {summary['tools']['results']} tool results"),
    ]
    actors = report.get("by_actor") or {}
    if actors:
        rows.append(("by actor", ", ".join(f"{k} {_money(float(v))}" for k, v in sorted(actors.items()))))
    kinds = cost.get("by_turn_type") or {}
    if kinds:
        rows.append(("by category", ", ".join(f"{k} {_money(v['usd'])}" for k, v in sorted(kinds.items(), key=lambda i: -i[1]["usd"]))))
    rows.append(("after best", f"{_money(cost['spent_after_best_usd'])} over {cost['requests_after_best']} requests; "
                               f"bookkeeping+rejected {cost['bookkeeping_and_rejected_pct']}%"))
    if cost["reconciliation"]["gap_usd"]:
        gap = cost["reconciliation"]
        rows.append(("SPEND GAP", Text(f"ledger {_money(gap['ledger_settled_usd'])}, Pi {_money(gap['session_usd'] or 0)}, gap {_money(gap['gap_usd'])}", style="bold red")))
    return Panel(_kv(rows), title="Spend", title_align="left", border_style="cyan")


def _lean_cache(summary: dict) -> Panel:
    lean, cache = summary.get("lean"), summary["cache"]

    def sec(value):
        return "n/a" if value is None else f"{value:.1f}s"

    rows: list[tuple[str, str | Text]] = []
    if lean:
        gate = lean.get("gate")
        rows.append(("lean", Text(f"{lean['checks']} checks, p50 {sec(lean['p50_seconds'])} p95 {sec(lean['p95_seconds'])}, "
                                  f"timeouts {lean['timeouts']} ({round(100 * lean['timeout_rate'])}%), cold path {lean['cold_path']}"
                                  + (f"; gate {gate['verdict']} ({gate['timeout']}s)" if gate else "")
                                  + ("; ALARM" if lean.get("alarm") else ""), style="red" if lean.get("alarm") else "")))
    else:
        rows.append(("lean", "no data"))
    rows.append(("cache", f"hit {cache['reuse_pct']}% (recent 10: {cache['reuse_pct_recent_10']}%), "
                          f"cost savings {cache['savings_pct']}%, alarms {cache['alarms']}"))
    return Panel(_kv(rows), title="Lean and cache", title_align="left", border_style="blue")


def _routes(summary: dict, names: dict[str, str]) -> Panel:
    table = Table(box=None, padding=(0, 2), header_style="dim")
    for column in ("route", "label", "attempts", "best", "goal states", "min holes", "status"):
        table.add_column(column, no_wrap=column != "label", overflow="ellipsis")
    for row in summary.get("routes") or []:
        if not row["attempts"] and not row["original"]:
            continue
        best = f"{names.get(row['best_candidate'], row['best_candidate'])} · {row['best_proxy']}" if row["best_proxy"] is not None else "-"
        status = ", ".join(filter(None, ["original" if row["original"] else "", "explored" if row.get("explored") else "opened",
                                         "credited" if row.get("credited") else "", f"stale {row['stale_streak']}" if row.get("stale_streak") else ""]))
        table.add_row(row["route"], row["label"], str(row["attempts"]), best, str(row.get("depth", 0)),
                      "-" if row.get("min_holes") is None else str(row["min_holes"]), status)
    depth = summary.get("route_progress")
    note = Text("")
    if depth and depth.get("new_state_share") is not None:
        note = Text(f"{round(100 * depth['new_state_share'])}% of attempts reached a goal state new to their route", style="dim")
    return Panel(Group(table, note), title="Routes", title_align="left", border_style="magenta")


def render_run_summary(summary: dict, report: dict, names: dict[str, str]) -> RenderableType:
    errors = summary["tools"]["errors"]
    parts: list[RenderableType] = [_result(summary, names), _spend(summary, report), _lean_cache(summary), _routes(summary, names)]
    if errors:
        parts.append(Text(f"tool errors {summary['tools']['error_total']}: " + ", ".join(f"{k} {v}" for k, v in errors.items()), style="yellow"))
    return Group(*parts)


def print_run_summary(console: Console, directory: Path, summary: dict) -> None:
    console.print(render_run_summary(summary, _json(directory / "cost.json"), node_names(directory)))
