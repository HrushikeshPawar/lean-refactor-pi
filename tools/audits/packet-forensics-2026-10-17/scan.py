#!/usr/bin/env python3
"""Hash-verified offline inventory of saved v8-family provider request journals."""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from arena.traces import post_hook_bytes, read_journal  # noqa: E402

RUNS_ROOT = REPO_ROOT / "runs" / "pi-budget"
OUTPUT_PATH = Path(__file__).with_name("summary.json")


def text_fields(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from text_fields(item)
    elif isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value["text"]
        if isinstance(value.get("content"), (str, list, dict)):
            yield from text_fields(value["content"])


def median(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def usage_for(response: dict[str, Any] | None) -> dict[str, int] | None:
    if not response or not isinstance(response.get("usage"), dict):
        return None
    usage = response["usage"]
    return {
        "input": int(usage.get("input") or 0),
        "cache_read": int(usage.get("cache_read") or 0),
        "cache_write": int(usage.get("cache_write") or 0),
        "output": int(usage.get("output") or 0),
    }


def request_messages(payload: dict[str, Any]) -> list[str]:
    # Pi's OpenAI Responses payload uses input; chat-style providers use messages.
    source = payload.get("input") or payload.get("messages") or []
    return list(text_fields(source))


def main() -> None:
    journals = sorted(RUNS_ROOT.glob("v8*/trace-journal.jsonl"))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prompt_tokens_by_group: dict[str, list[int]] = defaultdict(list)
    cache_reads_by_group: dict[str, int] = defaultdict(int)
    known_settled_by_group: dict[str, float] = defaultdict(float)
    missing_usage: list[dict[str, Any]] = []
    request_total = 0
    verified_body_total = 0
    global_prompt_tokens = 0
    global_cache_read = 0
    global_settled_usd = 0.0
    total_usage_rows = 0
    first_packet_run_count = 0

    for journal_path in journals:
        raw_rows = [json.loads(line) for line in journal_path.read_text().splitlines() if line]
        rows = read_journal(journal_path)  # reconstructs and SHA-256 verifies every post-hook body
        body_bytes = post_hook_bytes(raw_rows)
        requests = [row for row in rows if row.get("kind") == "request"]
        responses = {
            row.get("request_id"): row for row in rows if row.get("kind") == "response"
        }
        http_status = {
            row.get("request_id"): row.get("status")
            for row in rows
            if row.get("kind") == "http_response"
        }
        run_dir = journal_path.parent
        packet_path = run_dir / "packet.txt"
        packet = packet_path.read_text() if packet_path.exists() else ""
        packet_bytes = packet.encode("utf-8")
        packet_for_match = packet.rstrip("\n")
        tag = run_dir.name.split("-", 1)[0]
        occurrences = 0
        body_sizes: list[int] = []
        prompt_tokens: list[int] = []
        cache_reads: list[int] = []
        tool_sizes: list[int] = []
        run_settled_usd = 0.0
        first_has_packet = False

        for index, request in enumerate(requests):
            payload = request.get("post_hook") or {}
            texts = request_messages(payload)
            has_packet = bool(packet_for_match) and any(
                packet_for_match in text for text in texts
            )
            occurrences += int(has_packet)
            if index == 0:
                first_has_packet = has_packet

            raw_body = body_bytes.get(request.get("id"))
            if raw_body is None:
                raise RuntimeError(f"missing reconstructed body: {journal_path} {request.get('id')}")
            verified_body_total += 1
            body_sizes.append(len(raw_body))

            if payload.get("tools"):
                encoded_tools = json.dumps(
                    payload["tools"], ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                tool_sizes.append(len(encoded_tools))

            response = responses.get(request.get("request_id"))
            usage = usage_for(response)
            if usage is None:
                missing_usage.append(
                    {
                        "run": run_dir.name,
                        "request_id": request.get("request_id"),
                        "http_status": http_status.get(request.get("request_id")),
                    }
                )
                continue

            total_usage_rows += 1
            prompt = usage["input"] + usage["cache_read"] + usage["cache_write"]
            prompt_tokens.append(prompt)
            cache_reads.append(usage["cache_read"])
            prompt_tokens_by_group[tag].append(prompt)
            cache_reads_by_group[tag] += usage["cache_read"]
            global_prompt_tokens += prompt
            global_cache_read += usage["cache_read"]
            settled = float(response.get("settled_usd") or 0)
            run_settled_usd += settled
            known_settled_by_group[tag] += settled
            global_settled_usd += settled

        first_packet_run_count += int(first_has_packet)

        run_row = {
            "run": run_dir.name,
            "request_count": len(requests),
            "packet_chars": len(packet),
            "packet_utf8_bytes": len(packet_bytes),
            "packet_sha256": hashlib.sha256(packet_bytes).hexdigest(),
            "first_request_contains_packet": first_has_packet,
            "requests_containing_packet": occurrences,
            "request_body_bytes_median": median(body_sizes),
            "request_body_bytes_max": max(body_sizes) if body_sizes else None,
            "usage_request_count": len(prompt_tokens),
            "prompt_tokens_median": median(prompt_tokens),
            "prompt_tokens_max": max(prompt_tokens) if prompt_tokens else None,
            "cache_read_share_pct": (
                round(100 * sum(cache_reads) / sum(prompt_tokens), 4)
                if sum(prompt_tokens)
                else None
            ),
            "known_settled_usd": round(run_settled_usd, 6) if prompt_tokens else None,
            "tool_schema_utf8_bytes": sorted(set(tool_sizes)),
        }
        groups[tag].append(run_row)
        request_total += len(requests)

    summaries: dict[str, dict[str, Any]] = {}
    for tag, runs in sorted(groups.items()):
        request_count = sum(run["request_count"] for run in runs)
        body_medians = [
            run["request_body_bytes_median"]
            for run in runs
            if run["request_body_bytes_median"] is not None
        ]
        group_prompt_tokens = prompt_tokens_by_group[tag]
        summaries[tag] = {
            "runs": len(runs),
            "requests": request_count,
            "packet_chars_min": min(run["packet_chars"] for run in runs),
            "packet_chars_max": max(run["packet_chars"] for run in runs),
            "packet_utf8_bytes_min": min(run["packet_utf8_bytes"] for run in runs),
            "packet_utf8_bytes_max": max(run["packet_utf8_bytes"] for run in runs),
            "requests_containing_packet": sum(
                run["requests_containing_packet"] for run in runs
            ),
            "requests_containing_packet_pct": round(
                100
                * sum(run["requests_containing_packet"] for run in runs)
                / request_count,
                4,
            ),
            "request_body_bytes_median_of_run_medians": median(body_medians),
            "request_body_bytes_max": max(
                run["request_body_bytes_max"] or 0 for run in runs
            ),
            "usage_record_count": len(group_prompt_tokens),
            "prompt_tokens_median": median(group_prompt_tokens),
            "prompt_tokens_max": max(group_prompt_tokens) if group_prompt_tokens else None,
            "cache_read_share_pct": (
                round(
                    100 * cache_reads_by_group[tag] / sum(group_prompt_tokens),
                    4,
                )
                if sum(group_prompt_tokens)
                else None
            ),
            "known_settled_usd": (
                round(known_settled_by_group[tag], 6)
                if group_prompt_tokens
                else None
            ),
            "runs_detail": runs,
        }

    result = {
        "generated_from": "runs/pi-budget/v8*/trace-journal.jsonl",
        "method": "arena.traces.read_journal and post_hook_bytes; every reconstructed request body hash-verified",
        "journal_count": len(journals),
        "verified_request_body_count": verified_body_total,
        "all_request_body_hashes_verified": verified_body_total == request_total,
        "first_request_packet_run_count": first_packet_run_count,
        "request_count": request_total,
        "usage_record_count": total_usage_rows,
        "missing_usage_requests": missing_usage,
        "global_prompt_tokens_reported": global_prompt_tokens,
        "global_cache_read_share_pct": round(
            100 * global_cache_read / global_prompt_tokens, 4
        )
        if global_prompt_tokens
        else None,
        "known_settled_usd": round(global_settled_usd, 6),
        "groups": summaries,
    }
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
