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
from arena.ideas import idea_shape_issue, scheduled_ideas, source_ideas


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
        # A named argument such as (P:=P) occurs inside some theorem types.
        # Only the assignment at top level starts the proof body.
        depth = 0
        end = None
        for index, char in enumerate(suffix):
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == ":" and suffix[index:index + 2] == ":=" and depth == 0:
                end = index
                break
        signature = suffix[:end].rstrip() if end is not None else suffix.splitlines()[0]
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
        "Use arena_frontier to obtain the scheduled idea and seed. Supply its idea_id, a parent (#N is accepted), and a short hypothesis with arena_evaluate. Fast checks the primary version; full checks every version. Use arena_probe to develop an unfinished idea without adding a candidate node. Its diagnostics are complete. The current candidate file is accessible to lean_goal, lean_diagnostic_messages, and lean_multi_attempt. Use arena_source and arena_declaration for exact pinned context.",
        "Do not use sorry, unsafe, IO, #eval, or extra top-level declarations. Submit the complete theorem to arena_evaluate.",
        f"Pinned source: {row['source']}:{row['file_path']}:{row['start_line']}-{row['end_line']}",
        f"Toolchain commits: {commits}",
        f"Reference proof ({row['proof_length']} tokens):\n```lean\n{original}\n```",
        "Source-verified declaration signatures used by the original proof:",
    ]
    parts.extend(f"- {item['source']}\n{item['signature']}" for item in signatures)
    idea_rows = source_ideas(row["statement"], original)
    parts.insert(2, "Source-derived idea portfolio (no prior optimized proof or score):\n" +
                 "\n".join(f"- {idea['id']}: {idea['title']}. {idea['goal']}" for idea in idea_rows) +
                 "\nDevelop each structural idea for two attempts before local golfing. A failed first draft is an obligation to inspect and repair, not proof the idea is bad.")
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
    if "∃" in row["statement"] and "induction" in proof:
        parts.append("Structural exploration lane (derived from the statement and original proof, not a known solution):\n"
                     "- Compare choosing the existential witness before versus after induction. Inspect whether the induction hypothesis already supplies a witness or a tail proof that can replace a manual subproof.\n"
                     "- Try one structurally different candidate before another chain of local deletions. State which original proof block the new structure aims to remove.\n"
                     "- For a questionable local tactic edit, inspect the materialized Lean goal or use lean_multi_attempt before recording another candidate. Record the failed obligation in the hypothesis if the edit still fails.")
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
    for idea in source_ideas(row["statement"], row["src"]):
        _append(directory, {"kind": "idea", **idea})
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


def resolve_candidate_ref(history: list[dict], reference: str) -> str:
    candidates = [item["candidate_id"] for item in history if item.get("kind") == "candidate"]
    if re.fullmatch(r"#[1-9][0-9]*", reference):
        index = int(reference[1:])
        if index <= len(candidates):
            return candidates[index - 1]
    elif reference in candidates:
        return reference
    elif re.fullmatch(r"[0-9a-f]{8,63}", reference):
        matches = [candidate for candidate in candidates if candidate.startswith(reference)]
        if len(matches) == 1:
            return matches[0]
    raise ValueError(f"Unknown candidate parent: {reference}; use a current #N from arena_frontier")


def record_idea(run_id: str, title: str, goal: str, path: str, first: int, last: int) -> dict:
    """Add a distinct, source-grounded strategy to the durable portfolio."""
    title, goal = title.strip(), goal.strip()
    if not (8 <= len(title) <= 100 and 20 <= len(goal) <= 500 and 1 <= last - first + 1 <= 20):
        raise ValueError("Idea needs a title, actionable goal, and 1-20 pinned source lines")
    directory = run_dir(run_id)
    history = events(directory)
    if not history or not history[0].get("theorem"):
        raise ValueError("Run is uninitialized")
    evidence = source_range(history[0]["theorem"], path, first, last)
    ideas = [item for item in history if item.get("kind") == "idea"]
    if len(ideas) >= 8:
        raise ValueError("Idea portfolio is full; park or test an existing idea")
    identifier = "idea-" + hashlib.sha256((title.lower() + "\0" + goal.lower()).encode()).hexdigest()[:10]
    existing = next((item for item in ideas if item["id"] == identifier), None)
    if existing:
        return {"id": identifier, "cached": True}
    item = {"kind": "idea", "id": identifier, "title": title,
            "goal": goal, "source_evidence": evidence["source"], "idea_kind": "structural"}
    _append(directory, item)
    return {key: value for key, value in item.items() if key != "kind"}


