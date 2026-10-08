#!/usr/bin/env python3
"""Run a paid comparison campaign: theorem rows x models x N sequential replicates.

Each row gets one certified kickoff packet shared by all its runs. Nothing is spent unless a
passing Langfuse preflight receipt covers every model (run here, or a fresh one) and every row's
packet certifies with its mandatory sections. `--dry-run` prints the plan and worst-case cost.

    python tools/run_campaign.py --prefix v6c1 --rows Core.InitsUpdatesComm,fundamental_theorem_of_variational_calculus' \\
        --models gpt-6-luna,deepseek-v4.1-flash --cap 0.10 --replicates 1

Arguments after `--` are passed to every run (for example `--no-mcp`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.run_pi_budgeted import MODELS, THINKING_LEVELS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs" / "pi-budget"
RECEIPT_MAX_AGE_HOURS = 12.0
HELPER_DECL = re.compile(r"(?m)^\s*(?:private\s+|protected\s+)?(?:theorem|lemma)\s+\S+")


class CampaignAbort(Exception):
    """A pre-spend gate failed; nothing was run."""


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text)[:limit].strip("-._") or "row"


def plan(prefix: str, rows: list[str], models: list[str], replicates: int) -> list[dict]:
    """Replicate-major order: every row x model gets replicate k before any gets k+1."""
    if replicates < 1:
        raise ValueError("--replicates must be at least 1")
    if not rows or len(set(rows)) != len(rows) or not models or len(set(models)) != len(models):
        raise ValueError("rows and models must be non-empty and distinct")
    bad = [model for model in models if model not in MODELS]
    if bad:
        raise ValueError(f"unknown models {bad}; choose from {', '.join(MODELS)}")
    specs = [{"row": row, "model": model, "replicate": k,
              "run_id": f"{prefix}-{slug(row)}-{slug(model)}-r{k}"}
             for k in range(1, replicates + 1) for row in rows for model in models]
    if len({spec["run_id"] for spec in specs}) != len(specs):
        raise ValueError("run IDs collide; use shorter distinct row names or another prefix")
    return specs


def worst_case_usd(specs: list[dict], cap: float) -> float:
    return round(len(specs) * cap, 6)


def command(spec: dict, cap: float, thinking: str, passthrough: list[str]) -> list[str]:
    return [sys.executable, str(ROOT / "tools/run_pi_budgeted.py"), "--model", spec["model"],
            "--theorem", spec["row"], "--run-id", spec["run_id"], "--hard-cap-usd", f"{cap:g}",
            "--thinking", thinking, *passthrough]


def check_packets(rows: list[str], packet_fn=None) -> dict[str, str]:
    """Row -> sha256 of its certified packet. Any uncertifiable row aborts the campaign."""
    if packet_fn is None:
        from arena.campaign import packet as packet_fn  # noqa: PLC0415
    hashes, failures = {}, []
    for row in rows:
        try:
            text = packet_fn(row)
        except Exception as error:  # noqa: BLE001 - any failure to certify blocks spending
            failures.append(f"{row}: {error}")
            continue
        hashes[row] = hashlib.sha256(text.encode()).hexdigest()
    if failures:
        raise CampaignAbort("packet certification failed: " + "; ".join(failures))
    return hashes


def check_preflight(models: list[str], skip: bool, block_fn=None, receipt_fn=None, run_fn=None,
                    max_age_hours: float = RECEIPT_MAX_AGE_HOURS, now_fn=time.time) -> str:
    """Return how the gate was satisfied: 'skipped', 'fresh receipt' or 'ran preflight'."""
    if skip:
        return "skipped"
    if block_fn is None or receipt_fn is None:
        from arena.traces import preflight_block, receipt_path  # noqa: PLC0415
        block_fn, receipt_fn = block_fn or preflight_block, receipt_fn or receipt_path
    def fresh() -> bool:
        path = Path(receipt_fn())
        return path.is_file() and now_fn() - path.stat().st_mtime <= max_age_hours * 3600
    if block_fn(models) is None and fresh():
        return "fresh receipt"
    if run_fn is None:
        def run_fn(models: list[str]) -> int:
            return subprocess.run([sys.executable, str(ROOT / "tools/arena_preflight.py"),
                                   "--models", ",".join(models)], cwd=ROOT).returncode
    code = run_fn(models)
    reason = block_fn(models)
    if code != 0 or reason is not None:
        raise CampaignAbort(f"preflight failed: {reason or 'arena_preflight exited ' + str(code)}")
    return "ran preflight"


def helper_discovery(directory: Path, best_candidate: str | None) -> dict:
    """Model candidates that declare extra theorems/lemmas besides the target (helper discovery)."""
    ledger = []
    try:
        ledger = [json.loads(line) for line in (directory / "ledger.jsonl").read_text().splitlines() if line]
    except (OSError, ValueError):
        pass
    ids = [event["candidate_id"] for event in ledger if event.get("kind") == "candidate"]
    with_helpers, best_has = set(), False
    for index, event in enumerate(e for e in ledger if e.get("kind") == "candidate"):
        if event.get("origin") != "model":
            continue
        try:
            text = (directory / "proofs" / f"{event['candidate_id']}.lean").read_text()
        except OSError:
            continue
        if len(HELPER_DECL.findall(text)) > 1:  # the target theorem is the first declaration
            with_helpers.add(event["candidate_id"])
            best_has = best_has or best_candidate == f"#{ids.index(event['candidate_id']) + 1}"
    return {"candidates_with_helpers": len(with_helpers), "best_uses_helper": best_has}


def run_row(spec: dict, summary: dict | None, exit_code: int, packet_sha256: str | None,
            expected_packet: str, directory: Path | None = None) -> dict:
    summary = summary or {}
    cost, progress = summary.get("cost") or {}, summary.get("progress") or {}
    best = progress.get("best_verified_candidate")
    return {**spec, "exit_code": exit_code, "packet_matches": packet_sha256 == expected_packet,
            "stop_reason": summary.get("stop_reason"),
            "best_candidate": best.get("candidate") if best else None,
            "best_proxy": best.get("proxy") if best else None,
            "helpers": helper_discovery(directory, best.get("candidate") if best else None) if directory else None,
            "ideas_without_attempts": len(summary.get("ideas_without_attempts") or []),
            "routes": [{key: row[key] for key in ("route", "label", "attempts", "best_proxy")}
                       for row in summary.get("routes") or [] if row.get("attempts")],
            "tool_errors": (summary.get("tools") or {}).get("error_total"),
            "tool_errors_by_tool": (summary.get("tools") or {}).get("errors") or {},
            "cache_reuse_pct": (summary.get("cache") or {}).get("reuse_pct"),
            "bookkeeping_and_rejected_pct": cost.get("bookkeeping_and_rejected_pct"),
            "spent_usd": cost.get("spent_usd"), "unresolved_usd": cost.get("unresolved_usd"),
            "all_call_cost_usd": round((cost.get("spent_usd") or 0) + (cost.get("unresolved_usd") or 0), 6),
            "requests": cost.get("requests"), "retries": cost.get("retries")}


def _stats(values: list[float]) -> dict | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def aggregate(runs: list[dict], expected: dict[str, str]) -> dict:
    """Group run rows by (row, model); distributions are over replicates."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        groups.setdefault((run["row"], run["model"]), []).append(run)
    table = []
    for (row, model), items in groups.items():
        n = len(items)
        table.append({
            "row": row, "model": model, "replicates": n,
            "verified_runs": sum(item["best_proxy"] is not None for item in items),
            "best_proxy": _stats([item["best_proxy"] for item in items]),
            "helper_runs": sum(bool((item["helpers"] or {}).get("candidates_with_helpers")) for item in items),
            "best_uses_helper_runs": sum(bool((item["helpers"] or {}).get("best_uses_helper")) for item in items),
            "ideas_never_attempted": sum(item["ideas_without_attempts"] for item in items),
            "routes_tried": _stats([len(item.get("routes") or []) for item in items]),
            "single_route_runs": sum(len(item.get("routes") or []) <= 1 for item in items),
            "tool_errors": sum(item["tool_errors"] or 0 for item in items),
            "cache_reuse_pct": _stats([item["cache_reuse_pct"] for item in items]),
            "bookkeeping_and_rejected_pct": _stats([item["bookkeeping_and_rejected_pct"] for item in items]),
            "all_call_cost_usd": {**_stats([item["all_call_cost_usd"] for item in items]),
                                  "total": round(sum(item["all_call_cost_usd"] for item in items), 6)},
            "stop_reasons": {reason: sum(item["stop_reason"] == reason for item in items)
                             for reason in sorted({str(item["stop_reason"]) for item in items})},
            "packet_matches": all(item["packet_matches"] for item in items)})
    return {"identical_packets": all(item["packet_matches"] for item in runs),
            "expected_packets": expected, "groups": table, "runs": runs,
            "total_cost_usd": round(sum(item["all_call_cost_usd"] for item in runs), 6)}


