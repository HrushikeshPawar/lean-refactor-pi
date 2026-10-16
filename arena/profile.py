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

from arena import text as agent_text
from arena.engine import (
    ROOT,
    _proof_length,
    candidate_file,
    compile_version,
    measure_version,
    problem,
    run_lean,
    versions,
)
from arena.scoring import exchange_rates

LEAN_DIR = Path(__file__).with_name("lean")


MAX_DEPTH = 4
# not-model-facing: parser for structured output printed by the Lean profiler.
_ENTRY = re.compile(r"^ARENA_PROFILE (\d+) (\d+) (\d+) (\d+) (\d+) (tactic|term) (\d+)$", re.M)
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
    merged: dict[tuple[int, int, int, int, int, str], dict] = {}
    for line, column, depth, end, end_column, kind, heartbeats in _ENTRY.findall(output):
        key = (int(line) - shift, int(column), int(depth), int(end) - shift, int(end_column), kind)
        record = merged.setdefault(
            key,
            {
                "file_line": key[0],
                "column": key[1],
                "depth": key[2],
                "end_file_line": key[3],
                "end_column": key[4],
                "kind": kind,
                "hb": 0,
                "calls": 0,
            },
        )
        record["hb"] += int(heartbeats)
        record["calls"] += 1
    records = sorted(merged.values(), key=lambda r: (r["file_line"], r["column"], r["depth"]))
    for record in records:
        record["proof_line"] = record["file_line"] - start_line + 1
        record["end_proof_line"] = record["end_file_line"] - start_line + 1
    total = _TOTAL.search(output)
    return records, int(total[1]) if total else None


def _end(record: dict) -> tuple[int, int]:
    return record["end_file_line"], record.get("end_column", 10**6)


def attribute(records: list[dict]) -> None:
    """Fill `self_hb`: inclusive cost minus the cost of the tactics and stated terms directly inside."""
    for parent in records:
        inner = [
            child
            for child in records
            if child["depth"] == parent["depth"] + 1
            and (parent["file_line"], parent["column"]) < (child["file_line"], child["column"])
            and _end(child) <= _end(parent)
        ]
        parent["self_hb"] = max(0, parent["hb"] - sum(child["hb"] for child in inner))


_OPERATORS = [
    ":=",
    "!=",
    "&&",
    "-.",
    "->",
    "←",
    "..",
    "...",
    "::",
    ":>",
    "<;>",
    ";;",
    "==",
    "||",
    "=>",
    "<=",
    ">=",
    "⁻¹",
    "?_",
]


def _mask_comments(source: str) -> str:
    """Blank nested comments while preserving newlines and physical source coordinates."""
    out = list(source)
    i = depth = 0
    in_string = False
    while i < len(source):
        if in_string:
            if source[i] == "\\":
                i += 2
                continue
            if source[i] == '"':
                in_string = False
        elif depth:
            if source.startswith("/-", i):
                out[i : i + 2] = "  "
                depth += 1
                i += 2
                continue
            if source.startswith("-/", i):
                out[i : i + 2] = "  "
                depth -= 1
                i += 2
                continue
            if source[i] != "\n":
                out[i] = " "
        elif source.startswith("/-", i):
            out[i : i + 2] = "  "
            depth = 1
            i += 2
            continue
        elif source.startswith("--", i):
            while i < len(source) and source[i] != "\n":
                out[i] = " "
                i += 1
            continue
        elif source[i] == '"':
            in_string = True
        i += 1
    return "".join(out)


def _line_token_counts(proof: str, whole_tokens: int) -> dict[int, int] | None:
    """Map the pinned competition lexer count to physical proof lines, failing closed on drift."""
    from arena.context import _proof_boundary

    boundary = _proof_boundary(proof, 1)
    if boundary is None:
        return None
    line, column = boundary
    column += 2  # The official proof tokenizer starts immediately after the declaration's `:=`.
    cleaned = _mask_comments(proof).splitlines()
    counts: dict[int, int] = {}
    for index in range(line - 1, len(cleaned)):
        text = cleaned[index][column:] if index == line - 1 else cleaned[index]
        tokens: list[str] = []
        token = ""
        for char in text:
            if char == " ":
                if token:
                    tokens.append(token)
                    token = ""
            elif char.isalnum() or char in "._'":
                token += char
            else:
                if token:
                    tokens.append(token)
                    token = ""
                tokens.append(char)
        if token:
            tokens.append(token)
        rendered = " ".join(tokens)
        for operator in _OPERATORS:
            spaced = " ".join(operator)
            rendered = rendered.replace(spaced, operator)
        count = len(rendered.split(" ")) if rendered else 0
        if count:
            counts[index + 1] = count
    if sum(counts.values()) != whole_tokens:
        return None
    return counts


