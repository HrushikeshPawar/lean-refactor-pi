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
from contextlib import contextmanager
from pathlib import Path

from arena.engine import ROOT, candidate_file, evaluate, problem, source_path, validate_proof, versions, workspace
from arena.polish import polish
from arena.profile import heartbeat_floor, profile
from arena.graph import common_base, edit_fingerprint, merge_text, ranked_frontier


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", run_id):
        raise ValueError("Invalid run ID")
    return ROOT / "runs" / "pi-budget" / run_id


def _git_source(project: Path, commit: str, path: str) -> str:
    if not path.endswith(".lean") or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError("Only relative .lean paths inside the pinned project are allowed")
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=project,
                          text=True, capture_output=True, check=True).stdout


MAX_SOURCE_LINES = 400


def source_range(name: str, path: str, first: int, last: int | None = None) -> dict:
    """Read pinned source; `next_first` continues a range cut at the limit."""
    row = problem(name)
    version, commit = versions(row)[0]
    project = workspace(row, version, commit)
    try:
        lines = _git_source(project, commit, path).splitlines()
    except subprocess.CalledProcessError:
        raise ValueError(f"{path} does not exist in the pinned project at {commit[:8]}") from None
    if first < 1 or first > len(lines):
        raise ValueError(f"{path} has {len(lines)} lines; first={first} is out of range")
    wanted = last if last is not None else first + 199
    end = min(wanted, len(lines), first + MAX_SOURCE_LINES - 1)
    if end < first:
        raise ValueError("last must not precede first")
    return {"source": f"{row['source']}@{commit}:{path}:{first}-{end}", "file_lines": len(lines),
            "first": first, "last": end, "next_first": end + 1 if end < len(lines) and wanted > end else None,
            "text": "\n".join(f"{i}: {lines[i-1]}" for i in range(first, end + 1))}


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
    return _declaration_in_lean(name, symbol)


def _declaration_in_lean(name: str, symbol: str) -> dict:
    """Resolve a name the way the theorem's own file does (namespaces, opens, imported libraries)."""
    from arena.engine import candidate_file, run_lean

    row = problem(name)
    version, commit = versions(row)[0]
    built = candidate_file(row, row["src"], version, commit)
    inserted = (Path(__file__).with_name("lean") / "declaration.lean").read_text() + f"arena_decl {symbol}\n\n"
    text = built["text"][:built["offset"]] + inserted + built["text"][built["offset"]:]
    ran = run_lean(row, built["path"], text)
    if ran is None:
        raise ValueError("Lean timed out while resolving the name")
    records = [json.loads(raw) for raw in re.findall(r"^ARENA_DECL (\{.*\})$", ran[1], re.M)]
    found = [item for item in records if item.get("found")]
    if not found:
        return {"symbol": symbol, "found": False,
                "hint": "No declaration of that name is visible where the theorem is stated; try the full name or a prefix."}
    best = found[0]
    return {"symbol": symbol, "found": True, "name": best["name"], "kind": best["kind"], "module": best["module"],
            "source": f"{best['module']}" + (f":{best['line']}" if best.get("line") else ""),
            "signature": best["signature"],
            **({"alternatives": [item["name"] for item in found[1:]]} if len(found) > 1 else {})}


def packet(name: str) -> str:
    """Kickoff packet: task, exchange rates, source-derived context. Built once per row and cached."""
    from arena.context import render_packet

    return render_packet(name)


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