def render(report: dict) -> str:
    def span(stats: dict | None, fmt: str = "{:g}") -> str:
        return "none" if not stats else "/".join(fmt.format(stats[key]) for key in ("min", "median", "max"))
    lines = [f"campaign: {len(report['runs'])} runs, all-call cost ${report['total_cost_usd']:.4f}; "
             f"identical packets: {report['identical_packets']}"]
    for g in report["groups"]:
        lines += [f"{g['row']} | {g['model']} | n={g['replicates']} (verified {g['verified_runs']})",
                  f"  best-verified proxy min/median/max: {span(g['best_proxy'])}",
                  f"  helper discovery: {g['helper_runs']} runs declared helpers, {g['best_uses_helper_runs']} in the best candidate",
                  f"  routes tried per run min/median/max: {span(g['routes_tried'])}; runs with a single route: {g['single_route_runs']}",
                  f"  ideas never attempted: {g['ideas_never_attempted']}; tool errors: {g['tool_errors']}",
                  f"  cache reuse %: {span(g['cache_reuse_pct'])}; bookkeeping+rejected %: {span(g['bookkeeping_and_rejected_pct'])}",
                  f"  all-call cost per problem min/median/max: {span(g['all_call_cost_usd'], '${:.4f}')} "
                  f"(total ${g['all_call_cost_usd']['total']:.4f})",
                  f"  stop reasons: {g['stop_reasons']}"]
    return "\n".join(lines) + "\n"


