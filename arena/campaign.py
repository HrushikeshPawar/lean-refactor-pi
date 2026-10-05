"""Source-grounded, persistent state for one Arena proof-search run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import fcntl
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from arena.engine import ROOT, evaluate, problem, reconstruct, versions, workspace
from arena.graph import common_base, edit_fingerprint, merge_text, ranked_frontier


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
    pattern = re.compile(r"(?m)^\s*(?:@\[[^\n]*\]\s*)*(?:theorem|lemma|def|instance|abbrev|inductive|structure|class)\s+"
                         + re.escape(symbol) + r"(?![A-Za-z0-9_'.])")
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
    names = sorted(set(re.findall(r"(?<![A-Za-z0-9_'.])[A-Z][A-Za-z0-9_']*", proof)
                       + re.findall(r"(?<![A-Za-z0-9_'.])(?:updated[A-Za-z0-9_']+|isDefined|isNotDefined)", proof)))
    lookups = [declaration(name, symbol) for symbol in names]
    signatures = [item for item in lookups if item.get("signature")]
    commits = ", ".join(f"{v}:{c}" for v, c in versions(row))
    parts = [
        f"Lean Refactor Arena: optimize {name} from its ORIGINAL proof.",
        f"Reference graph candidate ID: {hashlib.sha256((name + chr(0) + original).encode()).hexdigest()}. Use this as the parent of your first edited candidate.",
        "The statement must remain byte-exact. Improve proof tokens and Lean heartbeats while preserving compatibility on every listed version.",
        "Use arena_evaluate fast for exploration and full for promising proofs. Supply the parent candidate ID and a short hypothesis for every edit so the graph can rank branches and combine independent changes. Its diagnostics are complete. The current candidate file is accessible to lean_goal, lean_diagnostic_messages, and lean_multi_attempt. Use arena_source and arena_declaration for exact pinned context.",
        "Do not use sorry, unsafe, IO, #eval, or extra top-level declarations. Submit the complete theorem to arena_evaluate.",
        f"Pinned source: {row['source']}:{row['file_path']}:{row['start_line']}-{row['end_line']}",
        f"Toolchain commits: {commits}",
        f"Reference proof ({row['proof_length']} tokens):\n```lean\n{original}\n```",
        "Source-verified declaration signatures used by the original proof:",
    ]
    parts.extend(f"- {item['source']}\n{item['signature']}" for item in signatures)
    lines = proof.splitlines()
    case_lines = [(i, re.search(r"^\s*case\s+([A-Za-z0-9_']+)", line).group(1))
                  for i, line in enumerate(lines) if re.search(r"^\s*case\s+([A-Za-z0-9_']+)", line)]
    case_spans = [f"{label}: {((case_lines[index + 1][0] if index + 1 < len(case_lines) else len(lines)) - start)} lines"
                  for index, (start, label) in enumerate(case_lines)]
    tactics = Counter(re.findall(r"(?m)^\s*(?:[.·]\s*)?(simp_all|simp|apply|rw|exact|refine|have|constructor|exists|induction)\b", proof))
    repeated = Counter(re.findall(r"\b(?:apply|exact|rw\s*\[|simp\s*\[)\s*([A-Za-z_][A-Za-z0-9_']*)", proof))
    parts.append("Original-proof opportunity map (mechanically extracted; these are leads, not known solutions):\n"
                 + "- Cases: " + (", ".join(case_spans) if case_spans else "none") + "\n"
                 + "- Tactic counts: " + ", ".join(f"{key}={value}" for key, value in sorted(tactics.items())) + "\n"
                 + "- Reused applications: " + (", ".join(f"{key}×{value}" for key, value in repeated.most_common() if value > 1) or "none") + "\n"
                 + "- Investigate whether repeated obligations and the longest case admit a direct source lemma or a different proof structure. Rotate to another graph seed after four unproductive edits to one lineage.")
    parts.append("Work iteratively. Preserve every useful candidate in the ledger. A passing primary proof is not fully validated until arena_evaluate full passes all versions.")
    return "\n\n".join(parts) + "\n"


def _append(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = (json.dumps({"ts": time.time(), **event}, ensure_ascii=False,
                           separators=(",", ":")) + "\n").encode()
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def events(directory: Path) -> list[dict]:
    file = directory / "ledger.jsonl"
    if not file.exists():
        return []
    with file.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        data = handle.read().decode()
    return [json.loads(line) for line in data.splitlines()]


def _snapshot(directory: Path, candidate_id: str, proof: str) -> Path:
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if proof_path.exists():
        return proof_path
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = proof_path.with_name(f"{candidate_id}.{os.getpid()}.tmp")
    temporary.write_text(proof)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(proof_path)
    return proof_path


@contextmanager
def _candidate_lock(directory: Path, candidate_id: str):
    locks = directory / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / f"{candidate_id}.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


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
                        "versions": versions(row),
                        "packet_sha256": hashlib.sha256(text.encode()).hexdigest()})
    reference_id = hashlib.sha256((name + "\0" + row["src"]).encode()).hexdigest()
    _snapshot(directory, reference_id, row["src"])
    _append(directory, {"kind": "candidate", "candidate_id": reference_id, "parents": [],
                        "hypothesis": "Pinned original reference proof", "origin": "reference",
                        "source_versions": versions(row),
                        "evaluator_sha256": hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()})
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
                      parents: list[str] | None = None, hypothesis: str = "",
                      origin: str = "model", merge: dict | None = None,
                      materialize_live: bool = True) -> dict:
    directory = run_dir(run_id)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    with _candidate_lock(directory, candidate_id):
        history = events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError("Run is uninitialized or theorem differs")
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(problem(name))]:
            raise ValueError("Pinned source versions changed since run initialization")
        known = {item["candidate_id"] for item in history if item.get("kind") == "candidate"}
        for parent in parents or []:
            if parent == candidate_id:
                raise ValueError("Candidate cannot be its own parent")
            if parent not in known:
                raise ValueError(f"Unknown candidate parent: {parent}")
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            evaluator_sha = hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()
            _append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                                "parents": parents or [], "hypothesis": hypothesis,
                                "origin": origin, "merge": merge,
                                "source_versions": versions(problem(name)),
                                "evaluator_sha256": evaluator_sha})
        elif parents and not any(item.get("kind") == "derivation"
                                  and item.get("candidate_id") == candidate_id
                                  and item.get("parents") == parents for item in history):
            original = next(item for item in history if item.get("kind") == "candidate"
                            and item["candidate_id"] == candidate_id)
            if original.get("parents", []) != parents:
                _append(directory, {"kind": "derivation", "candidate_id": candidate_id,
                                    "parents": parents, "origin": origin, "merge": merge})
        row = problem(name)
        evaluator_sha = hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()
        key = hashlib.sha256((candidate_id + mode + evaluator_sha + json.dumps(versions(row))).encode()).hexdigest()
        prior = next((item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None)
        if prior:
            result = prior["result"]
        else:
            try:
                result = evaluate(name, proof, mode)
            except (ValueError, FileNotFoundError) as error:
                result = {"ok": False, "name": name, "mode": mode, "error": str(error),
                          "compat": {}, "tokens": None, "heartbeat": None, "local_proxy": None}
            _append(directory, {"kind": "evaluation", "candidate_id": candidate_id, "key": key,
                                "mode": mode, "result": result})
    location = materialize(name, run_id, proof) if materialize_live and result.get("tokens") is not None else {}
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
                            and item["candidate_id"] == candidate_id],
            "derivations": [item for item in history if item.get("kind") in ("candidate", "derivation")
                            and item.get("candidate_id") == candidate_id], **location}


def set_decision(run_id: str, candidate_id: str, decision: str, reason: str) -> dict:
    if decision not in ("pursue", "park") or not reason.strip():
        raise ValueError("Decision must be pursue or park with a reason")
    directory = run_dir(run_id)
    if not any(event.get("kind") == "candidate" and event["candidate_id"] == candidate_id
               for event in events(directory)):
        raise ValueError("Unknown candidate")
    record = {"kind": "decision", "candidate_id": candidate_id,
              "decision": decision, "reason": reason.strip()}
    _append(directory, record)
    return record


def graph_state(run_id: str) -> dict:
    directory = run_dir(run_id)
    history = events(directory)
    if not history:
        return {"run_id": run_id, "nodes": [], "evaluations": 0, "merge_checks": [],
                "milestones": [], "frontier": []}
    theorem = history[0]["theorem"]
    total_versions = len(history[0].get("versions") or versions(problem(theorem)))
    nodes: dict[str, dict] = {}
    order: list[str] = []
    checks: list[dict] = []
    timeline: list[dict] = []
    for event in history:
        kind = event.get("kind")
        if kind == "candidate":
            identifier = event["candidate_id"]
            nodes[identifier] = {"id": identifier, "index": len(order) + 1,
                                 "parents": event.get("parents", []),
                                 "derivations": [event], "origin": event.get("origin", "model"),
                                 "hypothesis": event.get("hypothesis", ""),
                                 "merge": event.get("merge"), "evaluations": [],
                                 "source_versions": event.get("source_versions", []),
                                 "evaluator_sha256": event.get("evaluator_sha256"),
                                 "proof": (directory / "proofs" / f"{identifier}.lean").read_text(),
                                 "children": [], "decision": "pursue"}
            order.append(identifier)
        elif kind == "derivation" and event["candidate_id"] in nodes:
            nodes[event["candidate_id"]]["derivations"].append(event)
        elif kind == "evaluation" and event["candidate_id"] in nodes:
            index = len(timeline) + 1
            nodes[event["candidate_id"]]["evaluations"].append(
                {"number": index, "mode": event["mode"], "result": event["result"]})
            result = event["result"]
            timeline.append({"number": index, "candidate_id": event["candidate_id"],
                             "mode": event["mode"], "tokens": result.get("tokens"),
                             "heartbeat": result.get("heartbeat"),
                             "local_proxy": result.get("local_proxy"), "ts": event.get("ts")})
        elif kind == "merge_check":
            checks.append(event)
        elif kind == "decision" and event.get("candidate_id") in nodes:
            nodes[event["candidate_id"]]["decision"] = event["decision"]
    best_proxy = float("-inf")
    milestones = []
    for row in timeline:
        node = nodes[row["candidate_id"]]
        evaluation = next(e for e in node["evaluations"] if e["number"] == row["number"])
        result = evaluation["result"]
        compat = result.get("compat", {})
        row["status"] = "full" if evaluation["mode"] == "full" and len(compat) == total_versions and all(
            version.get("passed") for version in compat.values()) else (
            "primary" if next(iter(compat.values()), {}).get("passed") else "fail")
        if row["status"] == "full" and row["local_proxy"] is not None and row["local_proxy"] > best_proxy:
            best_proxy = row["local_proxy"]
            milestones.append(row.copy())
    fingerprints: dict[str, set[str]] = {}
    for identifier in order:
        node = nodes[identifier]
        for parent in node["parents"]:
            if parent in nodes:
                nodes[parent]["children"].append(identifier)
        full = [e for e in node["evaluations"] if next(
            (row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "full"]
        primary = [e for e in node["evaluations"] if next(
            (row["status"] for row in timeline if row["number"] == e["number"]), "fail") == "primary"]
        selected = max(full, key=lambda e: e["result"].get("local_proxy") or -1) if full else (
            min(primary, key=lambda e: e["result"].get("tokens") or 10**9) if primary else
            (node["evaluations"][-1] if node["evaluations"] else None))
        result = selected["result"] if selected else {}
        node["status"] = "full" if full else "primary" if primary else "fail" if selected else "unevaluated"
        node["tokens"] = result.get("tokens")
        node["heartbeat"] = result.get("heartbeat")
        node["local_proxy"] = result.get("local_proxy") if full else None
        parent_attempts = [nodes[p].get("attempts_since_gain", 0) for p in node["parents"] if p in nodes]
        node["attempts_since_gain"] = 0 if node["status"] == "full" and any(
            m["candidate_id"] == identifier for m in milestones) else 1 + (min(parent_attempts) if parent_attempts else 0)
        first_parent = nodes.get(node["parents"][0]) if node["parents"] else None
        fingerprint = edit_fingerprint(first_parent["proof"], node["proof"]) if first_parent else {node["proof"]}
        node["novelty"] = 1.0 - max((len(fingerprint & earlier) / len(fingerprint | earlier)
                                     for earlier in fingerprints.values() if fingerprint | earlier), default=0.0)
        fingerprints[identifier] = fingerprint
        node["merge_partners"] = 0
    checked_pairs = {tuple(sorted(check["parents"])) for check in checks}
    open_nodes = [node for node in nodes.values() if node["status"] in ("full", "primary")
                  and node["decision"] != "park"]
    ancestry = {node["id"]: node["parents"] for node in nodes.values()}
    reference = next((node for node in nodes.values() if node["origin"] == "reference"), None)
    for index, left in enumerate(open_nodes):
        for right in open_nodes[index + 1:]:
            if tuple(sorted((left["id"], right["id"]))) in checked_pairs:
                continue
            common = common_base(left["id"], right["id"], ancestry)
            base = common["base"] or (reference["id"] if common["reason"] == "no_common_base" and reference else None)
            if base and merge_text(nodes[base]["proof"], left["proof"], right["proof"])["text"]:
                left["merge_partners"] += 1
                right["merge_partners"] += 1
    rows = [nodes[identifier] for identifier in order]
    ranked = ranked_frontier(rows)
    return {"run_id": run_id, "theorem": theorem, "nodes": rows, "ledger_events": len(history), "evaluations": len(timeline),
            "timeline": timeline, "merge_checks": checks, "milestones": milestones,
            "frontier": ranked}


def merge_once(run_id: str) -> dict | None:
    """Process one unchecked good pair; repeated calls exhaust the queue."""
    graph = graph_state(run_id)
    if not graph["nodes"]:
        return None
    directory = run_dir(run_id)
    nodes = {node["id"]: node for node in graph["nodes"]}
    good = [node for node in graph["nodes"] if node["status"] in ("full", "primary")
            and node["decision"] != "park"]
    checked = {tuple(sorted(check["parents"])) for check in graph["merge_checks"]}
    ancestry = {node["id"]: node["parents"] for node in graph["nodes"]}
    reference = next((node for node in graph["nodes"] if node["origin"] == "reference"), None)
    for fresh in reversed(good):
        for other in good:
            if fresh["id"] == other["id"]:
                continue
            pair = sorted((fresh["id"], other["id"]))
            if tuple(pair) in checked:
                continue
            base = common_base(pair[0], pair[1], ancestry)
            inferred = base["base"] is None and base["reason"] == "no_common_base" and reference is not None
            if inferred:
                base = {"base": reference["id"], "reason": None}
            outcome = {"kind": "merge_check", "parents": pair, "base": base["base"]}
            if inferred:
                outcome["base_inferred_from_reference"] = True
            if base["base"] is None:
                outcome["reason"] = base["reason"]
            else:
                merged = merge_text(nodes[base["base"]]["proof"], nodes[pair[0]]["proof"],
                                    nodes[pair[1]]["proof"])
                outcome["edits"] = {"left": merged["left_edits"], "right": merged["right_edits"]}
                if merged["text"] is None:
                    outcome["reason"] = merged["reason"]
                else:
                    recorded = record_evaluation(graph["theorem"], run_id, merged["text"], "fast",
                                                 pair, "Deterministic combination of disjoint edits",
                                                 origin="auto_merge", merge={"base": base["base"],
                                                                               "base_inferred_from_reference": inferred,
                                                                               "edits": outcome["edits"]},
                                                 materialize_live=False)
                    outcome["candidate_id"] = recorded["candidate_id"]
                    outcome["fast_passed"] = any(v.get("passed") for v in recorded.get("compat", {}).values())
                    if outcome["fast_passed"]:
                        full = record_evaluation(graph["theorem"], run_id, merged["text"], "full",
                                                 pair, "Deterministic combination of disjoint edits",
                                                 origin="auto_merge", merge={"base": base["base"],
                                                                               "base_inferred_from_reference": inferred,
                                                                               "edits": outcome["edits"]},
                                                 materialize_live=False)
                        outcome["full_passed"] = all(v.get("passed") for v in full.get("compat", {}).values())
            _append(directory, outcome)
            return outcome
    return None


def frontier(run_id: str) -> dict:
    graph = graph_state(run_id)
    full = [node for node in graph["nodes"] if node["status"] == "full"]
    full.sort(key=lambda node: node["local_proxy"] or -1, reverse=True)
    primary = [node for node in graph["nodes"] if node["status"] in ("full", "primary")]
    primary.sort(key=lambda node: node["tokens"] if node["tokens"] is not None else 10**9)
    ranked_full = [row for row in graph["frontier"] if row["status"] == "full"][:4]
    ranked_repair = [row for row in graph["frontier"] if row["status"] == "primary"][:2]
    experiments = ranked_full + ranked_repair
    experiments.sort(key=lambda row: (-row["priority_total"], row["candidate_id"]))
    return {"verified_best": [{"candidate_id": full[0]["id"], "tokens": full[0]["tokens"],
                                "heartbeat": full[0]["heartbeat"], "local_proxy": full[0]["local_proxy"]}] if full else [],
            "score_best": {key: full[0][key] for key in ("id", "tokens", "heartbeat", "local_proxy")} if full else None,
            "primary_best": {"candidate_id": primary[0]["id"], "tokens": primary[0]["tokens"]} if primary else None,
            "next_experiments": experiments, "mutation_seeds": experiments,
            "merge_checks": len(graph["merge_checks"]),
            "evaluations": graph["evaluations"], "candidates": len(graph["nodes"])}