def summarize(
    records: list[dict],
    source_lines: list[str],
    measured: int | None,
    instrumented: int | None,
    line_tokens: dict[int, int] | None = None,
    reference_tokens: int | None = None,
    reference_heartbeats: int | None = None,
    proof_lines: list[str] | None = None,
    file_start_line: int | None = None,
    proof_tokens: int | None = None,
) -> dict:
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
        lines = (
            str(record["proof_line"])
            if record["end_proof_line"] == record["proof_line"]
            else f"{record['proof_line']}-{record['end_proof_line']}"
        )
        text = source_lines[record["file_line"] - 1].strip() if 0 < record["file_line"] <= len(source_lines) else ""
        entry = {
            "lines": lines,
            "file_line": record["file_line"],
            "end_file_line": record["end_file_line"],
            "proof_line": record["proof_line"],
            "end_proof_line": record["end_proof_line"],
            "depth": record["depth"],
            "kind": record.get("kind", "tactic"),
            "column": record["column"],
            "end_column": record.get("end_column"),
            "hb": record["hb"],
            "self_hb": record["self_hb"],
            "share_pct": share,
            "text": text[:90],
        }
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
        top.append(
            {
                "lines": (
                    str(record["proof_line"])
                    if record["end_proof_line"] == record["proof_line"]
                    else f"{record['proof_line']}-{record['end_proof_line']}"
                ),
                "self_hb": record["self_hb"],
                "text": (
                    source_lines[record["file_line"] - 1].strip()[:90]
                    if 0 < record["file_line"] <= len(source_lines)
                    else ""
                ),
                "cumulative_share_pct": round(running, 1),
            }
        )
    token_total = sum(line_tokens.values()) if line_tokens is not None else None
    token_ok = line_tokens is not None and proof_tokens is not None and token_total == proof_tokens
    hotspots: list[dict] = []
    attributed_by_line: dict[int, int] = {}
    spans_by_line: dict[int, list[dict]] = {}
    for record in records:
        attributed_by_line[record["proof_line"]] = attributed_by_line.get(record["proof_line"], 0) + record["self_hb"]
        spans_by_line.setdefault(record["proof_line"], []).append(
            {
                "file_line": record["file_line"],
                "end_file_line": record["end_file_line"],
                "proof_line": record["proof_line"],
                "end_proof_line": record["end_proof_line"],
                "depth": record["depth"],
                "column": record["column"],
            }
        )
    if file_start_line is None and records:
        file_start_line = min(r["file_line"] - r["proof_line"] + 1 for r in records)
    line_profile = []
    if proof_lines is not None and file_start_line is not None:
        line_profile = [
            {
                "proof_line": i,
                "file_line": file_start_line + i - 1,
                "self_hb": attributed_by_line.get(i, 0),
                "tokens": line_tokens.get(i, 0) if token_ok else None,
                "tactic_spans": spans_by_line.get(i, []),
                "text": text.strip(),
            }
            for i, text in enumerate(proof_lines, start=1)
        ]
    rates_ok = reference_tokens and reference_heartbeats
    if token_ok and rates_ok:
        by_line: dict[int, dict] = {}
        for record in records:
            item = by_line.setdefault(
                record["proof_line"],
                {
                    "proof_line": record["proof_line"],
                    "file_line": record["file_line"],
                    "end_proof_line": record["end_proof_line"],
                    "end_file_line": record["end_file_line"],
                    "self_hb": 0,
                    "tokens": 0,
                    "tactic_spans": [],
                },
            )
            item["self_hb"] += record["self_hb"]
            item["end_proof_line"] = max(item["end_proof_line"], record["end_proof_line"])
            item["end_file_line"] = max(item["end_file_line"], record["end_file_line"])
            item["tactic_spans"].append(
                {
                    "file_line": record["file_line"],
                    "end_file_line": record["end_file_line"],
                    "proof_line": record["proof_line"],
                    "end_proof_line": record["end_proof_line"],
                    "depth": record["depth"],
                    "column": record["column"],
                }
            )
        # Each token line goes to the innermost tactic span covering it, aggregated at that span's start line.
        offset = (file_start_line - 1) if file_start_line is not None else None
        for proof_line, count in line_tokens.items():
            covering = [r for r in records if r["proof_line"] <= proof_line <= r["end_proof_line"]]
            owner = max(
                covering,
                key=lambda r: (r["depth"], -(r["end_proof_line"] - r["proof_line"]), r["proof_line"]),
                default=None,
            )
            start = owner["proof_line"] if owner else proof_line
            item = by_line.setdefault(
                start,
                {
                    "proof_line": start,
                    "file_line": None if offset is None else start + offset,
                    "end_proof_line": start,
                    "end_file_line": None if offset is None else start + offset,
                    "self_hb": 0,
                    "tokens": 0,
                    "tactic_spans": [],
                },
            )
            item["tokens"] += count
            if proof_line > item["end_proof_line"]:
                item["end_proof_line"] = proof_line
                item["end_file_line"] = None if offset is None else proof_line + offset
        for item in by_line.values():
            token_count = item["tokens"]
            item["baseline_cost_points"] = round(
                token_count * 100 / reference_tokens / 3 + item["self_hb"] * 100 / reference_heartbeats / 3, 4
            )
            hotspots.append(item)
        hotspots.sort(key=lambda item: (-item["baseline_cost_points"], item["proof_line"]))
        hotspots = hotspots[:10]
    return {
        "profiled_total": profiled,
        "measured_total": measured,
        "instrumented_total": instrumented,
        "unattributed": (measured - profiled) if measured is not None else None,
        "entries": entries,
        "omitted_entries": omitted,
        "top_self_cost": top,
        "line_profile": line_profile,
        "line_tokens": line_tokens if token_ok else None,
        "line_tokens_total": token_total if token_ok else None,
        "token_attribution_available": bool(token_ok),
        "hotspots": hotspots,
        "hotspot_label": "top-ten score-equivalent cost (not predicted savings)",  # log: internal record # not-model-facing
        "unit": "heartbeats; hb includes nested tactics",  # log: internal record # not-model-facing
    }


