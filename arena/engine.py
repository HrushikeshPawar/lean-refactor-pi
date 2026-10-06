"""Fail-closed proof evaluation against immutable benchmark source.

Heartbeat and scalar scoring remain unavailable until the local measurement
matches the Arena worker. Compilation and token counts are still useful gates.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmark/original/warmup.jsonl"
UPSTREAM_CHECKER = ROOT / "vendor/lean-refactor/lean_refactor/cc_agent/tools/check_proof.py"
HEARTBEAT_WRAPPER = '''open Lean Elab Command in
elab "arena_measure_heartbeats " cmd:command : command => do
  let t0 ← IO.getNumHeartbeats
  try
    elabCommand
      (← `(command|
        set_option Elab.async false in
        set_option maxHeartbeats 0 in
        $cmd))
  finally
    let t1 ← IO.getNumHeartbeats
    logInfo m!"ARENA_HEARTBEATS {(t1 - t0) / 1000}"

arena_measure_heartbeats
'''
WRAPPER_LINES = HEARTBEAT_WRAPPER.count("\n")


def _proof_length(proof: str) -> int:
    spec = importlib.util.spec_from_file_location("pinned_check_proof", UPSTREAM_CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Pinned proof utility is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    length = module._proof_length(proof)
    if length >= 10**9:
        raise ValueError("Pinned proof utility could not parse the candidate")
    return length


def problem(name: str) -> dict:
    for line in BENCHMARK.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["name"] == name:
            return row
    raise ValueError(f"Unknown benchmark theorem: {name}")


def versions(row: dict) -> list[tuple[str, str]]:
    return [(version, commit) for pair in row["version_info"] for version, commit in pair.items()]


def validate_proof(row: dict, proof: str, allow_sorry: bool = False) -> int:
    statement = row["statement"]
    if not proof.startswith(statement) or not re.match(r"\s*:=", proof[len(statement):]):
        raise ValueError("STATEMENT_MODIFIED: candidate must begin with the exact benchmark statement")
    from tools.arena_check import FORBIDDEN, remove_comments

    clean = remove_comments(proof)
    if re.search(r"(?m)^(?:theorem|lemma|end|namespace|section|open|set_option)\b", clean[len(statement):]):
        raise ValueError("EXTRA_COMMAND: candidate contains a second top-level command")
    for label, pattern in FORBIDDEN:
        if allow_sorry and label in ("sorry", "admit"):
            continue
        if pattern.search(clean):
            raise ValueError(f"FORBIDDEN: {label}")
    return _proof_length(proof)


def workspace(row: dict, version: str, commit: str) -> Path:
    path = ROOT / "workspaces" / f"{row['source']}-{version}"
    if not path.is_dir():
        raise FileNotFoundError(f"Environment is not provisioned: {path}")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, capture_output=True, check=True
    ).stdout.strip()
    if actual != commit:
        raise ValueError(f"Environment commit mismatch for {version}: {actual} != {commit}")
    return path


def candidate_file(row: dict, proof: str, version: str, commit: str, truncate: bool = True) -> dict:
    """Pinned source with only the benchmark lines replaced.

    With `truncate`, everything after the target declaration is dropped so
    compile time never depends on later declarations. The returned text is the
    single file every compile and every `lean_goal` lookup uses.
    """
    if not row.get("file_path") or not row.get("start_line") or not row.get("end_line"):
        raise ValueError("This row needs a standalone environment adapter")
    path = workspace(row, version, commit)
    source = subprocess.run(
        ["git", "show", f"{commit}:{row['file_path']}"],
        cwd=path, text=True, capture_output=True, check=True,
    ).stdout
    original = row["src"]
    if source.count(original) != 1:
        raise ValueError(f"FILE_MODIFIED: pinned theorem is absent or ambiguous on {version}")
    body = proof.rstrip("\n")
    offset = source.index(original)
    text = source[:offset] + body + source[offset + len(original):]
    if truncate:
        text = text[:offset + len(body)] + "\n"
    start = source.count("\n", 0, offset) + 1
    return {"path": path, "text": text, "offset": offset,
            "start_line": start, "end_line": start + body.count("\n")}


def reconstruct(row: dict, proof: str, version: str, commit: str, truncate: bool = False) -> tuple[Path, str]:
    """Read the source object from Git, then replace only the benchmark lines."""
    built = candidate_file(row, proof, version, commit, truncate)
    return built["path"], built["text"]


_HEADER = re.compile(r"^(?P<file>.*?):(?P<line>\d+):(?P<column>\d+): (?P<severity>error|warning|info)(?:: ?|:)?(?P<rest>.*)$")
_MESSAGE_LIMIT = 800
_DIAGNOSTIC_LIMIT = 8


def parse_diagnostics(output: str) -> list[dict]:
    """Split Lean's textual output into one record per message."""
    found: list[dict] = []
    for line in output.splitlines():
        match = _HEADER.match(line)
        if match:
            found.append({"severity": match["severity"], "line": int(match["line"]),
                          "column": int(match["column"]), "message": [match["rest"]]})
        elif found:
            found[-1]["message"].append(line)
    for item in found:
        item["message"] = "\n".join(item["message"]).strip()
    return found