def record_evaluation(name: str, run_id: str, proof: str, mode: str,
                      parents: list[str] | None = None, hypothesis: str = "",
                      origin: str = "model", merge: dict | None = None,
                      materialize_live: bool = True, idea_id: str | None = None) -> dict:
    directory = run_dir(run_id)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    with _candidate_lock(directory, candidate_id):
        history = events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError("Run is uninitialized or theorem differs")
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(problem(name))]:
            raise ValueError("Pinned source versions changed since run initialization")
        parents = [resolve_candidate_ref(history, parent) for parent in parents or []]
        known = {item["candidate_id"] for item in history if item.get("kind") == "candidate"}
        if candidate_id in known and idea_id is None:
            idea_id = next(item.get("idea_id") for item in history
                           if item.get("kind") == "candidate" and item["candidate_id"] == candidate_id)
        ideas = [item for item in history if item.get("kind") == "idea"]
        if ideas and origin == "model" and candidate_id not in known:
            if idea_id not in {idea["id"] for idea in ideas}:
                raise ValueError("Supply a source-derived idea_id from arena_frontier")
            if not parents:
                raise ValueError("Supply a parent #N for each new candidate")
            scheduled = graph_state(run_id)["ideas"][0]["id"]
            if idea_id != scheduled:
                raise ValueError(f"Explore scheduled idea {scheduled} before {idea_id}; call arena_frontier")
            issue = idea_shape_issue(idea_id, proof)
            if issue:
                raise ValueError(issue)
        for parent in parents:
            if parent == candidate_id:
                raise ValueError("Candidate cannot be its own parent")
            if parent not in known:
                raise ValueError(f"Unknown candidate parent: {parent}")
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            evaluator_sha = hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()
            _append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                                "parents": parents or [], "hypothesis": hypothesis,
                                "origin": origin, "merge": merge, "idea_id": idea_id,
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
    node_number = next((i for i, item in enumerate(
        (item for item in events(directory) if item.get("kind") == "candidate"), 1)
        if item["candidate_id"] == candidate_id), None)
    return {**result, "candidate_id": candidate_id, "node_number": node_number,
            "idea_id": idea_id, "cached": prior is not None, **location}


def probe(name: str, run_id: str, proof: str, idea_id: str, parent: str) -> dict:
    """Compile a draft in the shadow project without entering the candidate graph."""
    directory = run_dir(run_id)
    history = events(directory)
    ideas = {item["id"] for item in history if item.get("kind") == "idea"}
    if idea_id not in ideas:
        raise ValueError("Supply a source-derived idea_id from arena_frontier")
    state = graph_state(run_id)
    if state.get("ideas") and state["ideas"][0]["id"] != idea_id:
        raise ValueError(f"Explore scheduled idea {state['ideas'][0]['id']} before {idea_id}; call arena_frontier")
    parent_id = resolve_candidate_ref(history, parent)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    earlier = next((item for item in reversed(history)
                    if item.get("kind") == "probe" and item["proof_id"] == proof_id), None)
    if earlier:
        result = earlier["result"]
    else:
        try:
            result = evaluate(name, proof, "fast")
        except (ValueError, FileNotFoundError) as error:
            result = {"ok": False, "error": str(error), "compat": {}}
        _snapshot(directory, proof_id, proof)
        _append(directory, {"kind": "probe", "proof_id": proof_id, "idea_id": idea_id,
                            "parent": parent_id, "result": result})
    location = materialize(name, run_id, proof) if result.get("tokens") is not None else {}
    return {**result, "proof_id": proof_id, "idea_id": idea_id,
            "idea_shape_issue": idea_shape_issue(idea_id, proof),
            "parent": parent_id, "cached": earlier is not None,
            "next_action": "Inspect the complete diagnostics and Lean goal, then repair this idea. Promote a passing draft with arena_evaluate.",
            **location}


