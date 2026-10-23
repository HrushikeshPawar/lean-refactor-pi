#!/usr/bin/env python3
"""Summarize saved multi-pin endpoint evidence; reads ledgers only and never launches Lean."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def compat_of(event: dict) -> dict:
    return (event.get("result") or {}).get("compat") or {}


def error_kind(entries: dict) -> str:
    encoded = json.dumps(entries, ensure_ascii=False).lower()
    if "timed out" in encoded or "timeout" in encoded:
        return "timeout"
    if any(
        isinstance(entry, dict)
        and (
            any(isinstance(diag, dict) and diag.get("severity") == "error" for diag in (entry.get("diagnostics") or []))
            or entry.get("passed") is False
        )
        for entry in entries.values()
    ):
        return "proof_error"
    return "unknown"


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=script_dir.parents[2], help="repository root")
    parser.add_argument("--output", type=Path, default=script_dir / "scan-results.json")
    args = parser.parse_args()
    root = args.root.resolve()

    ledger_files = sorted((root / "runs/pi-budget").glob("*/ledger.jsonl"))
    rows: dict[str, dict] = defaultdict(lambda: {"pins": set(), "full": [], "fast": [], "cold": []})
    ledger_hashes = []
    uninitialized = []

    for path in ledger_files:
        raw = path.read_bytes()
        ledger_hashes.append(
            {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
        )
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        init = next((entry for entry in entries if entry.get("kind") == "init" and entry.get("theorem")), None)
        if init is None:
            uninitialized.append(path.relative_to(root).as_posix())
            continue
        theorem = init["theorem"]
        row = rows[theorem]
        row["pins"].update(version for version, _commit in init.get("versions") or [])
        run_id = path.parent.name
        for entry in entries:
            if entry.get("kind") == "evaluation" and entry.get("mode") in ("fast", "full"):
                row[entry["mode"]].append((run_id, entry))
            elif entry.get("kind") == "cold_verification":
                row["cold"].append((run_id, entry))

    theorem_results = {}
    for theorem, row in sorted(rows.items()):
        pins = sorted(row["pins"], key=version_key)
        if len(pins) < 3:
            continue
        endpoints = {pins[0], pins[-1]}
        middle = set(pins) - endpoints
        full_failures = []
        full_patterns = Counter()
        failed_pins = Counter()
        fast_failures = []
        fast_failed_versions = Counter()
        endpoint_pass = endpoint_pass_middle_fail = endpoint_pass_missing_middle = 0
        full_missing = full_unknown = 0

        for run_id, event in row["full"]:
            compat = compat_of(event)
            passed = {
                version: entry.get("passed")
                for version, entry in compat.items()
                if isinstance(entry, dict)
            }
            missing = sorted(set(pins) - set(compat))
            unknown = [version for version in pins if passed.get(version) not in (True, False)]
            full_missing += len(missing)
            full_unknown += len(unknown)
            full_patterns["".join("P" if passed.get(v) is True else "F" if passed.get(v) is False else "?" for v in pins)] += 1
            failed = [version for version in pins if passed.get(version) is False]
            for version in failed:
                failed_pins[version] += 1
            if failed:
                full_failures.append(
                    {
                        "run_id": run_id,
                        "candidate_id": event.get("candidate_id"),
                        "failed_versions": failed,
                        "failure_kind": error_kind({v: compat[v] for v in failed if v in compat}),
                    }
                )
            if all(passed.get(version) is True for version in endpoints):
                endpoint_pass += 1
                if any(passed.get(version) is False for version in middle):
                    endpoint_pass_middle_fail += 1
                elif set(missing) & middle or set(unknown) & middle:
                    endpoint_pass_missing_middle += 1

        for run_id, event in row["fast"]:
            compat = compat_of(event)
            failed = [
                version
                for version, entry in compat.items()
                if isinstance(entry, dict) and entry.get("passed") is False
            ]
            if failed:
                fast_failures.append(
                    {
                        "run_id": run_id,
                        "candidate_id": event.get("candidate_id"),
                        "failed_versions": failed,
                        "failure_kind": error_kind({v: compat[v] for v in failed}),
                    }
                )
                fast_failed_versions.update(failed)

        full_by_candidate = {
            (run_id, event.get("candidate_id")): event for run_id, event in row["full"]
        }
        fast_failure_keys = {
            (failure["run_id"], failure["candidate_id"]) for failure in fast_failures
        }
        same_run_full_for_fast_failure = len(fast_failure_keys & set(full_by_candidate))
        cold_disagreements = []
        for run_id, cold in row["cold"]:
            full = full_by_candidate.get((run_id, cold.get("candidate_id")))
            if full is None:
                continue
            full_compat = compat_of(full)
            cold_passed = cold.get("passed") or {}
            mismatches = [
                version
                for version, result in cold_passed.items()
                if version in full_compat
                and isinstance(full_compat[version], dict)
                and full_compat[version].get("passed") != result
            ]
            if mismatches:
                cold_compat = cold.get("compat") or {}
                cold_disagreements.append(
                    {
                        "run_id": run_id,
                        "candidate_id": cold.get("candidate_id"),
                        "mismatched_versions": mismatches,
                        "cold_failure_kind": error_kind(
                            {v: cold_compat[v] for v in mismatches if v in cold_compat}
                        ),
                        "cold_errors": {
                            v: (cold_compat.get(v) or {}).get("error") for v in mismatches
                        },
                    }
                )

        theorem_results[theorem] = {
            "pins_oldest_to_newest": pins,
            "full_events": len(row["full"]),
            "full_failed_events": len(full_failures),
            "full_failed_pin_results": sum(failed_pins.values()),
            "full_failed_pin_results_by_version": dict(sorted(failed_pins.items(), key=lambda item: version_key(item[0]))),
            "full_missing_pin_keys": full_missing,
            "full_unknown_pass_results": full_unknown,
            "full_outcome_patterns": dict(sorted(full_patterns.items())),
            "endpoint_pass_full_events": endpoint_pass,
            "endpoint_pass_middle_failure_events": endpoint_pass_middle_fail,
            "endpoint_pass_missing_middle_events": endpoint_pass_missing_middle,
            "fast_events": len(row["fast"]),
            "fast_failed_events": len(fast_failures),
            "fast_failed_candidate_ids": len({item["candidate_id"] for item in fast_failures}),
            "fast_failed_versions": dict(sorted(fast_failed_versions.items(), key=lambda item: version_key(item[0]))),
            "fast_failed_failure_kinds": dict(Counter(item["failure_kind"] for item in fast_failures)),
            "fast_failures_with_same_run_full_event": same_run_full_for_fast_failure,
            "cold_events": len(row["cold"]),
            "same_run_full_cold_disagreements": cold_disagreements,
            "full_failure_examples": full_failures,
        }

    multi_pin = list(theorem_results.values())
    totals = {
        "multi_pin_theorems": len(multi_pin),
        "full_events": sum(row["full_events"] for row in multi_pin),
        "full_failed_events": sum(row["full_failed_events"] for row in multi_pin),
        "full_failed_pin_results": sum(row["full_failed_pin_results"] for row in multi_pin),
        "full_missing_pin_keys": sum(row["full_missing_pin_keys"] for row in multi_pin),
        "full_unknown_pass_results": sum(row["full_unknown_pass_results"] for row in multi_pin),
        "endpoint_pass_full_events": sum(row["endpoint_pass_full_events"] for row in multi_pin),
        "endpoint_pass_middle_failure_events": sum(row["endpoint_pass_middle_failure_events"] for row in multi_pin),
        "endpoint_pass_missing_middle_events": sum(row["endpoint_pass_missing_middle_events"] for row in multi_pin),
        "fast_events": sum(row["fast_events"] for row in multi_pin),
        "fast_failed_events": sum(row["fast_failed_events"] for row in multi_pin),
        "fast_failed_candidate_ids_by_theorem": {
            theorem: row["fast_failed_candidate_ids"]
            for theorem, row in theorem_results.items()
            if row["fast_failed_events"]
        },
        "cold_events": sum(row["cold_events"] for row in multi_pin),
        "same_run_full_cold_disagreements": sum(
            len(row["same_run_full_cold_disagreements"]) for row in multi_pin
        ),
    }
    result = {
        "method": {
            "ledger_glob": "runs/pi-budget/*/ledger.jsonl",
            "expected_pins": "union of initialized saved pin lists by theorem, checked against benchmark/original/warmup.jsonl",
            "endpoint_order": "numeric Lean version order; endpoints are oldest and newest",
            "full_outcome": "missing pin key or non-Boolean passed value is unknown, never a pass",
            "cold_match": "same run directory and exact candidate_id",
            "lean_or_provider_calls": 0,
        },
        "input": {
            "ledger_file_count": len(ledger_files),
            "initialized_ledger_count": len(ledger_files) - len(uninitialized),
            "ledgers_without_theorem_init": uninitialized,
            "ledger_sha256": ledger_hashes,
        },
        "totals": totals,
        "theorems": theorem_results,
    }
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
