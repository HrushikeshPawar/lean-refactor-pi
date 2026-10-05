"""Source-grounded, persistent state for one Arena proof-search run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from arena.engine import ROOT, evaluate, problem, reconstruct, versions, workspace


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", run_id):
        raise ValueError("Invalid run ID")
    return ROOT / "runs" / "pi-budget" / run_id


def _git_source(project: Path, commit: str, path: str) -> str:
    if not path.endswith(".lean") or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("Only relative pinned Lean source paths are allowed")
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=project,
                          text=True, capture_output=True, check=True).stdout


def source_range(name: str, path: str, first: int, last: int) -> dict:
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    lines = _git_source(project, commit, path).splitlines()
    if first < 1 or last < first or last > len(lines) or last - first > 120:
        raise ValueError("Source range must contain 1-120 existing lines")
    return {"source": f"{row['source']}@{commit}:{path}:{first}-{last}",
            "text": "\n".join(f"{i}: {lines[i-1]}" for i in range(first, last + 1))}


def declaration(name: str, symbol: str) -> dict:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9'.]*", symbol):
        raise ValueError("Invalid declaration name")
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    found = subprocess.run(["rg", "-l", "--glob", "*.lean", "-F", symbol, row["source"].capitalize()],
                           cwd=project, text=True, capture_output=True, check=False)
    paths = found.stdout.splitlines()
    # Some corpora use directory names unrelated to the benchmark source.
    if not paths:
        found = subprocess.run(["rg", "-l", "--glob", "*.lean", "-F", symbol, "."],
                               cwd=project, text=True, capture_output=True, check=False)
        paths = found.stdout.splitlines()
    pattern = re.compile(r"(?m)^\s*(?:theorem|lemma|def|instance|abbrev)\s+" + re.escape(symbol) + r"\b")
    for path in paths[:80]:
        path = path.removeprefix("./")
        try:
            source = _git_source(project, commit, path)
        except subprocess.CalledProcessError:
            continue
        match = pattern.search(source)
        if not match:
            continue
        suffix = source[match.start():match.start() + 3000]
        signature = suffix.split(":=", 1)[0].rstrip() if ":=" in suffix else suffix.splitlines()[0]
        line = source.count("\n", 0, match.start()) + 1
        return {"symbol": symbol, "source": f"{row['source']}@{commit}:{path}:{line}",
                "signature": signature}
    return {"symbol": symbol, "found": False}


def packet(name: str) -> str:
    row = problem(name)
    original = row["src"]
    proof = original.split(":=", 1)[1] if ":=" in original else original
    names = sorted(set(re.findall(r"\b[A-Z][A-Za-z0-9_']*\b", proof)
                       + re.findall(r"\b(?:updated[A-Za-z0-9_']+|isDefined|isNotDefined)\b", proof)))
    signatures = [declaration(name, symbol) for symbol in names]
    signatures = [item for item in signatures if item.get("signature")]
    commits = ", ".join(f"{v}:{c}" for v, c in versions(row))
    parts = [
        f"Lean Refactor Arena: optimize {name} from its ORIGINAL proof.",
        "The statement must remain byte-exact. Improve proof tokens and Lean heartbeats while preserving compatibility on every listed version.",
        "Use arena_evaluate fast for exploration and full for promising proofs. Its diagnostics are complete. The current candidate file is accessible to lean_goal, lean_diagnostic_messages, and lean_multi_attempt. Use arena_source and arena_declaration for exact pinned context.",
        "Do not use sorry, unsafe, IO, #eval, or extra top-level declarations. Submit the complete theorem to arena_evaluate.",
        f"Pinned source: {row['source']}:{row['file_path']}:{row['start_line']}-{row['end_line']}",
        f"Toolchain commits: {commits}",
        f"Reference proof ({row['proof_length']} tokens):\n```lean\n{original}\n```",
        "Source-verified declaration signatures used by the original proof:",
    ]
    parts.extend(f"- {item['source']}\n{item['signature']}" for item in signatures)
    parts.append("Work iteratively. Preserve every useful candidate in the ledger. A passing primary proof is not fully validated until arena_evaluate full passes all versions.")
    return "\n\n".join(parts) + "\n"


def _append(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        data = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def events(directory: Path) -> list[dict]:
    file = directory / "ledger.jsonl"
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text().splitlines()]


def init(name: str, run_id: str, extra: str = "") -> dict:
    directory = run_dir(run_id)
    if directory.exists():
        raise ValueError(f"Run ID already exists: {directory}")
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    directory.mkdir(parents=True)
    text = packet(name) + ("\nAdditional instructions:\n" + extra + "\n" if extra else "")
    (directory / "packet.txt").write_text(text)
    shadow = directory / "scratch" / "project"
    shutil.copytree(project, shadow, ignore=shutil.ignore_patterns(".git", ".lake"))
    (shadow / ".lake").symlink_to(project / ".lake", target_is_directory=True)
    _append(directory, {"kind": "init", "theorem": name, "version": version, "commit": commit,
                        "packet_sha256": hashlib.sha256(text.encode()).hexdigest()})
    materialize(name, run_id, row["src"])
    return {"packet": str(directory / "packet.txt"), "shadow": str(shadow),
            "candidate_path": str(shadow / row["file_path"])}


def materialize(name: str, run_id: str, proof: str) -> dict:
    row = problem(name)
    version, commit = versions(row)[0]
    _, source = reconstruct(row, proof, version, commit)
    path = run_dir(run_id) / "scratch" / "project" / row["file_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    start = source[:source.index(proof.rstrip("\n"))].count("\n") + 1
    end = start + proof.rstrip("\n").count("\n")
    return {"candidate_path": str(path), "start_line": start, "end_line": end}


def record_evaluation(name: str, run_id: str, proof: str, mode: str,
                      parents: list[str] | None = None, hypothesis: str = "") -> dict:
    directory = run_dir(run_id)
    history = events(directory)
    if not history or history[0].get("theorem") != name:
        raise ValueError("Run is uninitialized or theorem differs")
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    known = {item["candidate_id"] for item in history if item.get("kind") == "candidate"}
    for parent in parents or []:
        if parent not in known:
            raise ValueError(f"Unknown candidate parent: {parent}")
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not proof_path.exists():
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = proof_path.with_suffix(".tmp")
        temporary.write_text(proof)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(proof_path)
        _append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                            "parents": parents or [], "hypothesis": hypothesis})
    row = problem(name)
    key = hashlib.sha256((candidate_id + mode + json.dumps(versions(row))).encode()).hexdigest()
    prior = next((item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None)
    if prior:
        result = prior["result"]
    else:
        try:
            result = evaluate(name, proof, mode)
        except (ValueError, FileNotFoundError) as error:
            result = {"ok": False, "name": name, "mode": mode, "error": str(error),
                      "compat": {}, "tokens": None, "heartbeat": None, "local_proxy": None}
    if prior is None:
        _append(directory, {"kind": "evaluation", "candidate_id": candidate_id, "key": key,
                            "mode": mode, "result": result})
    location = materialize(name, run_id, proof) if result.get("ok") else {}
    return {**result, "candidate_id": candidate_id, "cached": prior is not None, **location}


def candidate(name: str, run_id: str, candidate_id: str) -> dict:
    directory = run_dir(run_id)
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_id) or not proof_path.exists():
        raise ValueError("Unknown candidate")
    proof = proof_path.read_text()
    location = materialize(name, run_id, proof)
    history = events(directory)
    return {"candidate_id": candidate_id, "proof": proof,
            "evaluations": [item["result"] for item in history if item.get("kind") == "evaluation"
                            and item["candidate_id"] == candidate_id], **location}


def frontier(run_id: str) -> dict:
    history = events(run_dir(run_id))
    count = len(versions(problem(history[0]["theorem"]))) if history else 0
    rows = []
    for item in history:
        if item.get("kind") != "evaluation":
            continue
        result = item["result"]
        passed = sum(bool(v.get("passed")) for v in result.get("compat", {}).values())
        rows.append({"candidate_id": item["candidate_id"], "tokens": result.get("tokens"),
                     "heartbeat": result.get("heartbeat"), "compat_passed": passed,
                     "compat_checked": len(result.get("compat", {})),
                     "local_proxy": result.get("local_proxy"), "mode": item["mode"]})
    full = [r for r in rows if r["mode"] == "full" and r["compat_checked"] == count and r["compat_passed"] == count]
    full.sort(key=lambda r: (r["local_proxy"] or float("-inf")), reverse=True)
    partial = [r for r in rows if r not in full and r["compat_passed"]]
    partial.sort(key=lambda r: (r["tokens"] or 10**9, -r["compat_passed"]))
    return {"verified_best": full[:1], "mutation_seeds": (full[1:4] + partial[:4]),
            "evaluations": len(rows), "candidates": len({r["candidate_id"] for r in rows})}