def candidate(name: str, run_id: str, candidate_id: str) -> dict:
    directory = run_dir(run_id)
    candidate_id = resolve_candidate_ref(events(directory), candidate_id)
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_id) or not proof_path.exists():
        raise ValueError("Unknown candidate")
    proof = proof_path.read_text()
    location = materialize(name, run_id, proof)
    history = events(directory)
    node_number = next((i for i, item in enumerate(
        (item for item in history if item.get("kind") == "candidate"), 1)
        if item["candidate_id"] == candidate_id), None)
    return {"candidate_id": candidate_id, "node_number": node_number, "proof": proof,
            "evaluations": [item["result"] for item in history if item.get("kind") == "evaluation"
                            and item["candidate_id"] == candidate_id],
            "derivations": [item for item in history if item.get("kind") in ("candidate", "derivation")
                            and item.get("candidate_id") == candidate_id], **location}


def set_decision(run_id: str, candidate_id: str, decision: str, reason: str) -> dict:
    if decision not in ("pursue", "park") or not reason.strip():
        raise ValueError("Decision must be pursue or park with a reason")
    directory = run_dir(run_id)
    candidate_id = resolve_candidate_ref(events(directory), candidate_id)
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
    ideas: list[dict] = []
    probes: list[dict] = []
    timeline: list[dict] = []
    for event in history:
        kind = event.get("kind")
        if kind == "idea":
            ideas.append({**{key: event[key] for key in ("id", "title", "goal", "idea_kind")},
                          "source_evidence": event.get("source_evidence")})
        elif kind == "probe":
            probes.append({"proof_id": event["proof_id"], "idea_id": event["idea_id"],
                           "parent": event["parent"], "result": event["result"], "ts": event.get("ts")})
        elif kind == "candidate":
            identifier = event["candidate_id"]
            nodes[identifier] = {"id": identifier, "index": len(order) + 1,
                                 "parents": event.get("parents", []),
                                 "derivations": [event], "origin": event.get("origin", "model"),
                                 "hypothesis": event.get("hypothesis", ""),
                                 "idea_id": event.get("idea_id"),
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
    idea_rows = scheduled_ideas(ideas, rows, probes) if ideas else []
    return {"run_id": run_id, "theorem": theorem, "nodes": rows, "ledger_events": len(history), "evaluations": len(timeline),
            "timeline": timeline, "merge_checks": checks, "milestones": milestones,
            "frontier": ranked, "ideas": idea_rows, "probes": probes}


def merge_once(run_id: str, graph: dict | None = None) -> dict | None:
    """Process one unchecked good pair; repeated calls exhaust the queue."""
    graph = graph if graph is not None else graph_state(run_id)
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
                    outcome["node_number"] = recorded["node_number"]
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
            graph["merge_checks"].append(outcome)
            return outcome
    return None


def merge_batch(run_id: str, max_checks: int = 64) -> dict:
    """Reuse one graph snapshot for cheap skipped pairs; refresh after a new node."""
    graph = graph_state(run_id)
    checks = 0
    last = None
    for _ in range(max_checks):
        outcome = merge_once(run_id, graph)
        if outcome is None:
            break
        checks += 1
        last = outcome
        if outcome.get("candidate_id"):
            break
    return {"checks": checks, "last": last}


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
    if graph.get("ideas"):
        experiments = [{"idea_id": idea["id"], "title": idea["title"],
                        "next_action": idea["next_action"], "candidate_id": idea["seed_candidate_id"],
                        "node_number": idea["seed_node"], "attempts": idea["attempts"],
                        "best_tokens": idea["best_tokens"], "kind": idea["idea_kind"]}
                       for idea in graph["ideas"]]
    return {"verified_best": [{"candidate_id": full[0]["id"], "tokens": full[0]["tokens"],
                                "heartbeat": full[0]["heartbeat"], "local_proxy": full[0]["local_proxy"]}] if full else [],
            "score_best": {key: full[0][key] for key in ("id", "tokens", "heartbeat", "local_proxy")} if full else None,
            "primary_best": {"candidate_id": primary[0]["id"], "tokens": primary[0]["tokens"]} if primary else None,
            "next_experiments": experiments, "mutation_seeds": experiments,
            "merge_checks": len(graph["merge_checks"]),
            "evaluations": graph["evaluations"], "candidates": len(graph["nodes"]),
            "ideas": graph.get("ideas", []), "probes": len(graph.get("probes", []))}