def map_measured_line(line: int, wrapper_start: int, wrapper_lines: int = WRAPPER_LINES) -> tuple[int, bool]:
    """Map a line of the heartbeat-wrapped file onto the candidate file.

    The wrapper is inserted at `wrapper_start`; later lines shift down by the
    wrapper's line count. A line inside the wrapper maps to its insertion point.
    """
    if line < wrapper_start:
        return line, False
    if line < wrapper_start + wrapper_lines:
        return wrapper_start, True
    return line - wrapper_lines, False


def structure_diagnostics(output: str, text: str, start_line: int, end_line: int,
                          wrapper_start: int | None = None) -> dict:
    """Return headlines for the target declaration plus a count of the rest.

    `text` is the candidate file the diagnostics are about, so every
    `source_line_text` is exactly what `lean_goal` sees at `file_line`.
    """
    lines = text.splitlines()
    inside: list[dict] = []
    goals, output = extract_goals(output, start_line)
    outside = {"errors": 0, "warnings": 0, "first_error": None}
    for item in parse_diagnostics(output):
        if item["severity"] == "info" and item["message"].startswith("ARENA_HEARTBEATS"):
            continue
        line, in_wrapper = (map_measured_line(item["line"], wrapper_start) if wrapper_start
                            else (item["line"], False))
        if in_wrapper:
            continue
        if start_line <= line <= end_line and item["severity"] != "info":
            message = item["message"]
            if len(message) > _MESSAGE_LIMIT:
                message = message[:_MESSAGE_LIMIT] + "… [truncated]"
            inside.append({"severity": item["severity"], "file_line": line,
                           "proof_line": line - start_line + 1, "column": item["column"],
                           "message": message,
                           "source_line_text": lines[line - 1] if 0 < line <= len(lines) else ""})
        elif item["severity"] == "error":
            outside["errors"] += 1
            outside["first_error"] = outside["first_error"] or f"line {line}: {item['message'].splitlines()[0]}"
        elif item["severity"] == "warning":
            outside["warnings"] += 1
    rank = {"error": 0, "warning": 1}
    ordered = sorted(inside, key=lambda item: (rank[item["severity"]], item["file_line"], item["column"]))
    return {"diagnostics": ordered[:_DIAGNOSTIC_LIMIT],
            "diagnostic_counts": {"errors": sum(i["severity"] == "error" for i in inside),
                                  "warnings": sum(i["severity"] == "warning" for i in inside),
                                  "omitted": max(0, len(ordered) - _DIAGNOSTIC_LIMIT)},
            "outside_target": outside, "goals": goals[:12],
            "error_headlines": [f"line {i['file_line']} (proof line {i['proof_line']}): "
                                f"{i['message'].splitlines()[0] if i['message'] else ''}"
                                for i in ordered if i["severity"] == "error"][:_DIAGNOSTIC_LIMIT]}


_SORRY_TACTIC = re.compile(r"(?m)(^[ \t]*(?:[·.][ \t]*)?|\bby[ \t]+|<;>[ \t]*)sorry\b(?![_'])")
_GOAL_MARKER = re.compile(r"^ARENA_SORRY (\d+)$")


def instrument_sorries(proof: str) -> str:
    """Make each tactic-position `sorry` print its goals without moving any line.

    Lean's command line prints informational messages without positions, so
    each trace is preceded by a marker naming the proof line.
    """
    def replace(match: re.Match) -> str:
        line = proof.count("\n", 0, match.start()) + 1
        return f'{match[1]}(trace "ARENA_SORRY {line}"; trace_state; sorry)'
    return _SORRY_TACTIC.sub(replace, proof)


