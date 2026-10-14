"""Pick each benchmark row's best cold-verified candidate across named runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arena.campaign import _graph_node_id, _update_id, node_label
from arena.graph import Graph, Node
from arena.package import RUNS, _json, _jsonl
from arena.submit.gates import cold_gate, static_gate


class SubmitError(Exception):
    """The invocation is wrong: the name, the runs, or the output directory."""


@dataclass
class Candidate:
    run_id: str
    candidate_id: str
    graph_id: str
    label: str
    proof: str
    tokens: int | None
    heartbeats: int | None
    proxy: float | None
    steps: list[dict]
    origin: str
    directory: Path
    config: dict
    source_versions: list
    evaluator_sha256: str | None
    tool_call_id: str | None
    request_id: str | None
    turn: int | None


@dataclass
class LoadedRun:
    run_id: str
    directory: Path
    config: dict
    theorem: str | None
    history: list[dict]
    candidates: list[Candidate] = field(default_factory=list)
    reason: str | None = None


@dataclass
class Selection:
    rows: list[dict]
    blocked: list[dict]
    missing: list[str]
    rejected: list[dict]


def resolve_runs(names_or_prefixes: list[str], runs_root: Path = RUNS) -> list[str]:
    """Expand each name to a run directory, or to every directory it prefixes.

    An argument that is itself a directory is that run and not a prefix. An argument
    that matches nothing raises `SubmitError` naming it.
    """
    if not runs_root.is_dir():
        raise SubmitError(f"run directory {runs_root} does not exist")
    found: list[str] = []
    seen: set[str] = set()
    directories = [path for path in runs_root.iterdir() if path.is_dir()]
    for name in names_or_prefixes:
        direct = runs_root / name
        matches = [name] if direct.is_dir() else sorted(path.name for path in directories if path.name.startswith(name))
        if not matches:
            raise SubmitError(f"no run matches {name}")
        for match in matches:
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def _steps(node: Node) -> list[dict]:
    return [
        {
            "id": step.id,
            "text": step.text,
            "hash": step.hash,
            "goal_before": step.before,
            "goal_after": step.after,
        }
        for step in node.steps
    ]


def _ids(history: list[dict], proof_id: str) -> tuple[str, str]:
    """Graph id (nK) and stored label (#k). Mapping goes through the campaign helpers."""
    try:
        graph_id = _graph_node_id(history, proof_id)
    except KeyError:
        graph_id = _update_id(history, proof_id)
    return graph_id, node_label(history, proof_id)


def _candidate(run: LoadedRun, node: Node, event: dict, proof: str) -> Candidate:
    graph_id, label = _ids(run.history, node.proof_id)
    turn = event.get("turn")
    return Candidate(
        run.run_id,
        node.proof_id,
        graph_id,
        label,
        proof,
        node.tokens,
        node.heartbeats,
        node.score,
        _steps(node),
        node.origin,
        run.directory,
        run.config,
        list(event.get("source_versions") or []),
        event.get("evaluator_sha256"),
        event.get("tool_call_id"),
        event.get("request_id"),
        turn if isinstance(turn, int) and not isinstance(turn, bool) else None,
    )


def load_runs(run_ids: list[str], runs_root: Path) -> tuple[list[LoadedRun], list[dict]]:
    """Load named runs. A directory with no `run-config.json` is rejected as unknown provenance,
    and one whose ledger the graph reader cannot build (older ledger shapes) is rejected with the error.
    """
    loaded, rejected = [], []
    for run_id in run_ids:
        directory = runs_root / run_id
        config = _json(directory / "run-config.json")
        history = _jsonl(directory / "ledger.jsonl")
        run = LoadedRun(run_id, directory, config, config.get("theorem") if config else None, history)
        if not config:
            run.reason = "unknown provenance"
            rejected.append({"run_id": run_id, "reasons": ["unknown provenance"]})
            loaded.append(run)
            continue
        events = {
            event["candidate_id"]: event
            for event in history
            if event.get("kind") == "candidate" and event.get("candidate_id")
        }

        def read_text(proof_id: str, directory: Path = directory) -> str | None:
            path = directory / "proofs" / f"{proof_id}.lean"
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return None

        # `verified` is the full evaluation that passed every toolchain. The graph's own
        # status is closed/sketch/broken, which is a later cut than "full".
        try:
            graph = Graph.from_history(history, read_text)
        except Exception as error:
            reason = f"graph unreadable: {type(error).__name__}: {error}"
            run.reason = reason
            rejected.append({"run_id": run_id, "reasons": [reason]})
            loaded.append(run)
            continue
        for node in graph.nodes:
            if node.origin == "reference" or not node.verified:
                continue
            proof = read_text(node.proof_id)
            event = events.get(node.proof_id)
            if not proof or event is None:
                continue
            run.candidates.append(_candidate(run, node, event, proof))
        loaded.append(run)
    return loaded, rejected


def pool(theorem: str, runs: list[LoadedRun]) -> list[Candidate]:
    """Every full, verified, non-reference candidate of `theorem` across `runs`."""
    return [candidate for run in runs if run.theorem == theorem and run.reason is None for candidate in run.candidates]


def _rank(candidate: Candidate) -> tuple:
    proxy = candidate.proxy if candidate.proxy is not None else float("-inf")
    tokens = candidate.tokens if candidate.tokens is not None else 10**18
    return (-proxy, tokens, candidate.run_id, candidate.candidate_id)


def _failure(theorem: str, candidate: Candidate | None, reasons: list[str]) -> dict:
    return {
        "row": theorem,
        "candidate": None if candidate is None else candidate.graph_id,
        "candidate_id": None if candidate is None else candidate.candidate_id,
        "label": None if candidate is None else candidate.label,
        "reasons": reasons,
    }


def _checked(checker: Callable[[str, str], dict], name: str, proof: str) -> dict:
    try:
        result = checker(name, proof)
    except Exception as error:
        return {"passed": {}, "tokens": None, "heartbeats": None, "proxy": None, "axes": {}, "error": str(error)}
    return dict(result) if isinstance(result, dict) else {"error": "cold check returned no result", "passed": {}}


def _row_from(theorem: str, candidate: Candidate, cold: dict, run_ids: list[str], source: str) -> dict:
    return {
        "name": theorem,
        "source": source,
        "proof": candidate.proof,
        "candidate_id": candidate.candidate_id,
        "graph_id": candidate.graph_id,
        "label": candidate.label,
        "run_id": candidate.run_id,
        "tokens": cold.get("tokens"),
        "heartbeats": cold.get("heartbeats"),
        "recorded_tokens": candidate.tokens,
        "recorded_heartbeats": candidate.heartbeats,
        "recorded_proxy": candidate.proxy,
        "proxy": cold.get("proxy"),
        "axes": cold.get("axes") or {},
        "passed": cold.get("passed") or {},
        "steps": candidate.steps,
        "config": candidate.config,
        "directory": str(candidate.directory),
        "source_versions": candidate.source_versions,
        "evaluator_sha256": candidate.evaluator_sha256,
        "tool_call_id": candidate.tool_call_id,
        "request_id": candidate.request_id,
        "turn": candidate.turn,
        "contributing_run_ids": list(run_ids),
    }


def _recorded_proxy(carried: dict) -> object:
    """The proxy the cold result must agree with. A later submission stores both scores."""
    recorded = carried.get("recorded_proxy")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
        return recorded
    return carried.get("proxy")


def _previous_runs(carried: dict) -> list[str]:
    runs = carried.get("contributing_runs")
    if isinstance(runs, list):
        return [run for run in runs if isinstance(run, str)]
    return [carried["run_id"]] if isinstance(carried.get("run_id"), str) else []


def _previous_row(theorem: str, carried: dict, cold: dict, run_ids: list[str]) -> dict:
    """A carried row. `contributing_run_ids` are the named runs on this theorem that left no
    candidate; the previous submission's own runs and spend ride along for the ceiling gate."""
    return {
        "name": theorem,
        "source": "previous",
        "proof": carried["proof"],
        "candidate_id": carried.get("candidate_id"),
        "graph_id": carried.get("graph_id"),
        "label": carried.get("label"),
        "run_id": carried.get("run_id"),
        "tokens": cold.get("tokens"),
        "heartbeats": cold.get("heartbeats"),
        "recorded_tokens": carried.get("tokens"),
        "recorded_heartbeats": carried.get("heartbeats"),
        "recorded_proxy": _recorded_proxy(carried),
        "proxy": cold.get("proxy"),
        "axes": cold.get("axes") or {},
        "passed": cold.get("passed") or {},
        "steps": [],
        "config": {},
        "directory": None,
        "source_versions": carried.get("pinned_sources") or [],
        "evaluator_sha256": None,
        "tool_call_id": None,
        "request_id": None,
        "turn": None,
        "contributing_run_ids": list(run_ids),
        "previous_run_ids": _previous_runs(carried),
        "previous_spend_usd": carried.get("spend_usd"),
        "code": carried.get("code"),
    }


def select_rows(
    manifest: dict[str, dict],
    runs: list[LoadedRun],
    checker: Callable[[str, str], dict],
    max_cold: int,
    previous: dict[str, dict],
    progress: Callable[[dict], None] | None,
) -> Selection:
    """Walk each row by recorded proxy and keep the first candidate that passes the gate.

    The static gates run first; a candidate that fails them is never cold-compiled and does
    not count against `max_cold`.
    """
    rows, blocked, missing, rejected = [], [], [], []
    for theorem in sorted(manifest):
        benchmark = manifest[theorem]
        named = [run.run_id for run in runs if run.theorem == theorem and run.reason is None]
        ranked = sorted(pool(theorem, runs), key=_rank)
        # With no verified candidate from the named runs, carry the previous proof. The named
        # runs' spend on this theorem still counts. Candidates that all fail gates block instead.
        if not ranked:
            carried = previous.get(theorem)
            if carried is None:
                missing.append(theorem)
                continue
            shown = carried.get("graph_id") or carried.get("label")
            reasons = static_gate(benchmark, carried["proof"])
            if not reasons:
                if progress:
                    progress({"row": theorem, "candidate": shown, "phase": "cold"})
                cold = _checked(checker, theorem, carried["proof"])
                cold["recorded_proxy"] = _recorded_proxy(carried)
                reasons = cold_gate(benchmark, cold)
            if reasons:
                if progress:
                    progress(
                        {"row": theorem, "candidate": carried.get("graph_id"), "phase": "fail", "reasons": reasons}
                    )
                blocked.append(
                    {
                        "row": theorem,
                        "candidate": carried.get("graph_id") or carried.get("candidate_id"),
                        "candidate_id": carried.get("candidate_id"),
                        "label": carried.get("label"),
                        "reasons": reasons,
                    }
                )
                continue
            rows.append(_previous_row(theorem, carried, cold, named))
            continue
        chosen = None
        tried = 0
        failures = []
        for candidate in ranked:
            reasons = static_gate(benchmark, candidate.proof)
            if reasons:
                if progress:
                    progress({"row": theorem, "candidate": candidate.graph_id, "phase": "fail", "reasons": reasons})
                failures.append(_failure(theorem, candidate, reasons))
                continue
            if tried >= max_cold:
                failures.append(_failure(theorem, None, [f"stopped after {max_cold} cold compiles"]))
                break
            tried += 1
            if progress:
                progress({"row": theorem, "candidate": candidate.graph_id, "phase": "cold"})
            cold = _checked(checker, theorem, candidate.proof)
            cold["recorded_proxy"] = candidate.proxy
            reasons = cold_gate(benchmark, cold)
            if reasons:
                if progress:
                    progress({"row": theorem, "candidate": candidate.graph_id, "phase": "fail", "reasons": reasons})
                failures.append(_failure(theorem, candidate, reasons))
                continue
            chosen = _row_from(theorem, candidate, cold, named, "run")
            break
        if chosen is None:
            blocked.extend(failures)
            continue
        rejected.extend(failures)
        rows.append(chosen)
    return Selection(rows, blocked, missing, rejected)


def load_previous(directory: Path) -> dict[str, dict]:
    """Rows of an earlier submission, keyed by benchmark name."""
    proofs = {}
    for row in _jsonl(directory / "proofs.jsonl"):
        if row.get("name") and isinstance(row.get("proof"), str):
            proofs[row["name"]] = row["proof"]
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    described = {}
    if isinstance(manifest, dict):
        for row in manifest.get("rows") or []:
            if isinstance(row, dict) and row.get("name"):
                described[row["name"]] = row
    return {name: {"proof": proof, **described.get(name, {})} for name, proof in proofs.items()}
