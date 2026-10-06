"""Run summary: one comparable artifact per budgeted run.

Everything is derived from files the run already writes (ledger.jsonl, cost-ledger.jsonl,
events.jsonl, run-config.json, cost.json), so a run that was killed can still be analysed.
"""

from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

COMPILE_TOOLS = {"arena_evaluate", "arena_probe", "arena_profile"}
BOOKKEEPING_TOOLS = {"arena_idea", "arena_frontier"}
LOCAL_EDIT_MAX_LINES = 2
WARMUP_REQUESTS = 2


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _result_ok(event: dict) -> bool:
    """False when the harness rejected or failed a tool call."""
    if event.get("isError"):
        return False
    try:
        payload = json.loads(event["result"]["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    return not (isinstance(payload, dict) and payload.get("ok") is False)


def cost_report_from_ledger(directory: Path) -> dict:
    """Reconstruct the cost report from the durable journal when Pi could not write it."""
    reserved: dict[str, float] = {}
    spent = 0.0
    for event in _jsonl(directory / "cost-ledger.jsonl"):
        if event.get("kind") == "reserve":
            reserved[str(event["id"])] = float(event["usd"])
        elif event.get("kind") in ("settle", "release") and str(event["id"]) in reserved:
            reserved.pop(str(event["id"]))
            if event["kind"] == "settle" and event.get("usage_known") is not False:
                spent += float(event["usd"])
    config = _read_json(directory / "run-config.json")
    return {"theorem": config.get("theorem"), "model": config.get("model"),
            "hard_cap_usd": config.get("hard_cap_usd"), "spent_usd": spent,
            "unresolved_usd": sum(reserved.values()), "written_by": "runner_ledger_reconstruction"}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _turns(events: list[dict], settles: list[dict]) -> list[dict]:
    """One row per priced assistant response with its tools, outcome and ledger cost."""
    results: dict[str, bool] = {}
    for event in events:
        if event.get("type") == "tool_execution_end":
            results[str(event.get("toolCallId"))] = _result_ok(event)
    priced = iter(s for s in settles if s.get("usage_known") is not False)
    turns = []
    for event in events:
        message = event.get("message") or {}
        if event.get("type") != "message_end" or message.get("role") != "assistant":
            continue
        usage = message.get("usage") or {}
        if not usage.get("totalTokens"):
            continue
        settle = next(priced, None)
        calls = [block for block in message.get("content", []) if block.get("type") == "toolCall"]
        names = [call["name"] for call in calls]
        rejected = any(results.get(str(call["id"])) is False for call in calls)
        if rejected:
            kind = "rejected"
        elif any(name in COMPILE_TOOLS for name in names):
            kind = "compile"
        elif any(name in BOOKKEEPING_TOOLS for name in names):
            kind = "bookkeeping"
        elif names:
            kind = "context"
        else:
            kind = "reasoning"
        turns.append({"kind": kind, "tools": names, "usd": float(settle["usd"]) if settle else 0.0,
                      "cache_read": usage.get("cacheRead", 0), "cache_write": usage.get("cacheWrite", 0),
                      "stop_reason": message.get("stopReason")})
    return turns


def _edit_classes(ledger: list[dict], directory: Path) -> dict:
    """Local = at most LOCAL_EDIT_MAX_LINES changed lines against the first parent."""
    proofs: dict[str, str] = {}
    counts = Counter()
    for event in ledger:
        if event.get("kind") != "candidate" or event.get("origin") != "model":
            continue
        proof_path = directory / "proofs" / f"{event['candidate_id']}.lean"
        proofs[event["candidate_id"]] = proof_path.read_text() if proof_path.exists() else ""
        parent = (event.get("parents") or [None])[0]
        if parent not in proofs:
            parent_path = directory / "proofs" / f"{parent}.lean"
            proofs[parent] = parent_path.read_text() if parent and parent_path.exists() else None
        if proofs.get(parent) is None:
            counts["unclassified"] += 1
            continue
        old, new = proofs[parent].splitlines(), proofs[event["candidate_id"]].splitlines()
        changed = sum(max(a1 - a0, b1 - b0) for tag, a0, a1, b0, b1 in
                      SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if tag != "equal")
        counts["local" if changed <= LOCAL_EDIT_MAX_LINES else "structural"] += 1
    return {"local": counts["local"], "structural": counts["structural"],
            "unclassified": counts["unclassified"],
            "rule": f"local = at most {LOCAL_EDIT_MAX_LINES} changed lines against the first parent"}


def _progress(ledger: list[dict]) -> dict:
    start = next((e["ts"] for e in ledger if e.get("kind") == "init"), None)
    labels = {}
    for event in ledger:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
    timeline, best = [], {"tokens": None, "heartbeats": None, "proxy": None, "estimated_proxy": None}
    for event in ledger:
        if event.get("kind") != "evaluation":
            continue
        result, metrics = event["result"], event["result"].get("metrics") or {}
        row = {"candidate": labels.get(event["candidate_id"]), "mode": event["mode"],
               "tokens": result.get("tokens"), "heartbeats": result.get("heartbeat"),
               "proxy": metrics.get("proxy"), "estimated_proxy": metrics.get("estimated_proxy"),
               "compiled": bool(metrics.get("compiled")),
               "t": round(event["ts"] - start, 1) if start else None}
        timeline.append(row)
        if not row["compiled"]:
            continue
        for key, lower in (("tokens", True), ("heartbeats", True), ("proxy", False), ("estimated_proxy", False)):
            value = row[key]
            if value is None:
                continue
            current = best[key]
            if current is None or (value < current["value"] if lower else value > current["value"]):
                best[key] = {"value": value, "candidate": row["candidate"]}
    return {"best": best, "timeline": timeline}


def build_summary(directory: Path) -> dict:
    ledger = _jsonl(directory / "ledger.jsonl")
    events = _jsonl(directory / "events.jsonl")
    cost_events = _jsonl(directory / "cost-ledger.jsonl")
    config = _read_json(directory / "run-config.json")
    report = _read_json(directory / "cost.json") or cost_report_from_ledger(directory)
    settles = [e for e in cost_events if e.get("kind") == "settle"]
    turns = _turns(events, settles)
    spent = report.get("spent_usd") or sum(s["usd"] for s in settles if s.get("usage_known") is not False)
    cap = report.get("hard_cap_usd") or config.get("hard_cap_usd")
    by_kind: dict[str, dict] = {}
    for turn in turns:
        row = by_kind.setdefault(turn["kind"], {"requests": 0, "usd": 0.0})
        row["requests"] += 1
        row["usd"] = round(row["usd"] + turn["usd"], 6)
    evaluations = [e for e in ledger if e.get("kind") == "evaluation"]
    probes = {e["proof_id"] for e in ledger if e.get("kind") == "probe"}
    read = sum(t["cache_read"] for t in turns)
    write = sum(t["cache_write"] for t in turns)
    recent = turns[-10:]
    recent_read, recent_write = sum(t["cache_read"] for t in recent), sum(t["cache_write"] for t in recent)
    alarms = [e for e in cost_events if e.get("kind") == "cache_alarm"]
    calls, errors = Counter(), Counter()
    result_ok = {str(e.get("toolCallId")): _result_ok(e) for e in events if e.get("type") == "tool_execution_end"}
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            for block in message.get("content", []):
                if block.get("type") == "toolCall":
                    calls[block["name"]] += 1
                    if result_ok.get(str(block["id"])) is False:
                        errors[block["name"]] += 1
    controls = [e for e in cost_events if e.get("kind") == "control"]
    ideas: dict[str, dict] = {}
    for event in ledger:
        if event.get("kind") == "idea":
            ideas[event["id"]] = {"id": event["id"], "title": event["title"], "status": event["status"], "attempts": 0}
        elif event.get("kind") == "idea_update" and event["id"] in ideas:
            ideas[event["id"]].update({k: event[k] for k in ("status", "title") if k in event})
        elif event.get("kind") == "candidate" and event.get("idea_id") in ideas:
            ideas[event["idea_id"]]["attempts"] += 1
    overshoot = max(0.0, spent - cap) if cap else 0.0
    progress = _progress(ledger)
    return {
        "run_id": directory.name, "theorem": config.get("theorem") or report.get("theorem"),
        "model": config.get("model"), "thinking": config.get("thinking"),
        "skill": (config.get("skill") or {}).get("sha256"),
        "stop_reason": (controls[-1].get("stop") if controls else None) or "model_stopped",
        "cost": {"spent_usd": round(spent, 6), "hard_cap_usd": cap, "overshoot_usd": round(overshoot, 6),
                 "requests": len(turns), "by_turn_type": by_kind,
                 "bookkeeping_and_rejected_pct": round(100 * sum(by_kind.get(k, {"usd": 0})["usd"]
                                                                 for k in ("bookkeeping", "rejected")) / spent, 1) if spent else 0.0,
                 "usd_per_evaluation": round(spent / len(evaluations), 6) if evaluations else None,
                 "report_source": report.get("written_by", "pi_session_shutdown")},
        "cache": {"reuse_pct": round(100 * read / (read + write), 1) if read + write else None,
                  "reuse_pct_recent_10": round(100 * recent_read / (recent_read + recent_write), 1)
                  if recent_read + recent_write else None,
                  "read_tokens": read, "write_tokens": write, "alarms": len(alarms),
                  "per_request": [[t["cache_read"], t["cache_write"]] for t in turns]},
        "progress": progress, "edits": _edit_classes(ledger, directory),
        "evaluations": len(evaluations), "probes": len(probes),
        "tools": {"calls": dict(calls), "errors": dict(errors), "error_total": sum(errors.values())},
        "ideas": list(ideas.values()),
    }


def render_text(summary: dict) -> str:
    best, cost, cache = summary["progress"]["best"], summary["cost"], summary["cache"]
    def pick(key: str) -> str:
        item = best.get(key)
        return f"{item['value']} ({item['candidate']})" if item else "none"
    kinds = ", ".join(f"{k} {v['requests']}×${v['usd']:.4f}" for k, v in sorted(cost["by_turn_type"].items()))
    return "\n".join([
        f"{summary['run_id']}: {summary['theorem']} · {summary['model']} · thinking {summary['thinking']} · stop {summary['stop_reason']}",
        f"cost ${cost['spent_usd']:.4f} of ${cost['hard_cap_usd']} (overshoot ${cost['overshoot_usd']:.4f}) over "
        f"{cost['requests']} requests; {kinds}; bookkeeping+rejected {cost['bookkeeping_and_rejected_pct']}%",
        f"cache reuse {cache['reuse_pct']}% (recent {cache['reuse_pct_recent_10']}%), alarms {cache['alarms']}",
        f"best: tokens {pick('tokens')}, heartbeats {pick('heartbeats')}, proxy {pick('proxy')}, "
        f"estimated proxy {pick('estimated_proxy')}",
        f"evaluations {summary['evaluations']}, probes {summary['probes']}, edits "
        f"structural {summary['edits']['structural']} / local {summary['edits']['local']}",
        f"tool errors {summary['tools']['error_total']}: {summary['tools']['errors']}",
    ]) + "\n"


def write_summary(directory: Path) -> dict:
    summary = build_summary(directory)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (directory / "summary.txt").write_text(render_text(summary))
    return summary