def execute(spec: dict, cap: float, thinking: str, passthrough: list[str], logs: Path, expected: str,
            run_fn=subprocess.run, summary_fn=None) -> dict:
    if summary_fn is None:
        from arena.summary import build_summary as summary_fn  # noqa: PLC0415
    directory = RUNS / spec["run_id"]
    with (logs / f"{spec['run_id']}.log").open("w") as log:
        proc = run_fn(command(spec, cap, thinking, passthrough), cwd=ROOT, stdout=log,
                      stderr=subprocess.STDOUT, text=True)
    config_path = directory / "run-config.json"
    packet_sha = json.loads(config_path.read_text()).get("packet_sha256") if config_path.exists() else None
    summary = summary_fn(directory) if directory.exists() else None
    return run_row(spec, summary, proc.returncode, packet_sha, expected, directory if directory.exists() else None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--rows", required=True, help="Comma-separated benchmark names")
    parser.add_argument("--models", required=True, help=f"Comma-separated: {', '.join(MODELS)}")
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--cap", type=float, default=3.0, help="Spend cap per run in USD (0.10-3.00); below 3 it is a soft cap on actual spend (the last request may overshoot), only 3 is a hard cap")
    parser.add_argument("--thinking", default="high", choices=THINKING_LEVELS)
    parser.add_argument("--skip-preflight", action="store_true", help="Explicitly skip the Langfuse preflight gate")
    parser.add_argument("--dry-run", action="store_true")
    args, passthrough = parser.parse_known_args(argv)
    passthrough = [item for item in passthrough if item != "--"]
    if not 0.1 <= args.cap <= 3:
        parser.error("--cap must be between 0.10 and 3.00")
    rows, models = [r for r in args.rows.split(",") if r], [m for m in args.models.split(",") if m]
    try:
        specs = plan(args.prefix, rows, models, args.replicates)
    except ValueError as error:
        parser.error(str(error))
    print(f"{len(specs)} runs ({len(rows)} rows x {len(models)} models x {args.replicates} replicates, sequential); "
          f"cap ${args.cap:g} each; worst case ${worst_case_usd(specs, args.cap):.2f}")
    for spec in specs:
        print(" ", " ".join(command(spec, args.cap, args.thinking, passthrough)[1:]))
    if args.dry_run:
        return 0
    clashes = [spec["run_id"] for spec in specs if (RUNS / spec["run_id"]).exists()]
    if clashes:
        parser.error(f"run IDs already exist: {', '.join(clashes)}")
    try:
        expected = check_packets(rows)
        print("preflight:", check_preflight(models, args.skip_preflight))
    except CampaignAbort as error:
        print(f"aborted before any paid run: {error}", file=sys.stderr)
        return 1
    out = RUNS / f"{args.prefix}-campaign"
    out.mkdir(parents=True)
    runs = [execute(spec, args.cap, args.thinking, passthrough, out, expected[spec["row"]]) for spec in specs]
    report = {"cap_usd": args.cap, "prefix": args.prefix, **aggregate(runs, expected)}
    (out / "campaign.json").write_text(json.dumps(report, indent=2) + "\n")
    text = render(report)
    (out / "campaign.txt").write_text(text)
    print(text, end="")
    if not report["identical_packets"]:
        print("Packets differ between runs; the comparison is not valid.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
