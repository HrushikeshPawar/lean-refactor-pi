"""Read-only data shaping for the local run viewer (arena/cli/serve.py).

Everything is derived from files a run already writes; nothing here starts, stops or writes to a
run. Langfuse is read server-side only: the keys never reach a response, a log line or an error.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arena.routes import progress as route_progress
from arena.routes import route_table
from arena.summary import (
    COMPACTION_SOURCES,
    _result_ok,
    _turns,
    build_summary,
    configured_cap,
    hit_rate_pct,
    ledger_spend,
    read_events,
    session_spend,
    trace_rows,
)

BASELINE_PROXY = round(100 / 3, 2)
STALL_SECONDS = 15 * 60
TEXT_LIMIT = 4000
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()  # `arena serve` answers requests on threads; eviction iterates the cache


# ---------------------------------------------------------------------------------------------
# File access with cheap caching
# ---------------------------------------------------------------------------------------------


def _stamp(path: Path):
    try:
        info = path.stat()
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def read_jsonl(path: Path) -> list[dict]:
    """Rows of a JSONL file; a missing file is empty and a half-written last line is skipped."""
    key = ("jsonl", str(path))
    stamp = _stamp(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    rows: list[dict] = []
    if stamp is not None:
        try:
            for line in path.read_text(errors="replace").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        except OSError:
            rows = []
    with _CACHE_LOCK:
        jsonl_keys = [k for k in _CACHE if k[0] == "jsonl"]
        for old in jsonl_keys[: max(0, len(jsonl_keys) - 23)]:  # keep memory bounded: oldest files go first
            _CACHE.pop(old, None)
        _CACHE.pop(key, None)
        _CACHE[key] = (stamp, rows)
    return rows


def _events(path: Path) -> list[dict]:
    """The assistant-message and tool-result events of events.jsonl, re-read only when the file changes."""
    key, stamp = ("events", str(path)), _stamp(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    rows = read_events(path)
    with _CACHE_LOCK:
        for old in [k for k in _CACHE if k[0] == "events" and k != key][:-3]:  # a few runs at most
            _CACHE.pop(old, None)
        _CACHE[key] = (stamp, rows)
    return rows


def _trace(path: Path) -> list[dict]:
    """The tool events of a trace journal, re-read only when it changes; payloads are never held."""
    key, stamp = ("trace", str(path)), _stamp(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    rows = [row for row in trace_rows(path) if row.get("kind") in ("tool_call", "tool_result")]
    _CACHE[key] = (stamp, rows)
    return rows


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _seconds(ts) -> float | None:
    """The cost and trace journals stamp milliseconds, the candidate ledger seconds."""
    if not isinstance(ts, (int, float)):
        return None
    return ts / 1000 if ts > 1e11 else float(ts)


def _clip(value, limit: int = TEXT_LIMIT) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} more characters)"


def campaign_of(run_id: str, root: Path) -> str:
    """The campaign prefix: the `<prefix>-campaign` directory next to the run that holds its log
    (run_campaign.py writes `<run id>.log` there); otherwise the run's own leading word."""
    for directory in sorted(root.glob("*-campaign")) if root.is_dir() else []:
        if (directory / f"{run_id}.log").exists():
            return directory.name[: -len("-campaign")]
    match = re.match(r"^([A-Za-z0-9]+(?:-[a-z]+-\d{8})?)-", run_id)
    return match[1] if match else "(none)"


def _reference(theorem: str | None) -> dict | None:
    if not theorem:
        return None
    try:
        from arena.scoring import reference as published

        tokens, heartbeats = published(theorem)
    except (ValueError, ImportError, KeyError):
        return None
    return {"tokens": tokens, "heartbeats": heartbeats, "proxy": BASELINE_PROXY}


def _live_summary(directory: Path, ttl: float = 10.0) -> dict:
    """summary.json once the run wrote it; otherwise a summary built from the journals (cached
    briefly, because a live run's files change constantly)."""
    finished = read_json(directory / "summary.json")
    if finished:
        return finished
    key = ("summary", str(directory))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        summary = build_summary(directory)
    except Exception:  # a half-written journal must not break the page
        summary = {}
    _CACHE[key] = (time.monotonic(), summary)
    return summary


