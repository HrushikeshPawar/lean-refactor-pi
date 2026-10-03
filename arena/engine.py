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


def validate_proof(row: dict, proof: str) -> int:
    statement = row["statement"]
    if not proof.startswith(statement) or not re.match(r"\s*:=", proof[len(statement):]):
        raise ValueError("STATEMENT_MODIFIED: candidate must begin with the exact benchmark statement")
    from tools.arena_check import FORBIDDEN, remove_comments

    clean = remove_comments(proof)
    if re.search(r"(?m)^(?:theorem|lemma|end|namespace|section|open|set_option)\b", clean[len(statement):]):
        raise ValueError("EXTRA_COMMAND: candidate contains a second top-level command")
    for label, pattern in FORBIDDEN:
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


def reconstruct(row: dict, proof: str, version: str, commit: str) -> tuple[Path, str]:
    """Read the source object from Git, then replace only the benchmark lines."""
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
    return path, source.replace(original, proof.rstrip("\n"), 1)


def compile_version(row: dict, proof: str, version: str, commit: str, measure: bool = False) -> dict:
    path, source = reconstruct(row, proof, version, commit)
    if measure:
        if source.count(proof.rstrip("\n")) != 1:
            raise ValueError("Cannot locate one candidate declaration for heartbeat measurement")
        source = source.replace(proof.rstrip("\n"), HEARTBEAT_WRAPPER + proof.rstrip("\n"), 1)
    scratch = ROOT / "runs" / "evaluations"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arena-", dir=scratch) as directory:
        candidate = Path(directory) / Path(row["file_path"]).name
        candidate.write_text(source, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["lake", "env", "lean", str(candidate)], cwd=path,
                text=True, capture_output=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Lean timed out after 180 seconds"}
    output = (proc.stdout + proc.stderr).replace(str(candidate), row["file_path"]).strip()
    headlines = [line for line in output.splitlines() if ": error:" in line]
    diagnostics = output[:2400]
    if len(output) > 2400:
        diagnostics += "\n[diagnostics truncated]"
    # Existing warnings elsewhere in a source file are not proof failures.
    match = re.search(r"ARENA_HEARTBEATS (\d+)", output) if measure else None
    passed = proc.returncode == 0 and (not measure or match is not None)
    return {"passed": passed, "exit_code": proc.returncode,
            "heartbeats": int(match.group(1)) if match else None,
            "error_headlines": headlines[:8], "diagnostics": diagnostics}


def evaluate(name: str, proof: str, mode: str = "fast") -> dict:
    if mode not in ("fast", "full"):
        raise ValueError("mode must be fast or full")
    row = problem(name)
    length = validate_proof(row, proof)
    targets = versions(row)
    if not targets:
        raise ValueError("No toolchain versions listed")
    checked = targets if mode == "full" else targets[:1]
    compat = {}
    for version, commit in checked:
        compat[version] = compile_version(row, proof, version, commit,
                                          measure=(version, commit) == targets[0])
        if mode == "fast" and not compat[version]["passed"]:
            break
    heartbeat = compat[targets[0][0]].get("heartbeats")
    proxy = None
    if mode == "full" and heartbeat is not None:
        from arena.scoring import local_proxy

        proxy = local_proxy(name, length, heartbeat, compat)
    return {
        "ok": True, "name": name, "mode": mode, "tokens": length,
        "reference_tokens": row["proof_length"], "compat": compat,
        "heartbeat": heartbeat, "local_proxy": proxy, "score": None,
        "calibration": "pending official Arena worker comparison",
    }