def extract_goals(output: str, start_line: int) -> tuple[list[dict], str]:
    """Pull marked goal traces out of Lean output; return them and the rest."""
    goals: list[dict] = []
    rest: list[str] = []
    current: dict | None = None
    for line in output.splitlines():
        marker = _GOAL_MARKER.match(line)
        if marker:
            current = {"proof_line": int(marker[1]), "file_line": start_line + int(marker[1]) - 1,
                       "text": []}
            goals.append(current)
        elif current is not None and not _HEADER.match(line):
            current["text"].append(line)
        else:
            current = None
            rest.append(line)
    return ([{"file_line": item["file_line"], "proof_line": item["proof_line"],
              "goals": "\n".join(item["text"]).strip()[:1500]} for item in goals],
            "\n".join(rest))


def run_lean(row: dict, project: Path, text: str, timeout: int = 180) -> tuple[int, str] | None:
    """Compile `text` as the target's file inside the pinned project; None on timeout."""
    scratch = ROOT / "runs" / "evaluations"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arena-", dir=scratch) as directory:
        candidate = Path(directory) / Path(row["file_path"]).name
        candidate.write_text(text, encoding="utf-8")
        try:
            proc = subprocess.run(["lake", "env", "lean", str(candidate)], cwd=project,
                                  text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    return proc.returncode, (proc.stdout + proc.stderr).replace(str(candidate), row["file_path"]).strip()


def compile_version(row: dict, proof: str, version: str, commit: str,
                    measure: bool = False, probe: bool = False) -> dict:
    built = candidate_file(row, proof, version, commit)
    text = built["text"]
    if probe:
        body = proof.rstrip("\n")
        text = text[:built["offset"]] + instrument_sorries(body) + text[built["offset"] + len(body):]
    wrapper_start = None
    if measure:
        wrapper_start = text[:built["offset"]].count("\n") + 1
        text = text[:built["offset"]] + HEARTBEAT_WRAPPER + text[built["offset"]:]
    output = run_lean(row, built["path"], text)
    if output is None:
        return {"passed": False, "error": "Lean timed out after 180 seconds"}
    returncode, output = output
    match = re.search(r"ARENA_HEARTBEATS (\d+)", output) if measure else None
    passed = returncode == 0 and (not measure or match is not None)
    structured = structure_diagnostics(output, built["text"], built["start_line"],
                                       built["end_line"], wrapper_start)
    result = {"passed": passed, "exit_code": returncode,
              "heartbeats": int(match.group(1)) if match else None,
              **structured, "raw_output": output}
    return result


def evaluate(name: str, proof: str, mode: str = "fast") -> dict:
    """Compile one proof. `probe` allows `sorry`, checks one version, never scores."""
    if mode not in ("fast", "full", "probe"):
        raise ValueError("mode must be fast, full or probe")
    from arena.scoring import local_proxy, metrics

    row = problem(name)
    probe = mode == "probe"
    length = validate_proof(row, proof, allow_sorry=probe)
    targets = versions(row)
    if not targets:
        raise ValueError("No toolchain versions listed")
    checked = targets if mode == "full" else targets[:1]
    compat = {}
    for version, commit in checked:
        compat[version] = compile_version(row, proof, version, commit,
                                          measure=(version, commit) == targets[0] and not probe,
                                          probe=probe)
        if mode != "full" and not compat[version]["passed"]:
            break
    primary = compat[targets[0][0]]
    heartbeat = primary.get("heartbeats")
    proxy = None
    if mode == "full" and heartbeat is not None:
        proxy = local_proxy(name, length, heartbeat, compat)
    result = {
        "ok": True, "name": name, "mode": mode, "tokens": length,
        "reference_tokens": row["proof_length"], "compat": compat,
        "heartbeat": heartbeat, "local_proxy": proxy, "score": None,
        "calibration": "pending official Arena worker comparison",
    }
    if probe:
        result["scored"] = False
        result["goals"] = primary.get("goals", [])
        result["contains_sorry"] = bool(re.search(r"\bsorry\b", proof))
    else:
        result["metrics"] = metrics(name, length, heartbeat, compat, mode, len(targets))
    return result