def _start_end(directory: Path) -> tuple[float | None, float | None]:
    ledger = read_jsonl(directory / "ledger.jsonl")
    start = next((e["ts"] for e in ledger if e.get("kind") == "init" and isinstance(e.get("ts"), (int, float))), None)
    costs = read_jsonl(directory / "cost-ledger.jsonl")
    stamps = [s for s in (_seconds(e.get("ts")) for e in costs) if s]
    stamps += [e["ts"] for e in ledger[-3:] if isinstance(e.get("ts"), (int, float))]
    if start is None and stamps:
        start = min(stamps)
    return start, (max(stamps) if stamps else None)


# ---------------------------------------------------------------------------------------------
# Hub: one row per run
# ---------------------------------------------------------------------------------------------


def hub_row(run_id: str, directory: Path, campaign: str | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    config, state, answer = (
        read_json(directory / name) for name in ("run-config.json", "state.json", "submission.json")
    )
    summary = _live_summary(directory)
    finished = bool(read_json(directory / "summary.json"))
    cost = summary.get("cost") or {}
    cache = summary.get("cache") or {}
    tools = summary.get("tools") or {}
    start, last = _start_end(directory)
    spent = requests = 0
    for event in read_jsonl(directory / "cost-ledger.jsonl"):
        if event.get("kind") == "settle" and event.get("usage_known") is not False:
            spent += float(event.get("usd") or 0)
            requests += 1
    # The summary's figure also covers requests Pi paid for that the ledger never settled.
    spent = max(spent, float(cost.get("spent_usd") or 0))
    best = state.get("best") or {}
    verified = (summary.get("progress") or {}).get("best_verified_candidate") or {}
    if not best and verified:
        best = {
            "candidate": verified.get("candidate"),
            "proxy": verified.get("proxy"),
            "tokens": verified.get("tokens"),
            "heartbeats": verified.get("heartbeats"),
        }
    reference = _reference(config.get("theorem"))
    stalled = not finished and last is not None and now - last > STALL_SECONDS
    status = "finished" if finished else "stalled" if stalled else "live"
    ended = last if finished or stalled else now
    proxy = best.get("proxy")
    return {
        "run_id": run_id,
        "campaign": campaign,
        "model": config.get("model"),
        "theorem": config.get("theorem"),
        "reference": reference,
        "thinking": config.get("thinking"),
        "limit_usd": cost.get("limit_usd") or configured_cap(config),
        "spent_usd": round(spent, 6),
        "requests": cost.get("requests") or requests,
        "tool_results": tools.get("results"),
        "tool_errors": tools.get("error_total"),
        "cache_reuse_pct": cache.get("reuse_pct"),
        "cache_savings_pct": cache.get("savings_pct"),
        "bookkeeping_pct": cost.get("bookkeeping_and_rejected_pct"),
        "spent_after_best_usd": cost.get("spent_after_best_usd"),
        "requests_after_best": cost.get("requests_after_best"),
        "best": {
            "candidate": best.get("candidate"),
            "proxy": proxy,
            "tokens": best.get("tokens"),
            "heartbeats": best.get("heartbeats"),
        }
        if best
        else None,
        "delta_proxy": round(proxy - BASELINE_PROXY, 2) if isinstance(proxy, (int, float)) else None,
        "leading_unverified": state.get("leading_unverified"),
        "checking": state.get("checking", []),
        "finished": finished,
        "status": status,
        "stop_reason": summary.get("stop_reason") if finished else None,
        "submission": answer.get("candidate"),
        "submission_info": {
            "candidate": answer.get("candidate"),
            "proxy": answer.get("proxy"),
            "verified_by": answer.get("verified_by"),
            "cold_verified": answer.get("verified_by") == "cold compile",
        }
        if answer
        else None,
        "started": start,
        "ended": ended,
        "duration_s": round(ended - start, 1) if start and ended else None,
        "langfuse_url": None,
    }


# ---------------------------------------------------------------------------------------------
# Per-run dashboard
# ---------------------------------------------------------------------------------------------


def _candidate_labels(ledger: list[dict]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for event in ledger:
        if event.get("kind") == "candidate" and event["candidate_id"] not in labels:
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
    return labels


def score_timeline(ledger: list[dict], start: float | None) -> list[dict]:
    labels = _candidate_labels(ledger)
    rows, best = [], None
    for event in ledger:
        if event.get("kind") != "evaluation":
            continue
        number = len(rows) + 1  # evaluation 0 is the original proof; the charts' x axis is this number
        result = event.get("result") or {}
        metrics = result.get("metrics") or {}
        proxy = metrics.get("proxy")
        if event.get("mode") == "full" and metrics.get("compiled") and proxy is not None:
            best = proxy if best is None else max(best, proxy)
        rows.append(
            {
                "n": number,
                "t": round(event["ts"] - start, 1) if start else None,
                "candidate": labels.get(event.get("candidate_id")),
                "candidate_id": event.get("candidate_id"),
                "mode": event.get("mode"),
                "proxy": proxy,
                "estimated_proxy": metrics.get("estimated_proxy"),
                "tokens": result.get("tokens"),
                "heartbeats": result.get("heartbeat"),
                "compiled": bool(metrics.get("compiled")),
                "best_verified": best,
            }
        )
    return rows


def spend_series(directory: Path, start: float | None, limit: float | None) -> dict:
    cost_events = read_jsonl(directory / "cost-ledger.jsonl")
    settles = [e for e in cost_events if e.get("kind") == "settle"]
    try:
        turns = _turns(_events(directory / "events.jsonl"), settles)
    except (KeyError, TypeError):
        turns = []
    priced = iter(turns)
    session = session_spend(directory)
    recon = ledger_spend(cost_events, session["usd"] if session else None)
    names = {"input": "input", "output": "output", "cacheRead": "cache_read", "cacheWrite": "cache_write"}
    points, spent = [], 0.0
    for settle in settles:
        if settle.get("usage_known") is False:
            continue
        turn = {"kind": "compaction"} if settle.get("source") in COMPACTION_SOURCES else next(priced, {})
        parts = {names[k]: float(v) for k, v in (settle.get("ledger_components_usd") or {}).items() if k in names}
        tokens = settle.get("tokens") or {}
        spent += float(settle.get("usd") or 0)
        stamp = _seconds(settle.get("ts"))
        read, write, fresh = tokens.get("cache_read", 0), tokens.get("cache_write", 0), tokens.get("input", 0)
        points.append(
            {
                "n": len(points) + 1,
                "t": round(stamp - start, 1) if start and stamp else None,
                "request_usd": float(settle.get("usd") or 0),
                "spent_usd": round(spent, 6),
                "parts": parts,
                "tokens": tokens,
                "kind": turn.get("kind"),
                "tools": turn.get("tools", []),
                "reuse_pct": hit_rate_pct(read, write, fresh),
            }
        )
    return {
        "points": points,
        "spent_usd": round(max(spent, recon["spent_usd"]), 6),
        "limit_usd": limit,
        "unsettled_usd": recon["gap_usd"],
        "reconciliation": recon,
    }


def tool_timeline(directory: Path, start: float | None) -> list[dict]:
    """Each tool call with start/end from the trace journal (its rows carry timestamps)."""
    calls: dict[str, dict] = {}
    for row in _trace(directory / "trace-journal.jsonl"):
        kind = row.get("kind")
        key = str(row.get("tool_call_id"))
        if kind == "tool_call":
            calls[key] = {
                "id": key,
                "name": row.get("name"),
                "start": _seconds(row.get("ts")),
                "end": None,
                "args": _clip(row.get("args")),
                "result": None,
                "is_error": False,
            }
        elif kind == "tool_result" and key in calls:
            result = row.get("result")
            text = row.get("text")
            if text is None and isinstance(result, dict):
                text = "\n".join(
                    block.get("text", "") for block in result.get("content", []) if isinstance(block, dict)
                )
            call = calls[key]
            call["end"] = _seconds(row.get("ts"))
            call["result"] = _clip(text if text is not None else result)
            try:
                payload = result if isinstance(result, dict) else {}
                call["is_error"] = not _result_ok({"isError": payload.get("isError"), "result": payload})
            except (KeyError, TypeError, AttributeError):
                call["is_error"] = False
    ordered = sorted(calls.values(), key=lambda c: c["start"] or 0)
    horizon = max((c["end"] or c["start"] or 0 for c in ordered), default=0)
    lanes: list[float] = []
    for call in ordered:
        begin = call["start"] or 0
        end = call["end"] if call["end"] is not None else horizon
        for number, busy in enumerate(lanes):
            if busy <= begin:
                lanes[number] = end
                call["lane"] = number
                break
        else:
            call["lane"] = len(lanes)
            lanes.append(end)
        call["running"] = call["end"] is None
        call["duration_s"] = round(end - begin, 3)
        call["t"] = round(begin - start, 2) if start else None
        call["t_end"] = round(end - start, 2) if start else None
        for field in ("start", "end"):
            call.pop(field)
    return ordered


def control_events(directory: Path, start: float | None) -> list[dict]:
    rows = []
    limit_reached = False
    for event in read_jsonl(directory / "cost-ledger.jsonl"):
        kind = event.get("kind")
        stamp = _seconds(event.get("ts"))
        t = round(stamp - start, 1) if start and stamp else None
        if kind == "finish":
            rows.append(
                {
                    "t": t,
                    "kind": "finish",
                    "label": f"finish {event.get('phase')}",
                    "detail": {k: v for k, v in event.items() if k not in ("ts", "kind", "phase")},
                }
            )
        elif kind == "control":
            label = f"control: stop {event['stop']}" if event.get("stop") else "control"
            rows.append(
                {
                    "t": t,
                    "kind": "control",
                    "label": label,
                    "detail": {k: v for k, v in event.items() if k not in ("ts", "kind")},
                }
            )
        elif kind == "cache_alarm":
            rows.append(
                {
                    "t": t,
                    "kind": "cache_alarm",
                    "label": "cache alarm",
                    "detail": {k: v for k, v in event.items() if k not in ("ts", "kind")},
                }
            )
        elif (
            kind == "settle"
            and not limit_reached
            and event.get("limit_usd")
            and (event.get("spent_usd") or 0) >= event["limit_usd"]
        ):
            limit_reached = True
            rows.append(
                {
                    "t": t,
                    "kind": "limit",
                    "label": "spend limit reached",
                    "detail": {"spent_usd": event.get("spent_usd"), "limit_usd": event["limit_usd"]},
                }
            )
    return rows


def lean_mix(ledger: list[dict]) -> dict:
    """How Lean ran: session (warm worker) versus cold compiles, per kind of check."""
    paths: dict[str, dict] = {}
    for event in ledger:
        if event.get("kind") not in ("evaluation", "probe"):
            continue
        label = event["kind"] if event["kind"] == "probe" else f"evaluation {event.get('mode')}"
        for compat in ((event.get("result") or {}).get("compat") or {}).values():
            lean = compat.get("lean") if isinstance(compat, dict) else None
            if not lean:
                continue
            row = paths.setdefault(lean.get("path") or "unknown", {"runs": 0, "seconds": 0.0, "by_check": {}})
            row["runs"] += 1
            row["seconds"] = round(row["seconds"] + float(lean.get("seconds") or 0), 2)
            row["by_check"][label] = row["by_check"].get(label, 0) + 1
    colds = [e for e in ledger if e.get("kind") == "cold_verification"]
    return {"paths": paths, "cold_verification": colds[-1] if colds else None}


def run_dashboard(run_id: str, directory: Path) -> dict:
    ledger = read_jsonl(directory / "ledger.jsonl")
    start, last = _start_end(directory)
    summary = _live_summary(directory)
    limit = (summary.get("cost") or {}).get("limit_usd") or configured_cap(read_json(directory / "run-config.json"))
    packet = directory / "packet.txt"
    try:
        packet_text = packet.read_text(errors="replace")
    except OSError:
        packet_text = None
    # A live summary always carries a default stop_reason, so only summary.json means the run ended.
    return {
        "run_id": run_id,
        "started": start,
        "last_activity": last,
        "finished": bool(read_json(directory / "summary.json")),
        "config": read_json(directory / "run-config.json"),
        "summary": summary,
        "submission": read_json(directory / "submission.json") or None,
        "reference": _reference(summary.get("theorem")),
        "baseline_proxy": BASELINE_PROXY,
        "scores": score_timeline(ledger, start),
        "spend": spend_series(directory, start, limit),
        "tools": tool_timeline(directory, start),
        "routes": (route_rows := route_table(ledger)),
        "route_progress": route_progress(route_rows),
        "controls": control_events(directory, start),
        "lean": lean_mix(ledger),
        "packet": packet_text,
    }


# ---------------------------------------------------------------------------------------------
# Langfuse (server side only)
# ---------------------------------------------------------------------------------------------

Fetch = Callable[[str, dict | None], dict]
_LF_FIELDS = "core,basic,time,model,usage,metrics"


class LangfuseUnavailable(RuntimeError):
    """Carries a short message that is safe to show: never a key, header or URL."""


def _config_fetch(config_path: Path) -> tuple[Fetch, str]:
    try:
        config = json.loads(config_path.read_text())
        token = base64.b64encode(f"{config['publicKey']}:{config['secretKey']}".encode()).decode()
        base = str(config["baseUrl"]).rstrip("/")
    except (OSError, KeyError, TypeError, ValueError):
        raise LangfuseUnavailable("Langfuse config missing or unreadable") from None

    def fetch(path: str, query: dict | None = None) -> dict:
        url = base + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raise LangfuseUnavailable(f"Langfuse answered HTTP {error.code}") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise LangfuseUnavailable("Langfuse is not reachable") from None

    return fetch, base


class Langfuse:
    """Session view of one run, cached for `ttl` seconds. `fetch(path, query)` is injectable."""

    def __init__(
        self,
        config_path: Path | None = None,
        fetch: Fetch | None = None,
        base_url: str | None = None,
        ttl: float = 45.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config_path = config_path or Path.home() / ".pi" / "agent" / "langfuse.json"
        self._fetch, self._base, self.ttl, self.clock = fetch, base_url, ttl, clock
        self._project: tuple[float, str | None] | None = None
        self._sessions: dict[str, tuple[float, dict]] = {}

    def _ready(self) -> tuple[Fetch, str]:
        if self._fetch is None or self._base is None:
            self._fetch, self._base = _config_fetch(self.config_path)
        return self._fetch, self._base

    def project_id(self) -> str | None:
        now = self.clock()
        if self._project and (self._project[1] or now - self._project[0] < 60):
            return self._project[1]
        project = None
        try:
            fetch, _ = self._ready()
            data = fetch("/api/public/projects", None).get("data") or []
            project = data[0].get("id") if data else None
        except LangfuseUnavailable:
            project = None
        self._project = (now, project)
        return project

    def session_url(self, run_id: str) -> str | None:
        try:
            _, base = self._ready()
        except LangfuseUnavailable:
            return None
        project = self.project_id()
        return f"{base}/project/{project}/sessions/{urllib.parse.quote(run_id)}" if project else None

    def session(self, run_id: str, started: float | None = None, refresh: bool = False) -> dict:
        now = self.clock()
        hit = self._sessions.get(run_id)
        if hit and not refresh and now - hit[0] < self.ttl:
            return hit[1]
        try:
            payload = self._load(run_id, started)
        except LangfuseUnavailable as error:
            payload = {"available": False, "error": str(error), "run_id": run_id}
            if hit and hit[1].get("available"):
                payload = {**hit[1], "stale": True, "error": str(error)}
        self._sessions[run_id] = (now, payload)
        return payload

    def _load(self, run_id: str, started: float | None) -> dict:
        fetch, base = self._ready()
        project = self.project_id()
        begin = datetime.fromtimestamp((started or time.time() - 14 * 86400) - 300, UTC)
        query = {
            "sessionId": run_id,
            "fromStartTime": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "toStartTime": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fields": _LF_FIELDS,
            "limit": "1000",
        }
        rows: list[dict] = []
        for _ in range(5):
            page = fetch("/api/public/v2/observations", query)
            rows.extend(page.get("data") or [])
            cursor = (page.get("meta") or {}).get("cursor")
            if not cursor:
                break
            query = {**query, "cursor": cursor}
        return shape_langfuse(run_id, rows, base, project)


def _iso(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def shape_langfuse(run_id: str, rows: list[dict], base: str, project: str | None) -> dict:
    root = f"{base}/project/{project}" if project else None
    quoted = urllib.parse.quote(run_id)

    def number(value) -> float:
        return float(value) if isinstance(value, (int, float)) else 0.0

    observations, traces = [], {}
    for row in sorted(rows, key=lambda r: r.get("startTime") or ""):
        usage = row.get("usageDetails") or {}
        cost = row.get("totalCost")
        if cost is None:
            cost = (row.get("costDetails") or {}).get("total")
        item = {
            "id": row.get("id"),
            "trace_id": row.get("traceId"),
            "parent_id": row.get("parentObservationId"),
            "type": row.get("type"),
            "name": row.get("name"),
            "level": row.get("level"),
            "status_message": row.get("statusMessage") or None,
            "model": row.get("model") or None,
            "start": _iso(row.get("startTime")),
            "latency_s": row.get("latency"),
            "cost_usd": cost,
            "input_tokens": number(row.get("inputUsage")) or number(usage.get("input")),
            "output_tokens": number(row.get("outputUsage")) or number(usage.get("output")),
            "cache_read_tokens": number(usage.get("cache_read_input_tokens")),
            "cache_write_tokens": sum(
                number(v) for k, v in usage.items() if "cache_creation" in k or "cache_write" in k
            ),
            "url": f"{root}/traces/{row.get('traceId')}?observation={row.get('id')}" if root else None,
        }
        observations.append(item)
        trace = traces.setdefault(
            row.get("traceId"),
            {
                "trace_id": row.get("traceId"),
                "name": None,
                "start": item["start"],
                "latency_s": None,
                "cost_usd": 0.0,
                "generations": 0,
                "tools": 0,
                "errors": 0,
                "models": set(),
                "url": f"{root}/traces/{row.get('traceId')}" if root else None,
            },
        )
        if item["parent_id"] is None:
            trace["name"], trace["latency_s"] = item["name"], item["latency_s"]
        trace["start"] = min(filter(None, (trace["start"], item["start"])), default=None)
        trace["cost_usd"] += number(cost)
        trace["generations"] += item["type"] == "GENERATION"
        trace["tools"] += item["type"] == "TOOL"
        trace["errors"] += item["level"] == "ERROR"
        if item["model"]:
            trace["models"].add(item["model"])
    trace_rows = sorted(traces.values(), key=lambda t: t["start"] or 0)
    for trace in trace_rows:
        trace["models"] = sorted(trace["models"])
        trace["cost_usd"] = round(trace["cost_usd"], 6)
    generations = [o for o in observations if o["type"] == "GENERATION"]
    latencies = [o["latency_s"] for o in generations if isinstance(o["latency_s"], (int, float))]
    return {
        "available": True,
        "run_id": run_id,
        "project_id": project,
        "traces": trace_rows,
        "observations": observations,
        "session_url": f"{root}/sessions/{quoted}" if root else None,
        "totals": {
            "observations": len(observations),
            "generations": len(generations),
            "tools": sum(o["type"] == "TOOL" for o in observations),
            "errors": sum(o["level"] == "ERROR" for o in observations),
            "cost_usd": round(sum(number(o["cost_usd"]) for o in observations), 6),
            "mean_generation_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "max_generation_latency_s": max(latencies) if latencies else None,
        },
    }


# A call field above this is cut. 200 KB, so one node panel cannot ship a whole journal.
_FIELD_LIMIT = 200 * 1024
_HARNESS_ORIGINS = {"reference", "auto_merge", "assembly"}
_CALL_KEYS = ("tool_call_id", "name", "args", "delivered", "untrimmed", "trimmed", "footer", "is_error")


def node_calls(directory: Path, node: str) -> dict:
    """The journal turn that created `node`: its call, as delivered and untrimmed, and its reasoning.

    v7 nodes join on `tool_call_id`. Older nodes join when one tool-call window encloses the
    ledger timestamp. A missing journal is an empty panel, not an error.
    """
    if not (directory / "trace-journal.jsonl").is_file():
        return _no_call(node, "no journal")
    from arena.replay import ReplayError, node_turn

    index = _journal_index(directory)
    run, calls = index["run"], index["calls"]
    proof_id = _proof_of(run.ledger, node)
    if proof_id is None:
        return _no_call(node, "no call matched")
    event = _creator(run.ledger, proof_id)
    if event is None:
        return _no_call(node, "no call matched")
    if event.get("origin") in _HARNESS_ORIGINS:
        return _no_call(node, "harness-made")
    tool_call = event.get("tool_call_id")
    reason = None
    if tool_call:
        try:
            turn = node_turn(run, node)
        except ReplayError:
            return _no_call(node, "no call matched")
        chosen = next((call for call in calls if call["tool_call_id"] == tool_call and call["turn"] == turn), None)
        if chosen is None:
            chosen = next((call for call in calls if call["tool_call_id"] == tool_call), None)
        if chosen is None:
            return _no_call(node, "no call matched")
    else:
        stamp = event.get("ts")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return _no_call(node, "no call matched")
        enclosing = [call for call in calls if _encloses(call, float(stamp))]
        if not enclosing:
            return _no_call(node, "no call matched")
        enclosing.sort(key=lambda call: (call["start"], call["turn"], str(call["tool_call_id"])))
        chosen = enclosing[0]
        if len(enclosing) > 1:
            reason = "ambiguous"
    found = {
        "node": node,
        "turn": chosen["turn"],
        "call": {key: chosen[key] for key in _CALL_KEYS},
        "reasoning": index["reasoning"].get(chosen["turn"], []),
        "siblings": _siblings(run.ledger, chosen, proof_id),
    }
    if reason:
        found["reason"] = reason
    found.update(_step_origin(directory, run.ledger, proof_id))
    return found


def _journal_index(directory: Path) -> dict:
    """The calls, per-turn reasoning and slim turns `node_calls` joins on, rebuilt only when the
    journal or the ledger changes. Request payloads are never expanded or held; a line that does
    not decode (the half-written tail of a live run) is skipped, as `read_jsonl` does."""
    from arena.replay import Run, _group

    journal, ledger = directory / "trace-journal.jsonl", directory / "ledger.jsonl"
    key, stamp = ("calls", str(directory)), (_stamp(journal), _stamp(ledger))
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    rows: list[dict] = []
    try:
        lines = journal.read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("kind") == "request":
            rows.append({field: row[field] for field in ("kind", "id", "turn", "ts") if field in row})
        elif row.get("kind") in ("tool_call", "tool_result", "response"):
            rows.append(row)
    run = Run(directory, {}, rows, read_jsonl(ledger), [], [], {})
    _group(run)
    index = {"run": run, "calls": _calls(run), "reasoning": {item.number: _reasoning(item) for item in run.turns}}
    # node_turn needs only each tool row's kind, id and time; drop the texts once the calls hold them.
    run.journal = []
    for item in run.turns:
        item.request = {}
        item.rows = [
            {field: row.get(field) for field in ("kind", "tool_call_id", "ts")}
            for row in item.rows
            if row.get("kind") in ("tool_call", "tool_result")
        ]
    with _CACHE_LOCK:
        for old in [k for k in _CACHE if k[0] == "calls" and k != key][:-3]:  # a few runs at most
            _CACHE.pop(old, None)
        _CACHE[key] = (stamp, index)
    return index


def _no_call(node: str, reason: str) -> dict:
    return {"node": node, "turn": None, "call": None, "reasoning": [], "siblings": [], "reason": reason}


def _proof_of(history: list[dict], node: str) -> str | None:
    from arena.campaign import resolve_node_ref

    try:
        return resolve_node_ref(history, node)
    except ValueError:
        return None


def _creator(history: list[dict], proof_id: str) -> dict | None:
    for event in _creators(history):
        if _event_proof(event) == proof_id:
            return event
    return None


def _creators(history: list[dict]) -> list[dict]:
    seen: set[str] = set()
    found = []
    for event in history:
        proof_id = _event_proof(event)
        if not proof_id or proof_id in seen:
            continue
        seen.add(proof_id)
        found.append(event)
    return found


def _event_proof(event: dict) -> str:
    if event.get("kind") == "probe":
        return str(event.get("proof_id") or "")
    if event.get("kind") == "candidate":
        return str(event.get("candidate_id") or "")
    return ""


def _journal_seconds(ts) -> float | None:
    """Journal stamps are milliseconds. Ledger stamps are already seconds."""
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    return float(ts) / 1000


def _text_blocks(result) -> str:
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _delivered(row: dict) -> str:
    if isinstance(row.get("delivered_text"), str):
        return row["delivered_text"]
    return _text_blocks(row.get("result"))


def _untrimmed(row: dict) -> str:
    if isinstance(row.get("text"), str):
        return row["text"]
    return _text_blocks(row.get("result"))


def _is_error(row: dict) -> bool:
    if isinstance(row.get("is_error"), bool):
        return row["is_error"]
    result = row.get("result")
    return bool(isinstance(result, dict) and result.get("isError"))


def _cap(text: str) -> str:
    if len(text) <= _FIELD_LIMIT:
        return text
    omitted = len(text) - _FIELD_LIMIT
    return f"{text[:_FIELD_LIMIT]}\n[truncated: {omitted} more characters; use arena replay]"


def _cap_args(args):
    """Arguments as sent; serialized and cut when the JSON is over the field limit."""
    if args is None:
        return {}
    serialized = json.dumps(args, ensure_ascii=False, default=str)
    return args if len(serialized) <= _FIELD_LIMIT else _cap(serialized)


def _calls(run) -> list[dict]:
    calls = []
    for item in run.turns:
        pending: dict = {}
        order: list = []
        for row in item.rows:
            kind = row.get("kind")
            if kind == "tool_call":
                ident = row.get("tool_call_id")
                start = _journal_seconds(row.get("ts"))
                pending[ident] = {
                    "tool_call_id": ident,
                    "name": str(row.get("name") or ""),
                    "args": _cap_args(row.get("args")),
                    "delivered": "",
                    "untrimmed": "",
                    "trimmed": False,
                    "footer": "",
                    "is_error": False,
                    "turn": item.number,
                    "start": start,
                    "end": start,
                }
                order.append(ident)
            elif kind == "tool_result" and row.get("tool_call_id") in pending:
                call = pending[row.get("tool_call_id")]
                call["delivered"] = _cap(_delivered(row))
                call["untrimmed"] = _cap(_untrimmed(row))
                call["trimmed"] = bool(row.get("trimmed"))
                call["footer"] = row.get("footer") if isinstance(row.get("footer"), str) else ""
                call["is_error"] = _is_error(row)
                end = _journal_seconds(row.get("ts"))
                if end is not None:
                    call["end"] = end
        calls.extend(pending[ident] for ident in order)
    return calls


def _encloses(call: dict, stamp: float) -> bool:
    start, end = call["start"], call["end"]
    return start is not None and end is not None and start <= stamp <= end


def _reasoning(item) -> list[dict]:
    response = next((row for row in item.rows if row.get("kind") == "response"), None)
    if not isinstance(response, dict):
        return []
    blocks = []
    for block in response.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking" and isinstance(block.get("thinking"), str):
            blocks.append({"type": "thinking", "text": _cap(block["thinking"])})
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            blocks.append({"type": "text", "text": _cap(block["text"])})
    return blocks


def _siblings(history: list[dict], chosen: dict, proof_id: str) -> list[str]:
    """Proof ids, the same ids the graph viewer selects. Ordered by ledger time."""
    matched = []
    for event in _creators(history):
        ident = _event_proof(event)
        if not ident or ident == proof_id or event.get("origin") in _HARNESS_ORIGINS:
            continue
        if not _same_call(event, chosen):
            continue
        matched.append(event)
    matched.sort(key=lambda event: (event.get("ts") or 0, _event_proof(event)))
    return [_event_proof(event) for event in matched]


def _same_call(event: dict, chosen: dict) -> bool:
    ident = event.get("tool_call_id")
    if ident and chosen.get("tool_call_id"):
        return ident == chosen["tool_call_id"]
    stamp = event.get("ts")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return False
    return _encloses(chosen, float(stamp))


def _step_origin(directory: Path, history: list[dict], proof_id: str) -> dict:
    """Filing line and holes from the v7 graph. A ledger with no edge for this node has neither."""
    edge = next((event for event in history if event.get("kind") == "edge" and event.get("proof_id") == proof_id), None)
    if edge is None:
        return {}
    from arena.graph import Graph
    from arena.tools import _filing_line

    def read(ident: str) -> str | None:
        path = directory / "proofs" / f"{ident}.lean"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    projection = Graph.from_history(history, read)
    node = next((item for item in projection.nodes if item.proof_id == proof_id), None)
    if node is None:
        return {}
    fields: dict = {"origin_line": f"{node.id} {_filing_line(node, projection, {})}"}
    holes = []
    for hole in node.holes:
        index = hole.get("index")
        holes.append(
            {
                "id": hole.get("id") or (f"{node.id}.h{index}" if index else ""),
                "goal": hole.get("goal"),
                "status": hole.get("status") or "open",
                "fills": list(hole.get("fills") or []),
            }
        )
    if holes:
        fields["holes"] = holes
    # The text names nodes by graph id (`n3`); the viewer keys them on proof ids.
    proofs = {item.id: item.proof_id for item in projection.nodes}
    named = re.findall(r"\bn[1-9][0-9]*\b", fields["origin_line"])
    named += [str(fill) for hole in node.holes for fill in hole.get("fills") or []]
    ids = {name: proofs[name] for name in named if name in proofs}
    if ids:
        fields["ids"] = ids
    return fields