@contextmanager
def lean_lock(directory: Path):
    """One Lean job at a time per run, so evaluations, probes, profiles and polish never compete
    for CPU (which would distort latency and starve the model's own checks)."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lean.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


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
    _append(directory, {"kind": "current", "candidate_id": reference_id})
    return {"packet": str(directory / "packet.txt"), "shadow": str(shadow),
            "candidate_path": str(shadow / source_path(row))}


def _externalize_output(directory: Path, key: str, result: dict) -> dict:
    """Keep full Lean output beside the ledger; results carry only a reference."""
    for version, item in (result.get("compat") or {}).items():
        raw = item.pop("raw_output", None)
        if raw:
            path = directory / "diagnostics" / f"{key[:16]}-{result.get('mode', 'eval')}-{version}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw + "\n")
            item["full_diagnostics_ref"] = str(path.relative_to(directory))
    return result


def _evaluator_sha() -> str:
    return hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()


def materialize(name: str, run_id: str, proof: str) -> dict:
    """Write the exact file the evaluator compiles (minus the heartbeat wrapper)."""
    row = problem(name)
    version, commit = versions(row)[0]
    built = candidate_file(row, proof, version, commit)
    path = run_dir(run_id) / "scratch" / "project" / source_path(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(built["text"])
    return {"candidate_path": str(path), "start_line": built["start_line"], "end_line": built["end_line"]}


def _candidate_ids(history: list[dict]) -> list[str]:
    return [item["candidate_id"] for item in history if item.get("kind") == "candidate"]


def _label(history: list[dict], candidate_id: str) -> str | None:
    ids = _candidate_ids(history)
    return f"#{ids.index(candidate_id) + 1}" if candidate_id in ids else None


def resolve_candidate_ref(history: list[dict], reference: str) -> str:
    candidates = _candidate_ids(history)
    reference = reference.strip()
    if re.fullmatch(r"#?[1-9][0-9]*", reference):
        index = int(reference.lstrip("#"))
        if index <= len(candidates):
            return candidates[index - 1]
    elif reference in candidates:
        return reference
    elif re.fullmatch(r"[0-9a-f]{8,63}", reference):
        matches = [candidate for candidate in candidates if candidate.startswith(reference)]
        if len(matches) == 1:
            return matches[0]
    raise ValueError(f"Unknown candidate {reference}; candidates are #1-#{len(candidates)}")


def _current(history: list[dict]) -> str | None:
    """Candidate whose file was most recently materialized."""
    for item in reversed(history):
        if item.get("kind") == "current":
            return item["candidate_id"]
    return None


def _probe_numbers(history: list[dict]) -> dict[str, str]:
    """Short `pN` IDs in order of first appearance of each distinct draft."""
    numbers: dict[str, str] = {}
    for item in history:
        if item.get("kind") == "probe" and item["proof_id"] not in numbers:
            numbers[item["proof_id"]] = f"p{len(numbers) + 1}"
    return numbers


def resolve_probe_ref(history: list[dict], reference: str) -> str:
    reference = reference.strip().lower()
    for proof_id, label in _probe_numbers(history).items():
        if reference in (label, proof_id):
            return proof_id
    raise ValueError(f"Unknown probe {reference}; probes are p1-p{len(_probe_numbers(history))}")


IDEA_STATUSES = ("active", "parked", "succeeded", "abandoned")


def record_idea(run_id: str, title: str | None = None, hypothesis: str = "", region: str | None = None,
                expected_effect: dict | None = None, idea_id: str | None = None,
                status: str | None = None, reason: str = "") -> dict:
    """Create or update a model-owned idea. The harness never authors or schedules ideas."""
    directory = run_dir(run_id)
    history = events(directory)
    if not history or not history[0].get("theorem"):
        raise ValueError("Run is uninitialized")
    if status is not None and status not in IDEA_STATUSES:
        raise ValueError(f"status must be one of {', '.join(IDEA_STATUSES)}")
    if status in ("parked", "abandoned", "succeeded") and not reason.strip():
        raise ValueError(f"Give a one-line reason when marking an idea {status}")
    effect = {str(k): str(v)[:80] for k, v in (expected_effect or {}).items()
              if k in ("tokens", "heartbeats", "compat")}
    span = None
    if region:
        found = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", region)
        if not found:
            raise ValueError("region must be proof lines such as 12-30")
        span = [int(found[1]), int(found[2] or found[1])]
    known = {item["id"]: item for item in history if item.get("kind") == "idea"}
    if idea_id:
        if idea_id not in known:
            raise ValueError(f"Unknown idea {idea_id}; ideas are {', '.join(known) or 'not recorded yet'}")
        update = {"kind": "idea_update", "id": idea_id}
        if title: update["title"] = title.strip()[:120]
        if hypothesis: update["hypothesis"] = hypothesis.strip()[:600]
        if span: update["region"] = span
        if effect: update["expected_effect"] = effect
        if status: update["status"] = status
        if reason.strip(): update["reason"] = reason.strip()[:300]
        _append(directory, update)
        return {"ok": True, **{k: v for k, v in update.items() if k != "kind"}}
    if not title or not title.strip():
        raise ValueError("A new idea needs a title")
    identifier = f"i{len(known) + 1}"
    item = {"kind": "idea", "id": identifier, "title": title.strip()[:120],
            "hypothesis": hypothesis.strip()[:600], "region": span, "expected_effect": effect,
            "status": status or "active", "reason": reason.strip()[:300]}
    _append(directory, item)
    return {"ok": True, **{k: v for k, v in item.items() if k != "kind"}}


def _metric_score(metrics: dict | None) -> float | None:
    if not metrics:
        return None
    value = metrics.get("proxy")
    return value if value is not None else metrics.get("estimated_proxy")


def _evaluation_status(result: dict, mode: str, total: int) -> str:
    compat = result.get("compat") or {}
    if mode == "full" and len(compat) == total and all(v.get("passed") for v in compat.values()):
        return "full"
    return "primary" if next(iter(compat.values()), {}).get("passed") else "fail"


def _summaries(history: list[dict]) -> list[dict]:
    """One row per candidate: best evaluation, status and score. Cheap; no Lean."""
    total = len((history[0].get("versions") if history else None) or [1])
    rows: dict[str, dict] = {}
    for item in history:
        if item.get("kind") == "candidate":
            rows[item["candidate_id"]] = {"id": item["candidate_id"], "n": len(rows) + 1,
                "idea_id": item.get("idea_id"), "origin": item.get("origin", "model"),
                "parents": item.get("parents", []), "evaluations": []}
        elif item.get("kind") == "evaluation" and item["candidate_id"] in rows:
            result = item["result"]
            rows[item["candidate_id"]]["evaluations"].append({
                "mode": item["mode"], "status": _evaluation_status(result, item["mode"], total),
                "result": result, "score": _metric_score(result.get("metrics"))})
    for row in rows.values():
        full = [e for e in row["evaluations"] if e["status"] == "full"]
        primary = [e for e in row["evaluations"] if e["status"] == "primary"]
        chosen = (max(full, key=lambda e: e["score"] or -1) if full else
                  max(primary, key=lambda e: e["score"] or -1) if primary else
                  (row["evaluations"][-1] if row["evaluations"] else None))
        row["status"] = chosen["status"] if chosen else "unevaluated"
        result = chosen["result"] if chosen else {}
        row.update(tokens=result.get("tokens"), heartbeats=result.get("heartbeat"),
                   score=chosen["score"] if chosen else None,
                   verified=bool(full), metrics=result.get("metrics"), evaluated=chosen is not None)
    return list(rows.values())


def _brief(row: dict | None) -> dict | None:
    if not row:
        return None
    return {"candidate": f"#{row['n']}", "tokens": row["tokens"], "heartbeats": row["heartbeats"],
            ("proxy" if row["verified"] else "estimated_proxy"): row["score"], "status": row["status"]}


def _best(rows: list[dict], exclude: str | None = None) -> dict | None:
    pool = [r for r in rows if r["id"] != exclude and r["score"] is not None
            and r["status"] in ("full", "primary") and r["origin"] != "reference"]
    return max(pool, key=lambda r: (r["verified"], r["score"]), default=None)


def _delta(current: dict, other: dict | None) -> dict | None:
    if not other or other.get("tokens") is None or other.get("heartbeats") is None:
        return None
    out = {"tokens": current["tokens"] - other["tokens"],
           "heartbeats": current["heartbeats"] - other["heartbeats"]}
    if current.get("score") is not None and other.get("score") is not None:
        out["proxy"] = round(current["score"] - other["score"], 2)
    return out


def _advisory(rows: list[dict], window: int = 4) -> str | None:
    """Facts only: the last attempts all descend from one non-reference node with no gain."""
    model = [r for r in rows if r["origin"] == "model" and r["evaluated"]]
    if len(model) < window:
        return None
    by_id = {r["id"]: r for r in rows}

    def lineage(row: dict) -> set[str]:
        found: set[str] = set()
        stack = list(row["parents"])
        while stack:
            parent = stack.pop()
            if parent in by_id and parent not in found:
                found.add(parent)
                stack.extend(by_id[parent]["parents"])
        return found
    recent = model[-window:]
    shared = set.intersection(*(lineage(r) for r in recent)) - {r["id"] for r in rows if r["origin"] == "reference"}
    if not shared:
        return None
    root = max(shared, key=lambda i: by_id[i]["n"])
    base = by_id[root]["score"]
    if any(r["score"] is not None and (base is None or r["score"] > base) for r in recent):
        return None
    return (f"The last {window} candidates (#{recent[0]['n']}-#{recent[-1]['n']}) all descend from "
            f"#{by_id[root]['n']} and none improved on its score" + (f" of {base}." if base is not None else "."))


def _model_view(result: dict) -> dict:
    """Compact, non-duplicated payload for the model; the ledger keeps the full result."""
    view = {key: result[key] for key in ("ok", "mode", "candidate", "probe", "tokens", "heartbeat",
            "idea_id", "cached", "candidate_path", "start_line", "end_line", "error", "notes",
            "best_so_far", "advisory", "scored", "contains_sorry", "goals") if result.get(key) not in (None, [], "")}
    metrics = result.get("metrics")
    if metrics and metrics.get("axes"):
        view["metrics"] = {key: metrics[key] for key in ("proxy", "estimated_proxy", "assumes_full_compat",
                                                         "deltas") if key in metrics}
        view["metrics"]["axes"] = {axis: {k: v for k, v in info.items() if k != "reference"}
                                   for axis, info in metrics["axes"].items()}
    elif metrics is not None and not metrics.get("compiled"):
        view["metrics"] = {"compiled": False}
    compat = {}
    for version, info in (result.get("compat") or {}).items():
        item = {"passed": bool(info.get("passed"))}
        for key in ("heartbeats", "diagnostics", "full_diagnostics_ref", "error"):
            if info.get(key) not in (None, [], ""):
                item[key] = info[key]
        counts = info.get("diagnostic_counts") or {}
        if counts.get("omitted"):
            item["omitted_diagnostics"] = counts["omitted"]
        outside = info.get("outside_target") or {}
        if outside.get("errors") or outside.get("warnings"):
            item["outside_target"] = {k: v for k, v in outside.items() if v}
        compat[version] = item
    if compat:
        view["compat"] = compat
    return view


def record_evaluation(name: str, run_id: str, proof: str, mode: str,
                      parents: list[str] | None = None, hypothesis: str = "",
                      origin: str = "model", merge: dict | None = None,
                      materialize_live: bool = True, idea_id: str | None = None) -> dict:
    if mode not in ("fast", "full"):
        raise ValueError("mode must be fast or full")
    directory = run_dir(run_id)
    row = problem(name)
    # Forbidden constructs and statement edits are rejected before anything is recorded,
    # so `sorry` drafts can never become candidates.
    validate_proof(row, proof)
    candidate_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    notes: list[str] = []
    with _candidate_lock(directory, candidate_id):
        history = events(directory)
        if not history or history[0].get("theorem") != name:
            raise ValueError("Run is uninitialized or theorem differs")
        if history[0].get("versions") and history[0]["versions"] != [list(pair) for pair in versions(row)]:
            raise ValueError("Pinned source versions changed since run initialization")
        known = set(_candidate_ids(history))
        explicit: list[str] = []
        for reference in parents or []:
            try:
                resolved = resolve_candidate_ref(history, reference)
            except ValueError as error:
                notes.append(f"parent {reference} ignored: {error}")
                continue
            if resolved != candidate_id and resolved not in explicit:
                explicit.append(resolved)
        lineage = explicit or ([_current(history)] if candidate_id not in known and _current(history) else [])
        lineage = [parent for parent in lineage if parent != candidate_id]
        if candidate_id in known and idea_id is None:
            idea_id = next(item.get("idea_id") for item in history
                           if item.get("kind") == "candidate" and item["candidate_id"] == candidate_id)
        if idea_id and idea_id not in {item["id"] for item in history if item.get("kind") == "idea"}:
            notes.append(f"idea_id {idea_id} is not a recorded idea; kept as a label")
        _snapshot(directory, candidate_id, proof)
        if candidate_id not in known:
            _append(directory, {"kind": "candidate", "candidate_id": candidate_id,
                                "parents": lineage, "hypothesis": hypothesis,
                                "origin": origin, "merge": merge, "idea_id": idea_id,
                                "source_versions": versions(row),
                                "evaluator_sha256": _evaluator_sha()})
        elif explicit and not any(item.get("kind") == "derivation"
                                  and item.get("candidate_id") == candidate_id
                                  and item.get("parents") == explicit for item in history):
            original = next(item for item in history if item.get("kind") == "candidate"
                            and item["candidate_id"] == candidate_id)
            if original.get("parents", []) != explicit:
                _append(directory, {"kind": "derivation", "candidate_id": candidate_id,
                                    "parents": explicit, "origin": origin, "merge": merge})
        key = hashlib.sha256((candidate_id + mode + _evaluator_sha() + json.dumps(versions(row))).encode()).hexdigest()
        prior = next((item for item in reversed(history) if item.get("kind") == "evaluation" and item["key"] == key), None)
        if prior:
            result = json.loads(json.dumps(prior["result"]))
        else:
            try:
                with lean_lock(directory):
                    result = evaluate(name, proof, mode)
            except (ValueError, FileNotFoundError) as error:
                result = {"ok": False, "name": name, "mode": mode, "error": str(error),
                          "compat": {}, "tokens": None, "heartbeat": None, "local_proxy": None}
            _externalize_output(directory, candidate_id, result)
            _append(directory, {"kind": "evaluation", "candidate_id": candidate_id, "key": key,
                                "mode": mode, "result": result})
    location = materialize(name, run_id, proof) if materialize_live and result.get("tokens") is not None else {}
    if location:
        _append(directory, {"kind": "current", "candidate_id": candidate_id})
    history = events(directory)
    rows = _summaries(history)
    me = next((r for r in rows if r["id"] == candidate_id), None)
    result.setdefault("metrics", None)
    if me and result["metrics"] and result["metrics"].get("axes"):
        deltas = result["metrics"].setdefault("deltas", {})
        current = {"tokens": result["tokens"], "heartbeats": result["heartbeat"],
                   "score": _metric_score(result["metrics"])}
        first_parent = next((r for r in rows if r["id"] == (explicit or lineage or [None])[0]), None)
        if first_parent and first_parent["evaluated"]:
            deltas["vs_parent"] = {"candidate": f"#{first_parent['n']}", **(_delta(current, first_parent) or {})}
        best = _best(rows, exclude=candidate_id)
        if best:
            deltas["vs_best"] = {"candidate": f"#{best['n']}", **(_delta(current, best) or {})}
    verified = _best([r for r in rows if r["verified"]])
    fast = _best([r for r in rows if not r["verified"]])
    best_line = {"verified": _brief(verified)}
    if fast and (not verified or (fast["score"] or 0) > (verified["score"] or 0)):
        best_line["fast_only"] = _brief(fast)
    return {**result, "candidate_id": candidate_id, "candidate": _label(history, candidate_id),
            "node_number": _candidate_ids(history).index(candidate_id) + 1,
            "idea_id": idea_id, "cached": prior is not None, "notes": notes,
            "best_so_far": best_line, "advisory": _advisory(rows), **location}


def evaluate_request(name: str, run_id: str, proof: str | None = None, mode: str = "fast",
                     parents: list[str] | None = None, hypothesis: str = "", idea_id: str | None = None,
                     candidate_ref: str | None = None, from_probe: str | None = None) -> dict:
    """Entry for the model: evaluate a proof, an existing `#N`, or a probe by ID."""
    directory = run_dir(run_id)
    history = events(directory)
    if candidate_ref:
        candidate_id = resolve_candidate_ref(history, candidate_ref)
        proof = (directory / "proofs" / f"{candidate_id}.lean").read_text()
    elif from_probe:
        proof_id = resolve_probe_ref(history, from_probe)
        source = next(item for item in reversed(history)
                      if item.get("kind") == "probe" and item["proof_id"] == proof_id)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        idea_id = idea_id or source.get("idea_id")
        parents = parents or ([source["parent"]] if source.get("parent") else None)
    if not proof:
        raise ValueError("Supply proof, candidate (#N) or from_probe (pN)")
    return _model_view(record_evaluation(name, run_id, proof, mode, parents, hypothesis, idea_id=idea_id))


def probe(name: str, run_id: str, proof: str, idea_id: str | None = None, parent: str | None = None) -> dict:
    """Compile a draft (sorry allowed) in the shadow project without creating a candidate."""
    directory = run_dir(run_id)
    history = events(directory)
    row = problem(name)
    notes: list[str] = []
    parent_id = None
    if parent:
        try:
            parent_id = resolve_candidate_ref(history, parent)
        except ValueError as error:
            notes.append(f"parent {parent} ignored: {error}")
    parent_id = parent_id or _current(history)
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    earlier = next((item for item in reversed(history)
                    if item.get("kind") == "probe" and item["proof_id"] == proof_id), None)
    if earlier:
        result = earlier["result"]
    else:
        validate_proof(row, proof, allow_sorry=True)
        try:
            with lean_lock(directory):
                result = evaluate(name, proof, "probe")
        except (ValueError, FileNotFoundError) as error:
            result = {"ok": False, "mode": "probe", "error": str(error), "compat": {}}
        _externalize_output(directory, proof_id, result)
        _snapshot(directory, proof_id, proof)
        _append(directory, {"kind": "probe", "proof_id": proof_id, "idea_id": idea_id,
                            "parent": parent_id, "result": result})
    location = materialize(name, run_id, proof) if result.get("tokens") is not None else {}
    label = _probe_numbers(events(directory))[proof_id]
    return _model_view({**result, "probe": label, "idea_id": idea_id or (earlier or {}).get("idea_id"),
                        "cached": earlier is not None, "notes": notes, **location})


def candidate(name: str, run_id: str, reference: str) -> dict:
    """Restore a candidate (`#N`) or a probe (`pN`) into the shadow project."""
    directory = run_dir(run_id)
    history = events(directory)
    if re.fullmatch(r"p[0-9]+", reference.strip().lower()):
        proof_id = resolve_probe_ref(history, reference)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
        entry = next(item for item in reversed(history)
                     if item.get("kind") == "probe" and item["proof_id"] == proof_id)
        return {"ok": True, "probe": reference.strip().lower(), "proof": proof,
                "last_result": _model_view({**entry["result"], "probe": reference}),
                **materialize(name, run_id, proof)}
    candidate_id = resolve_candidate_ref(history, reference)
    proof_path = directory / "proofs" / f"{candidate_id}.lean"
    if not proof_path.exists():
        raise ValueError("Unknown candidate")
    proof = proof_path.read_text()
    location = materialize(name, run_id, proof)
    _append(directory, {"kind": "current", "candidate_id": candidate_id})
    row = next((r for r in _summaries(events(directory)) if r["id"] == candidate_id), None)
    return {"ok": True, "candidate": _label(history, candidate_id), "proof": proof,
            "idea_id": row and row["idea_id"],
            "evaluations": [{"mode": e["mode"], "status": e["status"], "tokens": e["result"].get("tokens"),
                             "heartbeats": e["result"].get("heartbeat"), "score": e["score"]}
                            for e in (row["evaluations"] if row else [])], **location}


def profile_request(name: str, run_id: str, reference: str | None = None, proof: str | None = None) -> dict:
    """Per-tactic heartbeat profile of a compiling candidate (`#N`), probe (`pN`) or proof text.

    Defaults to the candidate whose file is currently materialized.
    """
    directory = run_dir(run_id)
    history = events(directory)
    label = None
    if proof is None:
        if reference and re.fullmatch(r"p[0-9]+", reference.strip().lower()):
            proof_id = resolve_probe_ref(history, reference)
            label = reference.strip().lower()
        else:
            proof_id = resolve_candidate_ref(history, reference) if reference else _current(history)
            if proof_id is None:
                raise ValueError("No candidate to profile; give candidate (#N) or probe (pN)")
            label = _label(history, proof_id)
        proof = (directory / "proofs" / f"{proof_id}.lean").read_text()
    proof_id = hashlib.sha256((name + "\0" + proof).encode()).hexdigest()
    cached = next((item for item in reversed(history)
                   if item.get("kind") == "profile" and item["proof_id"] == proof_id), None)
    if cached:
        return {**cached["result"], "target": label, "cached": True}
    measured = next((e["result"].get("heartbeat") for row in _summaries(history) if row["id"] == proof_id
                     for e in row["evaluations"] if e["result"].get("heartbeat") is not None), None)
    with lean_lock(directory):
        result = profile(name, proof, measured)
        result["statement_floor_hb"] = heartbeat_floor(name)["heartbeats"]
    _append(directory, {"kind": "profile", "proof_id": proof_id, "result": result})
    return {**result, "target": label, "cached": False}


def polish_request(name: str, run_id: str, reference: str | None = None, **limits) -> dict:
    """Try mechanical variants of a candidate. Passing, improving variants are stored as probes
    (`pN`) so the model can promote one with `arena_evaluate from_probe`; nothing becomes a node."""
    directory = run_dir(run_id)
    history = events(directory)
    candidate_id = resolve_candidate_ref(history, reference) if reference else _current(history)
    if candidate_id is None:
        raise ValueError("No candidate to polish; give candidate (#N)")
    proof = (directory / "proofs" / f"{candidate_id}.lean").read_text()
    measured = next((e["result"].get("heartbeat") for row in _summaries(history) if row["id"] == candidate_id
                     for e in row["evaluations"] if e["result"].get("heartbeat") is not None), None)
    with lean_lock(directory):
        outcome = polish(name, proof, measured, **limits)
    version = versions(problem(name))[0][0]
    shown = []
    for variant in outcome["variants"]:
        proof_id = hashlib.sha256((name + "\0" + variant["proof"]).encode()).hexdigest()
        if proof_id not in _probe_numbers(events(directory)):
            _snapshot(directory, proof_id, variant["proof"])
            _append(directory, {"kind": "probe", "proof_id": proof_id, "idea_id": None, "parent": candidate_id,
                                "result": {"ok": True, "mode": "probe", "scored": False, "tokens": variant["tokens"],
                                           "heartbeat": variant["heartbeats"], "polish": variant["edit"],
                                           "compat": {version: {"passed": True, "heartbeats": variant["heartbeats"]}}}})
        shown.append({"probe": _probe_numbers(events(directory))[proof_id], "edit": variant["edit"],
                      "tokens": variant["tokens"], "heartbeats": variant["heartbeats"],
                      "estimated_proxy": variant["estimated_proxy"], "delta": variant["delta"]})
    return {"ok": True, "candidate": _label(history, candidate_id), "base": outcome["base"],
            "tried": outcome["tried"], "passing": outcome["passing"], "improving": outcome["improving"],
            "complete": outcome["complete"], "seconds": outcome["seconds"], "variants": shown,
            "next": "Promote a variant with arena_evaluate from_probe; nothing was recorded as a candidate."}


def set_decision(run_id: str, candidate_id: str, decision: str, reason: str) -> dict:
    if decision not in ("pursue", "park") or not reason.strip():
        raise ValueError("Decision must be pursue or park with a reason")
    directory = run_dir(run_id)
    candidate_id = resolve_candidate_ref(events(directory), candidate_id)
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
            ideas.append({key: event.get(key) for key in ("id", "title", "hypothesis", "region",
                                                          "expected_effect", "status", "reason")})
        elif kind == "idea_update":
            target = next((i for i in ideas if i["id"] == event["id"]), None)
            if target:
                target.update({k: v for k, v in event.items() if k not in ("kind", "id", "ts")})
        elif kind == "probe":
            probes.append({"proof_id": event["proof_id"], "idea_id": event.get("idea_id"),
                           "parent": event.get("parent"), "result": event["result"], "ts": event.get("ts")})
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
    for idea in ideas:
        idea["attempts"] = sum(1 for node in rows if node["idea_id"] == idea["id"] and node["origin"] == "model")
        idea["probes"] = sum(1 for item in probes if item["idea_id"] == idea["id"])
    idea_rows = ideas
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
    """Compact status: best candidates, the model's ideas with their attempts, recent failures."""
    history = events(run_dir(run_id))
    if not history:
        raise ValueError("Run is uninitialized")
    rows = _summaries(history)
    ideas: dict[str, dict] = {}
    for item in history:
        if item.get("kind") == "idea":
            ideas[item["id"]] = {"id": item["id"], "title": item["title"], "status": item["status"],
                                 "reason": item.get("reason") or None}
        elif item.get("kind") == "idea_update" and item["id"] in ideas:
            ideas[item["id"]].update({k: item[k] for k in ("title", "status", "reason") if k in item})
    probe_numbers = _probe_numbers(history)
    failures: list[dict] = []
    for idea in ideas.values():
        mine = [r for r in rows if r["idea_id"] == idea["id"] and r["origin"] == "model"]
        drafts = [item for item in history if item.get("kind") == "probe" and item.get("idea_id") == idea["id"]]
        idea["attempts"] = len(mine)
        idea["probes"] = len({d["proof_id"] for d in drafts})
        idea["best"] = _brief(_best(mine))
        failed = [r for r in mine if r["status"] == "fail" and r["evaluations"]]
        last = failed[-1] if failed else None
        idea["last_failure"] = (f"#{last['n']}: " + _failure_text(last["evaluations"][-1]["result"])) if last else None
    for row in rows:
        if row["status"] == "fail" and row["evaluations"]:
            failures.append({"ref": f"#{row['n']}", "idea_id": row["idea_id"],
                             "error": _failure_text(row["evaluations"][-1]["result"])})
    for item in history:
        if item.get("kind") == "probe" and _probe_failed(item["result"]):
            failures.append({"ref": probe_numbers[item["proof_id"]], "idea_id": item.get("idea_id"),
                             "error": _failure_text(item["result"])})
    top = sorted((r for r in rows if r["status"] in ("full", "primary") and r["origin"] != "reference"),
                 key=lambda r: (r["verified"], r["score"] or -1), reverse=True)[:5]
    evaluations = sum(len(r["evaluations"]) for r in rows)
    return {"best": _brief(_best(rows)), "top": [_brief(r) | {"idea_id": r["idea_id"]} for r in top],
            "ideas": list(ideas.values()), "recent_failures": failures[-3:],
            "candidates": len(rows), "evaluations": evaluations,
            "probes": len(probe_numbers), "advisory": _advisory(rows)}


def _probe_failed(result: dict) -> bool:
    primary = next(iter((result.get("compat") or {}).values()), None)
    return result.get("ok") is False or (primary is not None and not primary.get("passed"))


def _failure_text(result: dict) -> str:
    if result.get("error"):
        return str(result["error"])[:160]
    for info in (result.get("compat") or {}).values():
        if info.get("error_headlines"):
            return info["error_headlines"][0][:160]
        if info.get("error"):
            return str(info["error"])[:160]
    return "compile failed"
