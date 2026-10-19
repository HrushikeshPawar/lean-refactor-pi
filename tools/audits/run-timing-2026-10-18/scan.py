#!/usr/bin/env python3
"""Offline interval accounting for saved v7*/v8* runs; never starts Lean or a provider."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from contextlib import suppress
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def merge(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def duration(intervals):
    return sum(end - start for start, end in merge(intervals))


def intersect(left, right):
    a, b = merge(left), merge(right)
    result, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result


def gaps(start, end, intervals):
    result, cursor = [], start
    for a, b in merge(intersect([(start, end)], intervals)):
        if a > cursor:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if end > cursor:
        result.append((cursor, end))
    return result


def stats(values):
    values = sorted(values)
    if not values:
        return {"n": 0, "sum_s": 0}

    def quantile(p):
        position = (len(values) - 1) * p
        lo, hi = math.floor(position), math.ceil(position)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)

    return {"n": len(values), "sum_s": sum(values), "mean_s": statistics.mean(values),
            "p50_s": quantile(0.5), "p90_s": quantile(0.9), "p95_s": quantile(0.95),
            "max_s": max(values)}


def rows(path, errors):
    if not path.exists():
        return
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"{path.relative_to(ROOT)}:{number}: malformed JSON")


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def iso(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    return None


def analyse_run(path, errors, manifest):
    ledger = list(rows(path / "ledger.jsonl", errors))
    config, summary, health = (load(path / name) for name in
                               ("run-config.json", "summary.json", "lean-health.json"))
    trace = list(rows(path / "trace-journal.jsonl", errors))
    cost = list(rows(path / "cost-ledger.jsonl", errors))
    for name in ("ledger.jsonl", "run-config.json", "summary.json", "lean-health.json",
                 "trace-journal.jsonl", "cost-ledger.jsonl"):
        file = path / name
        if file.exists():
            manifest.append({"path": str(file.relative_to(ROOT)), "bytes": file.stat().st_size,
                             "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    init = next((r for r in ledger if r.get("kind") == "init"), {})
    inherited_events = 0
    if config.get("seed_run"):
        seed_index = next((i for i, r in enumerate(ledger) if r.get("kind") == "seeded"), None)
        if seed_index is not None:
            inherited_events = seed_index
            ledger = ledger[seed_index + 1:]
    # Trace/cost timestamps are milliseconds; the Python ledger uses seconds.
    requests, responses, headers, calls, results = {}, {}, {}, {}, {}
    duplicates = Counter()
    for row in trace:
        kind = row.get("kind")
        # Synthetic message_end rows can retain an earlier stamped request_id.
        # Their explicit id differs: do not overwrite the actual provider response.
        key = row.get("id") or row.get("request_id")
        mapping = {"request": requests, "response": responses, "http_response": headers}.get(kind)
        if mapping is not None:
            if key in mapping:
                duplicates[kind] += 1
            mapping[key] = row
        elif kind in ("tool_call", "tool_result"):
            key = row.get("tool_call_id")
            mapping = calls if kind == "tool_call" else results
            if key in mapping:
                duplicates[kind] += 1
            mapping[key] = row
    llm, tools, request_rows, tool_rows = [], [], [], []
    tools_by_request = defaultdict(set)
    for call in calls.values():
        tools_by_request[call.get("id") or call.get("request_id")].add(call.get("name"))
    missing_response = []
    for key, request in requests.items():
        start = request["ts"] / 1000
        response = responses.get(key)
        if response is None:
            missing_response.append(key)
            continue
        end = response["ts"] / 1000
        if end < start:
            errors.append(f"{path.name}: request ends before start: {key}")
            continue
        llm.append((start, end))
        header = headers.get(key)
        usage = response.get("usage") or {}
        request_rows.append({"run": path.name, "id": key, "start": start, "end": end,
                             "model": request.get("model") or config.get("model"),
                             "seconds": end - start,
                             "header_seconds": header["ts"] / 1000 - start if header else None,
                             "stream_after_headers_seconds": end - header["ts"] / 1000 if header else None,
                             "retry": bool(request.get("retry_of")),
                             "failed": bool(response.get("error_message")) or response.get("stop_reason") in ("error", "aborted"),
                             "output_tokens": usage.get("output", 0),
                             "input_tokens": sum(usage.get(k, 0) or 0 for k in ("input", "cache_read", "cache_write")),
                             "tool_names": sorted(tools_by_request.get(key, set())),
                             "stop_reason": response.get("stop_reason")})
    for key, call in calls.items():
        result = results.get(key)
        if result is None:
            continue
        start, end = call["ts"] / 1000, result["ts"] / 1000
        if end < start:
            errors.append(f"{path.name}: tool ends before start: {key}")
            continue
        tools.append((start, end))
        tool_rows.append({"run": path.name, "id": key, "name": call.get("name"), "start": start,
                          "end": end, "seconds": end - start, "failed": bool(result.get("is_error")),
                          "check": (call.get("args") or {}).get("check")})
    timestamps = [r["ts"] for r in ledger if isinstance(r.get("ts"), (float, int))]
    timestamps += [r["ts"] / 1000 for r in trace if isinstance(r.get("ts"), (float, int))]
    # Cost controls/compaction can occur between trace records, and remain observed activity.
    timestamps += [r["ts"] / 1000 for r in cost if isinstance(r.get("ts"), (float, int))]
    for key in ("started", "finished"):
        if isinstance(health.get(key), (float, int)):
            timestamps.append(health[key])
    event_path = path / "events.jsonl"
    session_start = None
    if event_path.exists():
        with event_path.open() as stream:
            first = stream.readline()
        with suppress(ValueError, json.JSONDecodeError):
            session_start = iso(json.loads(first).get("timestamp"))
        if session_start:
            timestamps.append(session_start)
    start, end = (min(timestamps), max(timestamps)) if timestamps else (None, None)
    first_request = min((r["ts"] / 1000 for r in requests.values()), default=None)
    last_trace = max((r["ts"] / 1000 for r in trace), default=None)
    # Use last trace event, not the last LLM response, so final tool execution belongs to interaction.
    pre = first_request - start if first_request is not None else 0
    post = end - last_trace if last_trace is not None else 0
    llm_s, tool_s = duration(llm), duration(tools)
    overlap_s = duration(intersect(llm, tools))
    interactive_gaps = gaps(first_request, last_trace, llm + tools) if first_request is not None else []
    wall = end - start if start is not None else 0
    if first_request is None:
        pre = wall  # setup-only records have no interactive/provider window
    remaining = wall - llm_s - tool_s + overlap_s
    assert remaining >= -0.001
    if first_request is not None:
        assert abs(wall - (pre + post + llm_s + tool_s - overlap_s + duration(interactive_gaps))) < 0.01
    durations_by_kind = defaultdict(list)
    lean_samples, cold = [], []
    best_score, best_ts = float("-inf"), None
    for row in ledger:
        kind = row.get("kind")
        if isinstance(row.get("seconds"), (int, float)):
            durations_by_kind[kind].append(row["seconds"])
        result = row.get("result") or {}
        if kind == "evaluation" and row.get("mode") == "full":
            proxy = result.get("local_proxy")
            if isinstance(proxy, (int, float)) and proxy > best_score:
                best_score, best_ts = proxy, row.get("ts")
        for version, info in (row.get("compat") or result.get("compat") or {}).items():
            lean = info.get("lean") or {}
            if isinstance(lean.get("seconds"), (int, float)):
                sample = {"kind": kind, "mode": row.get("mode"), "version": version,
                          "path": lean.get("path"), "seconds": lean["seconds"],
                          "queue_seconds": lean.get("queue_seconds"), "header_seconds": lean.get("header_seconds"),
                          "check_seconds": lean.get("check_seconds"), "passed": info.get("passed"),
                          "new_worker": lean.get("new_worker"), "lane": lean.get("lane"),
                          "candidate": row.get("candidate_id") or row.get("proof_id")}
                lean_samples.append(sample)
                if kind == "cold_verification":
                    cold.append(sample)
    row = {"run": path.name, "family": path.name.split("-")[0], "model": config.get("model") or summary.get("model"),
           "theorem": init.get("theorem") or config.get("theorem"), "stop_reason": summary.get("stop_reason"),
           "has_summary": bool(summary), "start": start, "end": end, "observed_wall_s": wall,
           "inherited_ledger_events_excluded": inherited_events,
           "requests": len(requests), "matched_requests": len(request_rows), "missing_response_ids": missing_response,
           "orphan_response_count": len(set(responses) - set(requests)), "duplicates": dict(duplicates),
           "llm_union_s": llm_s, "llm_attempt_sum_s": sum(r["seconds"] for r in request_rows),
           "tool_union_s": tool_s, "tool_exclusive_s": tool_s - overlap_s, "llm_tool_overlap_s": overlap_s,
           "other_observed_s": remaining, "before_first_request_s": pre, "after_last_trace_s": post,
           "interactive_unattributed_s": duration(interactive_gaps),
           "max_interactive_gap_s": max((b-a for a, b in interactive_gaps), default=0),
           "largest_gaps": sorted(({"start": a, "end": b, "seconds": b-a} for a,b in interactive_gaps),
                                  key=lambda r:r["seconds"], reverse=True)[:5],
           "health_wall_s": health.get("wall_seconds"), "health_verdict": health.get("verdict"),
           "gate_timeout_s": health.get("timeout"),
           "explicit_duration_s": {k: sum(v) for k,v in durations_by_kind.items()},
           "cold_pin_sum_s": sum(r["seconds"] for r in cold), "cold_pin_results": len(cold),
           "restarts": sum(r.get("kind") == "restart" for r in ledger),
           "best_full_proxy": best_score if best_ts is not None else None,
           "last_best_full_ts": best_ts,
           "llm_after_last_best_s": duration(intersect(llm, [(best_ts, end)])) if best_ts is not None else None,
           "llm_intervals": merge(llm), "tool_intervals": merge(tools),
           "compaction_settles": [{"ts": r["ts"] / 1000, "id": r.get("id")} for r in cost
                                  if r.get("kind") == "settle" and r.get("source") == "compaction"],
           "unmatched_tool_calls": len(set(calls)-set(results)), "lean_samples": lean_samples}
    return row, request_rows, tool_rows


def aggregate(runs, requests, tools):
    totals = {k: sum(r[k] for r in runs) for k in ("observed_wall_s", "llm_union_s", "tool_exclusive_s",
              "before_first_request_s", "after_last_trace_s", "interactive_unattributed_s", "llm_tool_overlap_s")}
    llm_models, tool_names = {}, {}
    for model in sorted({r["model"] for r in requests}, key=str):
        selected = [r for r in requests if r["model"] == model]
        llm_models[model] = {"duration": stats([r["seconds"] for r in selected]),
                             "response_headers": stats([r["header_seconds"] for r in selected if r["header_seconds"] is not None]),
                             "stream_after_headers": stats([r["stream_after_headers_seconds"] for r in selected if r["stream_after_headers_seconds"] is not None]),
                             "failed": sum(r["failed"] for r in selected), "retry_attempts": sum(r["retry"] for r in selected)}
    for name in sorted({r["name"] for r in tools}, key=str):
        selected = [r for r in tools if r["name"] == name]
        tool_names[name] = {**stats([r["seconds"] for r in selected]), "failed": sum(r["failed"] for r in selected)}
    return {"runs": len(runs), "runs_with_requests": sum(r["requests"] > 0 for r in runs),
            "request_latency": stats([r["seconds"] for r in requests]), "tool_duration": stats([r["seconds"] for r in tools]),
            "run_wall": stats([r["observed_wall_s"] for r in runs]), "totals": totals,
            "models": llm_models, "tools": tool_names,
            "health_wall": stats([r["health_wall_s"] for r in runs if r["health_wall_s"] is not None]),
            "request_wall_global_union_s": duration([v for r in runs for v in r["llm_intervals"]]),
            "observed_wall_global_union_s": duration([(r["start"], r["end"]) for r in runs if r["start"] is not None])}


def self_check():
    assert merge([(0, 3), (2, 5), (5, 7), (9, 9)]) == [(0, 7)]
    assert duration([(0, 3), (2, 5)]) == 5
    assert intersect([(0, 4), (8, 12)], [(2, 10)]) == [(2, 4), (8, 10)]
    assert gaps(0, 10, [(2, 4), (3, 7), (9, 11)]) == [(0, 2), (7, 9)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    self_check()
    runs, requests, tools, errors, manifest, campaigns = [], [], [], [], [], []
    for path in sorted((ROOT / "runs/pi-budget").iterdir()):
        if not path.is_dir() or not path.name.startswith(("v7", "v8")):
            continue
        if not (path / "ledger.jsonl").exists() and not (path / "trace-journal.jsonl").exists():
            campaigns.append(path.name)
            continue
        row, calls, tool_calls = analyse_run(path, errors, manifest)
        runs.append(row)
        requests.extend(calls)
        tools.extend(tool_calls)
    families = {}
    for family in sorted({r["family"] for r in runs}):
        selected = [r for r in runs if r["family"] == family]
        ids = {r["run"] for r in selected}
        families[family] = aggregate(selected, [r for r in requests if r["run"] in ids],
                                     [r for r in tools if r["run"] in ids])
    result = {"scope": "runs/pi-budget/v7* and v8*, observed timestamp spans, not CPU time",
              "excluded_containers": campaigns, "errors": errors, "aggregate": aggregate(runs, requests, tools),
              "families": families, "runs": runs, "requests": requests, "tools": tools, "manifest": manifest}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    columns = [k for k,v in runs[0].items() if not isinstance(v, (dict, list))]
    with (args.output / "runs.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(runs)
    print(json.dumps({"runs": len(runs), "containers": len(campaigns), "request_pairs": len(requests),
                      "tool_pairs": len(tools), "errors": errors, "totals": result["aggregate"]["totals"]}, indent=2))


if __name__ == "__main__":
    main()
