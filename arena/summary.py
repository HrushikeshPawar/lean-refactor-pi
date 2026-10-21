"""Run summary: one comparable artifact per budgeted run.

Everything is derived from files the run already writes (ledger.jsonl, cost-ledger.jsonl,
events.jsonl, run-config.json, cost.json), so a run that was killed can still be analysed.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from arena.merges import merge_report, merge_text
from arena.routes import progress as route_progress
from arena.routes import route_table, routes_detail_text

COMPACTION_SOURCES = (
    "compaction",
    "orphan_stream",
)  # settle rows of Pi's summary requests; the old name is kept for old runs


def configured_cap(config: dict) -> float | None:
    """The run's spend limit. run-config.json says `limit_usd`; older files called it `soft_cap_usd` or `hard_cap_usd`."""
    return config.get("limit_usd") or config.get("soft_cap_usd") or config.get("hard_cap_usd")


STOP_FILE = "stop-reason.txt"  # a stop the runner imposed (e.g. "interrupted"); wins over the cost ledger's control row


def stop_reason_of(directory: Path, controls: list[dict]) -> str:
    """The one source of truth for how a run ended, shared by summary.json, summary.txt and campaign tables:
    the runner's own note, else the last control row of the cost ledger, else "model_stopped"."""
    try:
        noted = (directory / STOP_FILE).read_text().strip()
    except OSError:
        noted = ""
    return noted or (controls[-1].get("stop") if controls else None) or "model_stopped"


COMPILE_TOOLS = {"compile"}
LOCAL_EDIT_MAX_LINES = 2
WARMUP_REQUESTS = 2


# Each request logs its full payload twice (`post_hook` and the `wire` body): 99% of a trace journal, which reaches
# hundreds of MB. Readers that need only event headers cut a line there instead of parsing and holding it.
_HEAVY_FIELD = re.compile(r',"(?:post_hook|body)":')


