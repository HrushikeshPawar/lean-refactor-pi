"""Per-tactic heartbeat profile of a compiling proof.

The profiler is a Lean command wrapper in the same style as the one used for scoring:
it rewrites the theorem's syntax tree so every tactic in every tactic sequence runs
inside `arena_hb_tac`, which records the heartbeat delta around its evaluation (divided
by 1000, like the scoring wrapper). The instrumented file is scratch only; nothing here
touches candidates. If the full instrumentation fails the profile degrades to the
outermost tactic sequence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from arena.engine import (ROOT, candidate_file, compile_version, problem,
                          run_lean, versions)

LEAN_DIR = Path(__file__).with_name("lean")


MAX_DEPTH = 4
_ENTRY = re.compile(r"^ARENA_PROFILE (\d+) (\d+) (\d+) (\d+) (\d+)$", re.M)
_TOTAL = re.compile(r"^ARENA_PROFILE_TOTAL (\d+)$", re.M)
ENTRY_LIMIT = 60
MIN_SHARE = 0.5


def preamble(max_depth: int) -> str:
    return (LEAN_DIR / "profile.lean").read_text().replace("@@MAX_DEPTH@@", str(max_depth))


def parse_profile(output: str, shift: int, start_line: int) -> tuple[list[dict], int | None]:
    """Instrumented output -> aggregated tactic records and the instrumented command total.

    `shift` is the number of lines the instrumentation added before the theorem, so
    reported lines map back onto the candidate file.
    """
    merged: dict[tuple[int, int, int, int], dict] = {}
    for line, column, depth, end, heartbeats in _ENTRY.findall(output):
        key = (int(line) - shift, int(column), int(depth), int(end) - shift)
        record = merged.setdefault(key, {"file_line": key[0], "column": key[1], "depth": key[2],
                                         "end_file_line": key[3], "hb": 0, "calls": 0})
        record["hb"] += int(heartbeats)
        record["calls"] += 1
    records = sorted(merged.values(), key=lambda r: (r["file_line"], r["column"], r["depth"]))
    for record in records:
        record["proof_line"] = record["file_line"] - start_line + 1
        record["end_proof_line"] = record["end_file_line"] - start_line + 1
    total = _TOTAL.search(output)
    return records, int(total[1]) if total else None


def attribute(records: list[dict]) -> None:
    """Fill `self_hb`: inclusive cost minus the cost of the tactics directly inside."""
    for parent in records:
        inner = [child for child in records
                 if child["depth"] == parent["depth"] + 1
                 and (parent["file_line"], parent["column"]) < (child["file_line"], child["column"])
                 and child["end_file_line"] <= parent["end_file_line"]]
        parent["self_hb"] = max(0, parent["hb"] - sum(child["hb"] for child in inner))


def summarize(records: list[dict], source_lines: list[str], measured: int | None,
              instrumented: int | None) -> dict:
    """Shape a profile for the model: totals, source-ordered entries and the top self costs."""
    attribute(records)
    top_level = [r for r in records if r["depth"] == 0]
    profiled = sum(r["hb"] for r in top_level)
    basis = measured or instrumented or profiled or 1
    entries = []
    for record in records:
        share = round(100 * record["hb"] / basis, 1)
        if record["depth"] > 0 and share < MIN_SHARE:
            continue
        lines = (str(record["proof_line"]) if record["end_proof_line"] == record["proof_line"]
                 else f"{record['proof_line']}-{record['end_proof_line']}")
        text = source_lines[record["file_line"] - 1].strip() if 0 < record["file_line"] <= len(source_lines) else ""
        entry = {"lines": lines, "depth": record["depth"], "hb": record["hb"], "self_hb": record["self_hb"],
                 "share_pct": share, "text": text[:90]}
        if record["calls"] > 1:
            entry["calls"] = record["calls"]
        entries.append(entry)
    omitted = 0
    if len(entries) > ENTRY_LIMIT:
        keep = sorted(range(len(entries)), key=lambda i: -entries[i]["hb"])[:ENTRY_LIMIT]
        omitted = len(entries) - ENTRY_LIMIT
        entries = [entries[i] for i in sorted(keep)]
    running = 0.0
    top = []
    for record in sorted(records, key=lambda r: -r["self_hb"])[:5]:
        running += 100 * record["self_hb"] / basis
        top.append({"lines": (str(record["proof_line"]) if record["end_proof_line"] == record["proof_line"]
                              else f"{record['proof_line']}-{record['end_proof_line']}"),
                    "self_hb": record["self_hb"],
                    "text": (source_lines[record["file_line"] - 1].strip()[:90]
                             if 0 < record["file_line"] <= len(source_lines) else ""),
                    "cumulative_share_pct": round(running, 1)})
    return {"profiled_total": profiled, "measured_total": measured, "instrumented_total": instrumented,
            "unattributed": (measured - profiled) if measured is not None else None,
            "entries": entries, "omitted_entries": omitted, "top_self_cost": top,
            "unit": "heartbeats (the scoring unit, raw / 1000); hb is inclusive of nested tactics"}


def _instrumented(row: dict, proof: str, version: str, commit: str, depth: int) -> tuple[list[dict], int | None, dict, str]:
    built = candidate_file(row, proof, version, commit)
    inserted = preamble(depth)
    text = built["text"][:built["head"]] + inserted + built["text"][built["head"]:]
    ran = run_lean(row, built["path"], text)
    if ran is None:
        raise ValueError("Lean timed out while profiling")
    returncode, output = ran
    shift = inserted.count("\n")
    records, total = parse_profile(output, shift, built["start_line"])
    if returncode != 0 or not records:
        raise ValueError("instrumented compile failed: " + (next(
            (line for line in output.splitlines() if "error" in line), output[:160]) or "no output")[:200])
    return records, total, built, output


def profile(name: str, proof: str, measured: int | None = None) -> dict:
    """Profile a sorry-free, compiling proof on the primary toolchain."""
    row = problem(name)
    version, commit = versions(row)[0]
    if re.search(r"\bsorry\b", proof):
        raise ValueError("Profiling needs a proof without sorry; finish the draft first")
    granularity, failures = "tactic", []
    result = None
    for depth in (MAX_DEPTH, 0):
        try:
            result = _instrumented(row, proof, version, commit, depth)
            granularity = "tactic" if depth else "top_level"
            break
        except ValueError as error:
            failures.append(str(error))
    if result is None:
        reference = compile_version(row, proof, version, commit, measure=True)
        if not reference["passed"]:
            headlines = reference.get("error_headlines") or [reference.get("error", "compile failed")]
            raise ValueError("The proof does not compile, so it cannot be profiled: " + headlines[0])
        raise ValueError("Profiling could not instrument this proof: " + failures[-1])
    records, instrumented, built, _ = result
    if measured is None:
        measure = compile_version(row, proof, version, commit, measure=True)
        measured = measure.get("heartbeats")
    summary = summarize(records, built["text"].splitlines(), measured, instrumented)
    return {"ok": True, "granularity": granularity, "version": version, **summary,
            "note": ("Profile degraded to the outermost tactics: " + failures[0]) if failures else None}


def heartbeat_floor(name: str) -> dict:
    """Cost of elaborating the statement alone (stub proof), cached per row and commit."""
    row = problem(name)
    version, commit = versions(row)[0]
    cache = ROOT / "runs" / "cache" / "floor.json"
    key = f"{name}@{commit}"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    if key not in known:
        stub = row["statement"] + " := by\n  sorry"
        outcome = compile_version(row, stub, version, commit, measure=True)
        known[key] = {"heartbeats": outcome.get("heartbeats"), "version": version,
                      "method": "statement elaborated with a sorry proof"}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1))
    return known[key]
