#!/usr/bin/env python3
"""Certify provisioned benchmark rows: run each reference proof through fast and full evaluation.

A row is certified when its reference compiles on every listed version, the local token count equals
the published one, the local heartbeat count is within a tolerance of the published denominator, and
its kickoff packet builds (render_packet raises when a required section or name cannot be certified).
Rows whose environments are not provisioned are reported, not failed (use --require-all to fail them).

    python tools/arena_certify.py                       # every row
    python tools/arena_certify.py --rows Core.InitsUpdatesComm --tolerance 0.05
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena import environments  # noqa: E402
from arena.context import render_packet  # noqa: E402
from arena.engine import BENCHMARK, evaluate, problem  # noqa: E402
from arena.scoring import reference  # noqa: E402


def all_rows() -> list[str]:
    return [json.loads(line)["name"] for line in BENCHMARK.read_text(encoding="utf-8").splitlines() if line.strip()]


def certify(name: str, tolerance: float = 0.05) -> dict:
    row = problem(name)
    listed = environments.provisioned(row)
    missing = [{"version": version, "commit": commit} for version, commit, path in listed if path is None]
    if missing:
        return {"name": name, "status": "unprovisioned", "missing": missing}
    try:
        fast = evaluate(name, row["src"], "fast")
        full = evaluate(name, row["src"], "full")
    except (ValueError, FileNotFoundError) as error:
        return {"name": name, "status": "failed", "reasons": [str(error)[:200]]}
    published_tokens, published_heartbeats = reference(name)
    heartbeats = full.get("heartbeat")
    drift = abs(heartbeats - published_heartbeats) / published_heartbeats if heartbeats is not None else None
    reasons = []
    try:
        packet_chars = len(render_packet(name))
    except (ValueError, FileNotFoundError, KeyError) as error:
        packet_chars = None
        reasons.append(f"kickoff packet is not certifiable: {str(error)[:200]}")
    failing = [version for version, info in full["compat"].items() if not info.get("passed")]
    if failing:
        reasons.append(f"the reference does not compile on {', '.join(failing)}")
    if full["tokens"] != published_tokens:
        reasons.append(f"tokens {full['tokens']} differ from the published {published_tokens}")
    if drift is None:
        reasons.append("heartbeats were not measured")
    elif drift > tolerance:
        reasons.append(f"heartbeats {heartbeats} drift {drift:.1%} from the published {published_heartbeats}")
    return {"name": name, "status": "failed" if reasons else "certified", "reasons": reasons,
            "tokens": {"local": full["tokens"], "published": published_tokens},
            "heartbeats": {"local": heartbeats, "published": published_heartbeats,
                           "drift_pct": None if drift is None else round(100 * drift, 2),
                           "measured_on": full.get("measured_on")},
            "compat": {version: bool(info.get("passed")) for version, info in full["compat"].items()},
            "packet_chars": packet_chars,
            "fast_matches_full_heartbeats": fast.get("heartbeat") == heartbeats,
            "reference_proxy": full.get("local_proxy")}


def render(results: list[dict]) -> str:
    lines = []
    for item in results:
        if item["status"] == "unprovisioned":
            versions = ", ".join(f"{m['version']}@{m['commit'][:8]}" for m in item["missing"])
            lines.append(f"{'unprovisioned':>13}  {item['name']}  (missing {versions})")
        elif item["status"] == "failed" and "tokens" not in item:
            lines.append(f"{'FAILED':>13}  {item['name']}  {'; '.join(item['reasons'])}")
        else:
            beats, tokens = item["heartbeats"], item["tokens"]
            lines.append(f"{item['status'].upper():>13}  {item['name']}  tokens {tokens['local']}/{tokens['published']}  "
                         f"hb {beats['local']}/{beats['published']} ({beats['drift_pct']}%)  "
                         f"compat {sum(item['compat'].values())}/{len(item['compat'])}  packet {item['packet_chars']}"
                         + (f"  — {'; '.join(item['reasons'])}" if item["reasons"] else ""))
    counts = {status: sum(1 for item in results if item["status"] == status)
              for status in ("certified", "failed", "unprovisioned")}
    return "\n".join(lines) + f"\n{counts['certified']} certified, {counts['failed']} failed, " \
                              f"{counts['unprovisioned']} unprovisioned\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", help="Comma-separated row names (default: every row)")
    parser.add_argument("--tolerance", type=float, default=0.05, help="Allowed heartbeat drift from the published value")
    parser.add_argument("--json", type=Path, help="Write the full results here")
    parser.add_argument("--require-all", action="store_true", help="Treat unprovisioned rows as failures")
    args = parser.parse_args()
    names = args.rows.split(",") if args.rows else all_rows()
    results = [certify(name, args.tolerance) for name in names]
    print(render(results), end="")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    bad = any(item["status"] == "failed" or (args.require_all and item["status"] == "unprovisioned")
              for item in results)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