def trace_rows(path: Path) -> list[dict]:
    """trace-journal.jsonl without request payloads and wire bodies; every other event is whole."""
    rows = []
    try:
        handle = path.open(errors="replace")  # streamed: the whole file as one str is 4 bytes a character
    except OSError:
        return rows
    with handle:
        for line in handle:
            cut = _HEAVY_FIELD.search(line, 0, 600)
            try:
                row = json.loads(line[: cut.start()] + "}" if cut else line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


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


# The only Pi event types any reader of events.jsonl uses. A run's file is 100-160 MB, almost all `message_update`
# stream chunks (~0.1% of lines are kept), so lines are filtered by their head before any JSON is parsed, and a live
# file is read incrementally: each call parses only the complete lines appended since the last one.
KEPT_EVENTS = ("message_end", "tool_execution_end")
_EVENT_NAMES = tuple(f'"{kind}"'.encode() for kind in KEPT_EVENTS)  # Pi writes "type" first; spacing may vary
_EVENTS: dict[str, tuple[int, int, list[dict]]] = {}  # path -> (inode, bytes consumed, kept rows)
_EVENTS_LOCK = threading.Lock()


def read_events(path: Path) -> list[dict]:
    try:
        stat = path.stat()
    except OSError:
        return []
    key = str(path)
    with _EVENTS_LOCK:
        inode, offset, rows = _EVENTS.get(key, (stat.st_ino, 0, []))
        if inode != stat.st_ino or stat.st_size < offset:  # replaced or truncated: start over
            offset, rows = 0, []
        rows = list(rows)
        with path.open("rb") as handle:
            handle.seek(offset)
            for line in handle:
                if not line.endswith(b"\n"):
                    break  # the half-written tail of a live file: read it next time
                offset += len(line)
                head = line[:48]
                if not any(name in head for name in _EVENT_NAMES):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("type") in KEPT_EVENTS:
                    rows.append(row)
        _EVENTS[key] = (stat.st_ino, offset, rows)
        if len(_EVENTS) > 8:  # a few runs at most
            _EVENTS.pop(next(iter(_EVENTS)))
        return rows


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _result_ok(event: dict) -> bool:
    """False when the harness rejected or failed a tool call."""
    if event.get("isError"):
        return False
    try:
        payload = json.loads(event["result"]["content"][0]["text"].splitlines()[0])
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    return not (isinstance(payload, dict) and payload.get("ok") is False)


def _entry_usd(usage: object) -> float:
    cost = (usage or {}).get("cost") if isinstance(usage, dict) else None
    total = cost.get("total") if isinstance(cost, dict) else None
    return float(total) if isinstance(total, (int, float)) else 0.0


def session_spend(directory: Path) -> dict | None:
    """Pi's own record of paid usage: every message, compaction, branch summary and usage entry.

    Pi session files hold requests the cost ledger may never see settle, notably the summaries
    Pi sends for compaction. None when the run has no session file."""
    files = sorted((directory / "session").glob("*.jsonl"))
    if not files:
        return None
    usd = compaction_usd = 0.0
    compactions = 0
    for file in files:
        for row in _jsonl(file):
            kind = row.get("type")
            if kind == "message":
                message = row.get("message") or {}
                if message.get("role") in ("assistant", "toolResult"):
                    usd += _entry_usd(message.get("usage"))
            elif kind in ("compaction", "branch_summary", "usage"):
                amount = _entry_usd(row.get("usage"))
                usd += amount
                if kind == "compaction" and amount:
                    compaction_usd += amount
                    compactions += 1
    return {"usd": usd, "compaction_usd": compaction_usd, "compactions": compactions}


def counted_settles(cost_events: list[dict]) -> tuple[list[dict], bool]:
    """One row per request. Unknown usage is incomplete, not a zero charge."""
    seen: set[tuple[str, str]] = set()
    kept: list[dict] = []
    unknown = False
    for event in cost_events:
        if event.get("kind") != "settle":
            continue
        if event.get("usage_known") is False:
            unknown = True
            continue
        # A settle row's own id names the request it charges; request_id is stamped from the
        # extension's current request and can repeat across distinct charges, so it is not a key.
        if event.get("id"):
            key = (str(event["id"]), str(event.get("session_entry_id") or ""))
            if key in seen:
                continue
            seen.add(key)
        kept.append(event)
    return kept, unknown


def ledger_spend(cost_events: list[dict], session_usd: float | None = None) -> dict:
    """The run's spend: the sum of the cost ledger's settle rows, each one call's actual cost.

    Pi's own session total is a cross-check: the spend never falls below it, so a call the ledger lost
    cannot lower it, and `gap_usd` exposes the difference."""
    settled = compaction_settled = 0.0
    compaction_settles = 0
    for event in counted_settles(cost_events)[0]:
        settled += float(event.get("usd") or 0.0)
        if event.get("source") in COMPACTION_SOURCES:
            compaction_settled += float(event.get("usd") or 0.0)
            compaction_settles += 1
    gap = max(0.0, session_usd - settled) if session_usd is not None else 0.0
    gap = gap if gap > 1e-9 else 0.0
    return {
        "ledger_settled_usd": round(settled, 6),
        "compaction_settled_usd": round(compaction_settled, 6),
        "compaction_settles": compaction_settles,
        "session_usd": None if session_usd is None else round(session_usd, 6),
        "gap_usd": round(gap, 6),
        "spent_usd": max(settled, session_usd or 0.0),
    }


def cost_report_from_ledger(directory: Path) -> dict:
    """Reconstruct the cost report from the durable journal when Pi could not write it."""
    if (directory / "control.jsonl").is_file():
        from arena.run_control import read_state, run_threshold

        state = read_state(directory)
        config = _read_json(directory / "run-config.json")
        return {
            "theorem": config.get("theorem"),
            "model": config.get("model"),
            "spent_usd": state["total"],
            "limit_usd": str(run_threshold(directory)),
            "accounting": state["accounting"],
            "accounting_failures": state["accounting_failures"],
            "unknown_requests": state["unknown_requests"],
            "by_actor": state["by_actor"],
            "by_job": state["by_job"],
            "stopped": state["stopped"],
            "stop_reason": state["stop_reason"],
            "projection_of": "control.jsonl",
        }
    session = session_spend(directory)
    spend = ledger_spend(_jsonl(directory / "cost-ledger.jsonl"), session["usd"] if session else None)
    config = _read_json(directory / "run-config.json")
    return {
        "theorem": config.get("theorem"),
        "model": config.get("model"),
        "limit_usd": configured_cap(config),
        "spent_usd": spend["spent_usd"],
        "written_by": "runner_ledger_reconstruction",
    }


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
    priced = iter(
        s for s in settles if s.get("usage_known") is not False and s.get("source") not in COMPACTION_SOURCES
    )  # compaction summaries are not agent messages
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
        elif names and all(_new_bookkeeping_call(call) for call in calls):
            kind = "bookkeeping"
        elif names:
            kind = "context"
        else:
            kind = "reasoning"
        parts = (settle or {}).get("ledger_components_usd") or {}
        tokens = (settle or {}).get("tokens") or {}
        turns.append(
            {
                "kind": kind,
                "tools": names,
                "usd": float(settle["usd"]) if settle else 0.0,
                "input": usage.get("input", 0),
                "cache_read": usage.get("cacheRead", 0),
                "cache_write": usage.get("cacheWrite", 0),
                "input_side_usd": sum(float(parts.get(k) or 0) for k in ("input", "cacheRead", "cacheWrite")),
                "uncached_rate": (
                    float(parts["input"]) / tokens["input"] if parts.get("input") and tokens.get("input") else None
                ),
                "stop_reason": message.get("stopReason"),
            }
        )
    return turns


def _new_bookkeeping_call(call: dict) -> bool:
    name = call.get("name")
    arguments = call.get("arguments") or {}
    if not isinstance(arguments, dict):
        return False
    if name == "read":
        return arguments.get("view", "source") in ("map", "outline")
    if name == "goal":
        return not arguments.get("try")
    return name == "finish"


def _compile_counters(events: list[dict]) -> dict:
    calls = []
    for event in events:
        message = event.get("message") or {}
        if event.get("type") == "message_end" and message.get("role") == "assistant":
            calls.extend(block for block in message.get("content", []) if block.get("type") == "toolCall")
    selected = [call for call in calls if call.get("name") in COMPILE_TOOLS]
    first = next((index for index, call in enumerate(calls) if call.get("name") in COMPILE_TOOLS), None)
    operation_names = {"splice", "fill", "merge"}
    with_operation = sum(
        bool(set((call.get("arguments") or {}).keys()) & operation_names or (call.get("arguments") or {}).get("base"))
        for call in selected
        if call.get("name") == "compile"
    )
    return {
        "compile_calls": len(selected),
        "compile_calls_with_operation": with_operation,
        "calls_before_first_compile": len(calls[:first]) if first is not None else len(calls),
    }


def hit_rate_pct(read: int, write: int, uncached: int) -> float | None:
    """Industry-standard cache hit rate: cache_read over every prompt token (input + read + write)."""
    prompt = uncached + read + write
    return round(100 * read / prompt, 1) if prompt else None


def cache_savings_pct(turns: list[dict]) -> float | None:
    """1 - actual input-side cost / cost had every prompt token been billed at the uncached input
    rate. The rate comes from the turn's own settle, else the run's last observed uncached rate."""
    rates = [t["uncached_rate"] for t in turns if t.get("uncached_rate")]
    if not rates:
        return None
    actual = baseline = 0.0
    for turn in turns:
        rate = turn.get("uncached_rate") or rates[-1]
        actual += turn.get("input_side_usd", 0.0)
        baseline += (turn["input"] + turn["cache_read"] + turn["cache_write"]) * rate
    return round(100 * (1 - actual / baseline), 1) if baseline else None


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
        if not isinstance(parent, str):
            counts["unclassified"] += 1
            continue
        if parent not in proofs:
            parent_path = directory / "proofs" / f"{parent}.lean"
            if parent_path.exists():
                proofs[parent] = parent_path.read_text()
        if parent not in proofs:
            counts["unclassified"] += 1
            continue
        old, new = proofs[parent].splitlines(), proofs[event["candidate_id"]].splitlines()
        changed = sum(
            max(a1 - a0, b1 - b0)
            for tag, a0, a1, b0, b1 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
            if tag != "equal"
        )
        counts["local" if changed <= LOCAL_EDIT_MAX_LINES else "structural"] += 1
    return {
        "local": counts["local"],
        "structural": counts["structural"],
        "unclassified": counts["unclassified"],
        "rule": f"local = at most {LOCAL_EDIT_MAX_LINES} changed lines against the first parent",  # log: operator run summary
    }


def _progress(ledger: list[dict]) -> dict:
    start = next((e["ts"] for e in ledger if e.get("kind") == "init"), None)
    labels = {}
    for event in ledger:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
    timeline, best = [], {"tokens": None, "heartbeats": None, "proxy": None, "estimated_proxy": None}
    best_verified_candidate = None
    for event in ledger:
        if event.get("kind") != "evaluation":
            continue
        result, metrics = event["result"], event["result"].get("metrics") or {}
        row = {
            "candidate": labels.get(event["candidate_id"]),
            "mode": event["mode"],
            "tokens": result.get("tokens"),
            "heartbeats": result.get("heartbeat"),
            "proxy": metrics.get("proxy"),
            "estimated_proxy": metrics.get("estimated_proxy"),
            "compiled": bool(metrics.get("compiled")),
            "t": round(event["ts"] - start, 1) if start else None,
        }
        timeline.append(row)
        if not row["compiled"]:
            continue
        compat = metrics.get("axes", {}).get("compat", {})
        if (
            event["mode"] == "full"
            and metrics.get("proxy") is not None
            and compat.get("total") is not None
            and compat.get("passed") == compat.get("total")
        ):
            candidate = {
                "candidate": row["candidate"],
                "tokens": row["tokens"],
                "heartbeats": row["heartbeats"],
                "proxy": metrics["proxy"],
            }
            if best_verified_candidate is None or candidate["proxy"] > best_verified_candidate["proxy"]:
                best_verified_candidate = candidate
        for key, lower in (("tokens", True), ("heartbeats", True), ("proxy", False), ("estimated_proxy", False)):
            value = row[key]
            if value is None:
                continue
            current = best[key]
            if current is None or (value < current["value"] if lower else value > current["value"]):
                best[key] = {"value": value, "candidate": row["candidate"]}
    return {"best": best, "best_verified_candidate": best_verified_candidate, "timeline": timeline}


def build_summary(directory: Path) -> dict:
    ledger = _jsonl(directory / "ledger.jsonl")
    events = read_events(directory / "events.jsonl")
    cost_events = _jsonl(directory / "cost-ledger.jsonl")
    trace = trace_rows(directory / "trace-journal.jsonl")
    config = _read_json(directory / "run-config.json")
    shared_accounting = (directory / "control.jsonl").is_file()
    report = (
        cost_report_from_ledger(directory)
        if shared_accounting
        else (_read_json(directory / "cost.json") or cost_report_from_ledger(directory))
    )
    submission_result = _json(directory / "submission.json")
    settles = [e for e in cost_events if e.get("kind") == "settle"]
    turns = _turns(events, settles)
    request_events = [event for event in trace if event.get("kind") == "request"]
    retries = sum(event.get("retry_of") is not None for event in request_events)
    session = session_spend(directory)
    recon = ledger_spend(cost_events, session["usd"] if session else None)
    reported_spend = float(report.get("spent_usd") or 0.0)
    spent = reported_spend if shared_accounting else max(reported_spend, recon["spent_usd"])
    if shared_accounting:
        recon["authority"] = "control.jsonl"
    recon["cost_report_usd"] = report.get("spent_usd")
    cap_value = (
        report.get("limit_usd") or configured_cap(config) or report.get("soft_cap_usd") or report.get("hard_cap_usd")
    )
    cap = float(cap_value) if cap_value is not None else None
    remaining = max(0.0, float(cap or 0.0) - spent)
    by_kind: dict[str, dict] = {}
    for turn in turns:
        row = by_kind.setdefault(turn["kind"], {"requests": 0, "usd": 0.0})
        row["requests"] += 1
        row["usd"] = round(row["usd"] + turn["usd"], 6)
    # Pi's compaction summaries are paid requests that are not agent turns.
    compaction_usd = recon["compaction_settled_usd"] or (session or {}).get("compaction_usd", 0.0)
    if compaction_usd:
        by_kind["compaction"] = {
            "requests": recon["compaction_settles"] or (session or {}).get("compactions", 0),
            "usd": round(compaction_usd, 6),
        }
    evaluations = [e for e in ledger if e.get("kind") == "evaluation"]
    probes = {e["proof_id"] for e in ledger if e.get("kind") == "probe"}
    read = sum(t["cache_read"] for t in turns)
    write = sum(t["cache_write"] for t in turns)
    recent = turns[-10:]
    recent_read, recent_write = sum(t["cache_read"] for t in recent), sum(t["cache_write"] for t in recent)
    uncached, recent_uncached = sum(t["input"] for t in turns), sum(t["input"] for t in recent)
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
    overshoot = max(0.0, spent - cap) if cap else 0.0
    progress = _progress(ledger)
    if submission_result and submission_result.get("candidate"):
        progress["best_verified_candidate"] = {
            "candidate": submission_result["candidate"],
            "tokens": submission_result.get("tokens"),
            "heartbeats": submission_result.get("heartbeats"),
            "proxy": submission_result.get("proxy"),
        }
    best_verified = progress.get("best_verified_candidate")
    best_at = None
    if best_verified:
        candidate_ids = [event["candidate_id"] for event in ledger if event.get("kind") == "candidate"]
        try:
            best_id = candidate_ids[int(best_verified["candidate"].removeprefix("#")) - 1]
            best_at = min(
                event["ts"]
                for event in ledger
                if event.get("kind") == "evaluation"
                and event.get("candidate_id") == best_id
                and event.get("mode") == "full"
                and (event.get("result", {}).get("metrics") or {}).get("proxy") is not None
            )
        except (IndexError, KeyError, ValueError, TypeError):
            best_at = None
    later_settles = [event for event in settles if best_at is not None and float(event.get("ts", 0)) / 1000 > best_at]
    later_requests = [
        event for event in request_events if best_at is not None and float(event.get("ts", 0)) / 1000 > best_at
    ]
    stopped = stop_reason_of(directory, controls)
    route_rows = route_table(ledger)
    drains = [e for e in ledger if e.get("kind") == "closing_drain"]
    golfs = [e for e in ledger if e.get("kind") == "golf"]
    return {
        "golf": {k: v for k, v in golfs[-1].items() if k not in ("kind", "ts")} if golfs else None,
        "closing_drain": {k: v for k, v in drains[-1].items() if k not in ("kind", "ts")} if drains else None,
        "run_id": directory.name,
        "theorem": config.get("theorem") or report.get("theorem"),
        "model": config.get("model"),
        "thinking": config.get("thinking"),
        "skill": (config.get("skill") or {}).get("sha256"),
        "stop_reason": stopped,
        "lean": lean_stats(ledger, directory, stopped),
        "cost": {
            "spent_usd": round(spent, 6),
            "limit_usd": cap,
            "remaining_usd": round(remaining, 6),
            "overshoot_usd": round(overshoot, 6),
            "requests": len(request_events) if request_events else len(turns),
            "priced_responses": len(turns),
            "retries": retries,
            "requests_after_best": len(later_requests),
            "spent_after_best_usd": round(sum(float(event["usd"]) for event in later_settles), 6),
            "by_turn_type": by_kind,
            "reconciliation": recon,
            "bookkeeping_and_rejected_pct": round(
                100 * sum(by_kind.get(k, {"usd": 0})["usd"] for k in ("bookkeeping", "rejected")) / spent, 1
            )
            if spent
            else 0.0,
            "usd_per_evaluation": round(spent / len(evaluations), 6) if evaluations else None,
            "report_source": report.get("projection_of") or report.get("written_by", "pi_session_shutdown"),
        },
        # reuse_pct is the cache hit rate (cache_read / (input + cache_read + cache_write)); the key
        # name is kept for stored summaries and the viewer.
        "cache": {
            "reuse_pct": hit_rate_pct(read, write, uncached),
            "reuse_pct_recent_10": hit_rate_pct(recent_read, recent_write, recent_uncached),
            "savings_pct": cache_savings_pct(turns),
            "savings_pct_recent_10": cache_savings_pct(recent),
            "read_tokens": read,
            "write_tokens": write,
            "input_tokens": uncached,
            "alarms": len(alarms),
            "per_request": [[t["cache_read"], t["cache_write"], t["input"]] for t in turns],
        },
        "progress": progress,
        "edits": _edit_classes(ledger, directory),
        "evaluations": len(evaluations),
        "probes": len(probes),
        "tools": {
            "calls": dict(calls),
            "results": sum(event.get("type") == "tool_execution_end" for event in events),
            "errors": dict(errors),
            "error_total": sum(errors.values()),
            **_compile_counters(events),
        },
        "routes": route_rows,
        "route_progress": route_progress(route_rows),
        "merge_report": merge_report(ledger, directory),
        "submission": submission_result,
    }


LEAN_ALARM_TIMEOUT_RATE = 0.2


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def lean_stats(ledger: list[dict], directory: Path | None = None, stop_reason: str | None = None) -> dict:
    """Lean latency of the model lane: every compat entry of a probe or a model-triggered evaluation is one check
    (a cached repeat is not recorded again, so it is not counted). Alarm: timeout rate above 20%, or a run that
    stopped `lean_unhealthy`."""
    seconds: list[float] = []
    checks = timeouts = warm_kept = cold = 0
    for event in ledger:
        if event.get("kind") == "evaluation" and event.get("trigger", "model") != "model":
            continue
        if event.get("kind") not in ("probe", "evaluation"):
            continue
        for entry in ((event.get("result") or {}).get("compat") or {}).values():
            lean = entry.get("lean") or {}
            checks += 1
            timeouts += str(entry.get("error") or "").startswith("Lean timed out")
            warm_kept += bool(lean.get("warm_kept"))
            cold += lean.get("path") in ("cold", "cold-fallback")
            if isinstance(lean.get("seconds"), (int, float)):
                seconds.append(float(lean["seconds"]))
    rate = round(timeouts / checks, 3) if checks else 0.0
    gate = None
    if directory is not None:
        gate = _json(directory / "lean-health.json")
    unhealthy = stop_reason == "lean_unhealthy"
    return {
        "checks": checks,
        "p50_seconds": _percentile(seconds, 0.5),
        "p95_seconds": _percentile(seconds, 0.95),
        "timeouts": timeouts,
        "timeout_rate": rate,
        "warm_kept": warm_kept,
        "cold_path": cold,
        "gate": (
            {
                "verdict": gate.get("verdict"),
                "timeout": gate.get("timeout"),
                "slowest_warm_seconds": gate.get("slowest_warm_seconds"),
            }
            if gate
            else None
        ),
        "alarm": rate > LEAN_ALARM_TIMEOUT_RATE or unhealthy,
    }


def lean_text(lean: dict | None) -> str:
    if not lean:
        return "lean: no data"

    def sec(value):
        return "n/a" if value is None else f"{value:.1f}s"

    gate = lean.get("gate")
    return (
        "lean: "
        + f"{lean['checks']} model-lane checks, p50 {sec(lean['p50_seconds'])} p95 {sec(lean['p95_seconds'])}, "  # log: operator run summary
        f"timeout rate {round(100 * lean['timeout_rate'])}% ({lean['timeouts']}), warm-kept {lean['warm_kept']}, "
        f"cold path {lean['cold_path']}"
        + (f"; gate {gate['verdict']} limit {gate['timeout']}s" if gate else "")
        + ("; ALARM" if lean.get("alarm") else "")
    )


def route_depth_text(depth: dict | None) -> str:
    if not depth:
        return "route depth: no route events"
    head = f"route depth: {depth['credited_routes']} credited routes, {depth['explored_routes']} explored"  # log: operator run summary
    if depth.get("new_state_share") is None:
        return head + "; no attempts on a route yet"
    share = round(100 * depth["new_state_share"])
    return head + f"; {share}% of attempts produced a goal state new to their route"  # log: operator run summary


def render_text(summary: dict) -> str:
    best, cost, cache = summary["progress"]["best"], summary["cost"], summary["cache"]

    def pick(key: str) -> str:
        item = best.get(key)
        return f"{item['value']} ({item['candidate']})" if item else "none"

    kinds = ", ".join(f"{k} {v['requests']}×${v['usd']:.4f}" for k, v in sorted(cost["by_turn_type"].items()))
    verified = summary["progress"].get("best_verified_candidate")
    verified_line = (
        f"best verified candidate: {verified['candidate']} proxy {verified['proxy']} "  # log: operator run summary
        f"({verified['tokens']} tok, {verified['heartbeats']} HB)"
        if verified
        else "best verified candidate: none (original proof baseline stands)"  # log: operator run summary
    )
    return (
        "\n".join(
            [
                f"{summary['run_id']}: {summary['theorem']} · {summary['model']} · thinking {summary['thinking']} · stop {summary['stop_reason']}",
                (
                    f"cost ${cost['spent_usd']:.4f} of ${cost['limit_usd']} limit "  # log: operator run summary
                    f"(remaining ${cost['remaining_usd']:.4f}; overshoot ${cost['overshoot_usd']:.4f}) over "
                    f"{cost['requests']} requests / {summary['tools']['results']} tool results "
                    f"({cost['retries']} retries); {kinds}; bookkeeping+rejected {cost['bookkeeping_and_rejected_pct']}%"
                ),
                *(
                    [
                        f"SPEND GAP: ledger settled ${cost['reconciliation']['ledger_settled_usd']:.4f}, Pi session "  # log: operator run summary
                        f"${cost['reconciliation']['session_usd'] or 0:.4f}, gap ${cost['reconciliation']['gap_usd']:.4f}"
                    ]
                    if cost["reconciliation"]["gap_usd"]
                    else []
                ),
                lean_text(summary.get("lean")),
                f"cache hit rate {cache['reuse_pct']}% (recent {cache['reuse_pct_recent_10']}%), cost savings {cache['savings_pct']}%, alarms {cache['alarms']}",  # log: operator run summary
                verified_line,
                f"per-axis highs: tokens {pick('tokens')}, heartbeats {pick('heartbeats')}, proxy {pick('proxy')}, "  # log: operator run summary
                f"estimated proxy {pick('estimated_proxy')}",
                f"evaluations {summary['evaluations']}, probes {summary['probes']}, edits "  # log: operator run summary
                f"structural {summary['edits']['structural']} / local {summary['edits']['local']}",
                f"post-best spend ${cost['spent_after_best_usd']:.4f} over {cost['requests_after_best']} requests; "  # log: operator run summary
                "routes tried: " + routes_detail_text(summary.get("routes") or []),
                route_depth_text(summary.get("route_progress")),
                "harness merge check: " + merge_text(summary.get("merge_report") or []),
                f"tool errors {summary['tools']['error_total']}: {summary['tools']['errors']}",
                f"submission: {(summary.get('submission') or {}).get('candidate') or 'none'}",
            ]
        )
        + "\n"
    )


def write_summary(directory: Path, stop_reason: str | None = None) -> dict:
    """`stop_reason` overrides the ledger's, e.g. when the runner was interrupted."""
    try:  # persisted so a later build_summary (campaign report, viewer) names the stop the same way
        if stop_reason:
            (directory / STOP_FILE).write_text(stop_reason + "\n")
        else:
            (directory / STOP_FILE).unlink(missing_ok=True)
    except OSError:
        pass
    summary = build_summary(directory)
    if stop_reason:
        summary["stop_reason"] = stop_reason
        if summary.get("lean") is not None:
            summary["lean"]["alarm"] = summary["lean"]["alarm"] or stop_reason == "lean_unhealthy"
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    (directory / "summary.txt").write_text(render_text(summary))
    return summary
