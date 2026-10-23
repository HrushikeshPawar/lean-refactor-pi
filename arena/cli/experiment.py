#!/usr/bin/env python3
"""Launch budgeted runs that differ in exactly one declared factor and compare them.

Every run gets the same theorem, packet, limit and options except the factor under test, so
differences in the report are attributable to that factor. Use a small limit ($0.10-$0.20).

    python -m arena.cli experiment --theorem Core.InitsUpdatesComm --prefix think-ab \\
        --factor thinking --values medium,high --model deepseek-v4.1-flash --limit-usd 0.1

Arguments after `--` are passed to every run.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from arena.campaign import packet, run_dir
from arena.cli.run import MODELS, THINKING_LEVELS
from arena.engine import ROOT
from arena.summary import build_summary
from arena.traces import preflight_block

FACTORS = ("model", "thinking", "skill")
PER_RUN_GB = 4.5  # Pi and one Lean process in each of the model and background lanes


def parallelism(requested: str, runs: int, available_kb: int, per_run_gb: float = PER_RUN_GB) -> int:
    """Number of runs to execute at once; `auto` is bounded by measured free memory."""
    if requested != "auto":
        if not requested.isdigit() or int(requested) < 1:
            raise ValueError("--parallel must be a positive integer or 'auto'")
        return min(int(requested), runs)
    fit = int(available_kb / 1024 / 1024 // per_run_gb)
    return max(1, min(runs, fit))


def available_memory_kb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    return 0


def plan(factor: str, values: list[str], model: str, thinking: str, prefix: str) -> list[dict]:
    """One spec per value; everything else is held fixed."""
    if factor not in FACTORS:
        raise ValueError(f"factor must be one of {', '.join(FACTORS)}")
    if len(values) < 2 or len(set(values)) != len(values):
        raise ValueError("give at least two distinct values for the factor")
    allowed = {"model": MODELS, "thinking": THINKING_LEVELS, "skill": ("on", "off")}[factor]
    bad = [value for value in values if value not in allowed]
    if bad:
        raise ValueError(f"invalid {factor} values {bad}; choose from {', '.join(allowed)}")
    specs = []
    for value in values:
        spec = {"model": model, "thinking": thinking, "skill": "on", factor: value}
        spec["run_id"] = re.sub(r"[^A-Za-z0-9._-]", "-", f"{prefix}-{factor}-{value}")
        spec["factor"], spec["value"] = factor, value
        specs.append(spec)
    return specs


def command(spec: dict, theorem: str, limit: float, passthrough: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "arena.cli",
        "run",
        "--model",
        spec["model"],
        "--theorem",
        theorem,
        "--run-id",
        spec["run_id"],
        "--limit-usd",
        f"{limit:g}",
        "--thinking",
        spec["thinking"],
        *(["--no-skill"] if spec["skill"] == "off" else []),
        *passthrough,
    ]


def execute(spec: dict, theorem: str, limit: float, passthrough: list[str], logs: Path) -> dict:
    with (logs / f"{spec['run_id']}.log").open("w") as log:
        proc = subprocess.run(
            command(spec, theorem, limit, passthrough), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True
        )
    row = {**spec, "exit_code": proc.returncode}
    directory = run_dir(spec["run_id"])
    config_path = directory / "run-config.json"
    row["packet_sha256"] = json.loads(config_path.read_text())["packet_sha256"] if config_path.exists() else None
    row["summary"] = build_summary(directory) if directory.exists() else None
    return row


def compare(rows: list[dict], expected_packet: str) -> dict:
    table = []
    for row in rows:
        summary = row["summary"] or {}
        cost, best = summary.get("cost", {}), (summary.get("progress", {}) or {}).get("best", {})

        def pick(key: str, best: dict = best):
            return (best.get(key) or {}).get("value")

        coherent = (summary.get("progress", {}) or {}).get("best_verified_candidate")
        table.append(
            {
                "run_id": row["run_id"],
                row["factor"]: row["value"],
                "exit_code": row["exit_code"],
                "stop_reason": summary.get("stop_reason"),
                "spent_usd": cost.get("spent_usd"),
                "remaining_usd": cost.get("remaining_usd"),
                "requests": cost.get("requests"),
                "evaluations": summary.get("evaluations"),
                "tool_results": (summary.get("tools") or {}).get("results"),
                "retries": cost.get("retries"),
                "spent_after_best_usd": cost.get("spent_after_best_usd"),
                "requests_after_best": cost.get("requests_after_best"),
                "best_candidate": coherent.get("candidate") if coherent else None,
                "best_tokens": coherent.get("tokens") if coherent else pick("tokens"),
                "best_heartbeats": coherent.get("heartbeats") if coherent else pick("heartbeats"),
                "best_proxy": coherent.get("proxy") if coherent else pick("proxy"),
                "best_estimated_proxy": pick("estimated_proxy"),
                "bookkeeping_and_rejected_pct": cost.get("bookkeeping_and_rejected_pct"),
                "cache_reuse_pct": (summary.get("cache") or {}).get("reuse_pct"),
                "tool_errors": (summary.get("tools") or {}).get("error_total"),
                "packet_matches": row["packet_sha256"] == expected_packet,
            }
        )
    return {"identical_packets": all(item["packet_matches"] for item in table), "runs": table}


def render(report: dict, factor: str) -> str:
    lines = [f"factor: {factor}; identical packets: {report['identical_packets']}"]
    for row in report["runs"]:
        lines.extend(
            [
                f"{row[factor]:>10}  ${row['spent_usd'] or 0:.4f}  req {row['requests']}  eval {row['evaluations']}  "
                f"tool results {row['tool_results']}  retries {row['retries']}  "
                f"best {row['best_candidate'] or 'none'}  "
                f"tokens {row['best_tokens']}  hb {row['best_heartbeats']}  proxy {row['best_proxy']}/"
                f"{row['best_estimated_proxy']}  overhead {row['bookkeeping_and_rejected_pct']}%  "
                f"cache {row['cache_reuse_pct']}%  post-best ${row['spent_after_best_usd']} "
                f"stop {row['stop_reason']}"
            ]
        )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ExperimentOptions:
    theorem: str
    prefix: str
    factor: str
    values: str
    model: str = "deepseek-v4.1-flash"
    thinking: str = "high"
    limit_usd: float = 0.5
    parallel: str = "1"
    dry_run: bool = False


def cli_execute(options: ExperimentOptions, passthrough: tuple[str, ...] = ()) -> int:
    if not 0 < options.limit_usd <= 2:
        print("--limit-usd must be above 0 and at most 2.00", file=sys.stderr)
        return 2
    try:
        specs = plan(options.factor, options.values.split(","), options.model, options.thinking, options.prefix)
        workers = parallelism(options.parallel, len(specs), available_memory_kb())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    clashes = [spec["run_id"] for spec in specs if run_dir(spec["run_id"]).exists()]
    if clashes:
        print(f"run IDs already exist: {', '.join(clashes)}", file=sys.stderr)
        return 2
    run_options = list(passthrough)
    expected = hashlib.sha256(packet(options.theorem, options.model).encode()).hexdigest()
    print(
        f"{len(specs)} runs varying {options.factor}; packet {expected[:12]}; {workers} at once; "
        f"limit ${options.limit_usd:g} each"
    )
    for spec in specs:
        print("  arena run " + " ".join(command(spec, options.theorem, options.limit_usd, run_options)[4:]))
    if options.dry_run:
        return 0
    blocked = preflight_block([spec["model"] for spec in specs])
    if blocked:
        print(blocked, file=sys.stderr)
        return 1
    out = ROOT / "runs" / "pi-budget" / f"{options.prefix}-matrix"
    out.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda spec: execute(spec, options.theorem, options.limit_usd, run_options, out), specs))
    report = {
        "theorem": options.theorem,
        "limit_usd": options.limit_usd,
        "expected_packet_sha256": expected,
        **compare(rows, expected),
    }
    (out / "matrix.json").write_text(json.dumps(report, indent=2) + "\n")
    text = render(report, options.factor)
    (out / "matrix.txt").write_text(text)
    print(text, end="")
    if not report["identical_packets"]:
        print("Packets differ between runs; the comparison is not valid.", file=sys.stderr)
        return 1
    return 0
