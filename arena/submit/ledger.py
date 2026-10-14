"""Provenance ledger: every charged call of every contributing run, and the $3 gate."""

from __future__ import annotations

from pathlib import Path

from arena.package import _json, attempts, trace_ids
from arena.replay import ReplayError, load_run, node_turn


def _turn(row: dict) -> int | None:
    """The turn that created the candidate. New runs join on the tool call; older runs use time."""
    if isinstance(row.get("turn"), int) and not isinstance(row.get("turn"), bool):
        return row["turn"]
    directory = row.get("directory")
    graph_id = row.get("graph_id")
    if not directory or not graph_id:
        return None
    path = Path(directory)
    if not (path / "trace-journal.jsonl").is_file():
        return None
    try:
        run = load_run(path.name, path.parent)
        return node_turn(run, graph_id)
    except ReplayError:
        return None


def _settled_usd(spent: dict) -> float:
    """Sum of settle rows. The reconciled session total is reported beside it and is not this sum."""
    return round(sum(float(row.get("usd") or 0) for row in spent.get("settles") or []), 6)


def _calls(run_ids: list[str], runs_root: Path, selected: str | None) -> tuple[list[dict], float]:
    rows, total = [], 0.0
    for run_id in run_ids:
        directory = runs_root / run_id
        spent = attempts(directory)
        settled = _settled_usd(spent)
        total += settled
        config = _json(directory / "run-config.json")
        rows.append(
            {
                "run_id": run_id,
                "model": config.get("model"),
                "selected_run": run_id == selected,
                "discarded": run_id != selected,
                "settled_usd": settled,
                "total_usd": round(float(spent["total_usd"]), 6),
                "retries": spent["retries"],
                "attempts": spent["settles"],
            }
        )
    return rows, round(total, 6)


def unlisted_runs(theorem: str, named: set[str], runs_root: Path) -> dict[str, float]:
    """Spend of other on-disk runs of `theorem`. Informational unless `--discover`."""
    found = {}
    if not runs_root.is_dir():
        return found
    for path in sorted(runs_root.glob("*/run-config.json")):
        config = _json(path)
        if config.get("theorem") != theorem:
            continue
        run_id = path.parent.name
        if run_id in named:
            continue
        found[run_id] = _settled_usd(attempts(path.parent))
    return found


def _code(row: dict) -> dict | None:
    if row.get("source") == "previous" and isinstance(row.get("code"), dict):
        return row["code"]
    code = (row.get("config") or {}).get("code")
    return code if isinstance(code, dict) else None


def build(
    rows: list[dict], runs_root: Path, ceiling: float, discover: bool, named: set[str]
) -> tuple[dict, list[dict]]:
    """Provenance for the selected rows, and a block entry for every row over the ceiling."""
    problems = {}
    blocked = []
    for row in rows:
        contributors = list(row.get("contributing_run_ids") or [])
        others = unlisted_runs(row["name"], named, runs_root)
        spend_ids = contributors + (list(others) if discover else [])
        calls, spend = _calls(spend_ids, runs_root, row.get("run_id"))
        spend = round(spend, 6)
        entry = {
            "source": row["source"],
            "run_id": row.get("run_id"),
            "candidate_id": row.get("candidate_id"),
            "graph_id": row.get("graph_id"),
            "label": row.get("label"),
            "proof_sha256": None,
            "model": {
                "name": (row.get("config") or {}).get("model"),
                "provider": (row.get("config") or {}).get("provider"),
                "version": (row.get("config") or {}).get("model_version"),
            },
            "pinned_sources": row.get("source_versions") or [],
            "toolchains": [
                version for version, _commit in row.get("source_versions") or [] if isinstance(version, str)
            ],
            "local_verification": {
                "proxy": row.get("proxy"),
                "recorded_proxy": row.get("recorded_proxy"),
                "tokens": row.get("tokens"),
                "heartbeats": row.get("heartbeats"),
                "recorded_tokens": row.get("recorded_tokens"),
                "recorded_heartbeats": row.get("recorded_heartbeats"),
                "passed": row.get("passed") or {},
            },
            "tool_call_id": row.get("tool_call_id"),
            "request_id": row.get("request_id"),
            "turn": _turn(row),
            "spend_usd": spend,
            "ceiling_usd": ceiling,
            "calls": calls,
            "unlisted_runs": others,
            "run_ids": spend_ids,
        }
        code = _code(row)
        if code is not None:
            entry["code"] = code
        directory = row.get("directory")
        if directory:
            path = Path(directory)
            entry["trace_ids"] = trace_ids(path, row.get("config") or {})
            entry["ledger_paths"] = {
                name: str(path / name)
                for name in ("ledger.jsonl", "cost-ledger.jsonl", "trace-journal.jsonl", "submission.json")
            }
        if spend > ceiling + 1e-9:
            run_list = ", ".join(f"{call['run_id']} ${call['settled_usd']:.4f}" for call in calls) or "none"
            blocked.append(
                {
                    "row": row["name"],
                    "candidate": row.get("graph_id"),
                    "candidate_id": row.get("candidate_id"),
                    "label": row.get("label"),
                    "reasons": [f"spend ${spend:.4f} across {run_list} exceeds the ${ceiling:.2f} per-problem ceiling"],
                }
            )
        problems[row["name"]] = entry
    return problems, blocked