def _instrumented(
    row: dict, proof: str, version: str, commit: str, depth: int, lane: str = "model"
) -> tuple[list[dict], int | None, dict, str]:
    built = candidate_file(row, proof, version, commit)
    inserted = preamble(depth)
    text = built["text"][: built["head"]] + inserted + built["text"][built["head"] :]
    ran = run_lean(row, built["path"], text, prefix_end=built["head"], lane=lane)
    if ran is None:
        raise ValueError(agent_text.render("messages/errors.profile_timeout"))
    returncode, output = ran
    shift = inserted.count("\n")
    records, total = parse_profile(output, shift, built["start_line"])
    if returncode != 0 or not records:
        raise ValueError(
            agent_text.render(
                "messages/errors.profile_compile_failed",
                detail=(next((line for line in output.splitlines() if "error" in line), output[:160]) or "no output")[
                    :200
                ],
            )
        )
    return records, total, built, output


def profile(name: str, proof: str, measured: int | None = None, lane: str = "model") -> dict:
    """Profile a sorry-free, compiling proof on the primary toolchain."""
    row = problem(name)
    version, commit = measure_version(row)
    if re.search(r"\bsorry\b", proof):
        raise ValueError(agent_text.render("messages/errors.profile_requires_complete"))
    granularity, failures = "tactic", []
    result = None
    for depth in (MAX_DEPTH, 0):
        try:
            result = _instrumented(row, proof, version, commit, depth, lane)
            granularity = "tactic" if depth else "top_level"
            break
        except ValueError as error:
            failures.append(str(error))
    if result is None:
        reference = compile_version(row, proof, version, commit, measure=True, lane=lane)
        if not reference["passed"]:
            headlines = reference.get("error_headlines") or [reference.get("error", "compile failed")]
            raise ValueError(agent_text.render("messages/errors.profile_proof_compile", headline=headlines[0]))
        raise ValueError(agent_text.render("messages/errors.profile_instrumentation_failed", detail=failures[-1]))
    records, instrumented, built, _ = result
    if measured is None:
        measure = compile_version(row, proof, version, commit, measure=True, lane=lane)
        measured = measure.get("heartbeats")
    whole_tokens = _proof_length(proof, row.get("statement"))
    token_lines = _line_token_counts(proof, whole_tokens)
    rates = exchange_rates(name, len(versions(row)))
    summary = summarize(
        records,
        built["text"].splitlines(),
        measured,
        instrumented,
        token_lines,
        rates["reference_tokens"],
        rates["reference_heartbeats"],
        proof.splitlines(),
        built["start_line"],
        whole_tokens,
    )
    summary["tokens"] = whole_tokens if whole_tokens < 10**9 else None
    return {
        "ok": True,
        "granularity": granularity,
        "version": version,
        **summary,
        "note": _degraded_note(failures),
    }


def _degraded_note(failures: list) -> str | None:
    if not failures:
        return None
    return f"Profile degraded to the outermost tactics: {failures[0]}"  # log: internal record # not-model-facing


def heartbeat_floor(name: str) -> dict:
    """Cost of elaborating the statement alone (stub proof), cached per row and commit."""
    row = problem(name)
    version, commit = measure_version(row)
    cache = ROOT / "runs" / "cache" / "floor.json"
    key = f"{name}@{commit}"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    if key not in known:
        stub = row["statement"] + " := by\n  sorry"
        outcome = compile_version(row, stub, version, commit, measure=True)
        known[key] = {
            "heartbeats": outcome.get("heartbeats"),
            "version": version,
            "method": "statement elaborated with a sorry proof",  # log: internal record # not-model-facing
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(known, indent=1))
    return known[key]


def cached_heartbeat_floor(name: str) -> int | None:
    """The statement floor if `heartbeat_floor` already cached it for this row and commit; never starts Lean."""
    row = problem(name)
    _, commit = measure_version(row)
    cache = ROOT / "runs" / "cache" / "floor.json"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    entry = known.get(f"{name}@{commit}") or {}
    return entry.get("heartbeats")
