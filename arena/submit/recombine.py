"""Build and cold-check cheaper cross-run step hybrids for selected submission rows."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from arena.engine import _proof_length
from arena.steps import Step, parse, split_steps
from arena.submit.gates import cold_check as default_cold_check
from arena.submit.gates import gate, static_gate
from arena.submit.select import LoadedRun, _checked, pool


def _splittable(proof: str) -> bool:
    """A proof with top-level tactic steps. A one-line `:= by tac` proof has none to swap."""
    return parse(proof.split("\n")) is not None


def _reindent(step: Step, indent: int) -> str:
    """The step's lines moved to `indent`, keeping their structure relative to the step's first line."""
    shift = indent - step.indent
    lines = []
    for line in step.text.split("\n"):
        if not line.strip():
            lines.append(line)
        elif shift >= 0:
            lines.append(" " * shift + line)
        else:
            lines.append(line[min(-shift, len(line) - len(line.lstrip(" "))) :])
    return "\n".join(lines)


def _replace_step(proof: str, index: int, replacement: str) -> str:
    steps = split_steps(proof)
    step = steps[index]
    lines = proof.split("\n")
    lines[step.first_line - 1 : step.last_line] = replacement.split("\n")
    return "\n".join(lines)


def _digest(proof: str) -> str:
    return hashlib.sha256(proof.encode()).hexdigest()


def _hybrid_steps(proof: str, meta: list[dict]) -> list[dict]:
    """Step records of an accepted hybrid: text, hash and id from its own split, goals from `meta`."""
    return [
        {**(meta[index] if index < len(meta) else {}), "id": step.id, "text": step.text, "hash": step.hash}
        for index, step in enumerate(split_steps(proof))
    ]


def _goals(step: dict) -> bool:
    return isinstance(step.get("goal_before"), str) and bool(step["goal_before"])


def _aligned(
    base: dict,
    donor: dict,
    base_index: int,
    donor_index: int,
    base_count: int,
    donor_count: int,
    base_has_goals: bool,
    donor_has_goals: bool,
) -> bool:
    if base_has_goals != donor_has_goals:
        return False
    if base_has_goals:
        if not _goals(base) or not _goals(donor):
            return False
        if base["goal_before"] != donor["goal_before"]:
            return False
        before_after = base.get("goal_after"), donor.get("goal_after")
        return not all(isinstance(goal, str) for goal in before_after) or before_after[0] == before_after[1]
    return base_count == donor_count and base_index == donor_index and base.get("hash") != donor.get("hash")


def _swaps(row: dict, donors: list, attempted: set[str]) -> list[dict]:
    base_steps = split_steps(row["proof"])
    base_meta = row.get("steps") or []
    base_has_goals = any(_goals(step) for step in base_meta)
    swaps = []
    for donor in donors:
        if donor.proof == row["proof"] or (
            donor.run_id == row.get("run_id") and donor.candidate_id == row.get("candidate_id")
        ):
            continue
        if not _splittable(donor.proof):
            continue
        donor_steps = split_steps(donor.proof)
        donor_meta = donor.steps
        donor_has_goals = any(_goals(step) for step in donor_meta)
        for base_index, base_step in enumerate(base_steps):
            if base_index >= len(base_meta):
                continue
            for donor_index, donor_step in enumerate(donor_steps):
                if donor_index >= len(donor_meta) or not _aligned(
                    base_meta[base_index],
                    donor_meta[donor_index],
                    base_index,
                    donor_index,
                    len(base_steps),
                    len(donor_steps),
                    base_has_goals,
                    donor_has_goals,
                ):
                    continue
                declaration = "theorem __arena_step : True := by\n"
                saving = _proof_length(declaration + base_step.text) - _proof_length(declaration + donor_step.text)
                if saving <= 0:
                    continue
                hybrid = _replace_step(row["proof"], base_index, _reindent(donor_step, base_step.indent))
                # A hybrid already tried for this row costs no slot; one that no longer splits into
                # the base's steps would not be the one-step swap it claims to be.
                if _digest(hybrid) in attempted or len(split_steps(hybrid)) != len(base_steps):
                    continue
                swaps.append(
                    {
                        "base_index": base_index,
                        "donor_index": donor_index,
                        "donor": donor,
                        "saving": saving,
                        "proof": hybrid,
                    }
                )
    return sorted(
        swaps,
        key=lambda item: (-item["saving"], item["donor"].run_id, item["donor"].candidate_id, item["base_index"]),
    )


def recombine(
    rows: list[dict],
    manifest: dict[str, dict],
    runs: list[LoadedRun],
    max_hybrids: int,
    cold_check: Callable[[str, str], dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Greedily swap cheaper aligned steps, returning rows and per-row attempt logs.

    Only selected rows rooted in a named run are eligible. Carried rows have no source pool
    steps and pass through unchanged.
    """
    checker = cold_check or default_cold_check
    attempts_by_row = []
    result = []
    for selected in rows:
        row = dict(selected)
        row_attempts = []
        attempts_by_row.append({"name": row["name"], "attempts": row_attempts})
        if row.get("source") != "run" or max_hybrids == 0 or not _splittable(row["proof"]):
            result.append(row)
            continue
        donors = pool(row["name"], runs)
        tried: set[str] = set()
        cold_attempts = 0
        next_hybrid = 1
        contributors = [
            {"run": row["run_id"], "node": row["graph_id"], "step": step.get("id", f"s{index + 1}")}
            for index, step in enumerate(row.get("steps") or [])
        ]
        best = row
        accepted_any = False
        while True:
            swaps = _swaps(best, donors, tried)
            accepted = False
            for swap in swaps:
                donor = swap["donor"]
                hybrid_proof = swap["proof"]
                # Two swaps of one round can still build the same text (equal donor steps).
                if _digest(hybrid_proof) in tried:
                    continue
                tried.add(_digest(hybrid_proof))
                rejection = static_gate(manifest[best["name"]], hybrid_proof)
                attempt = {
                    "base_node": best.get("hybrid_id") or best.get("graph_id"),
                    "donor_run": donor.run_id,
                    "donor_node": donor.graph_id,
                    "step_index": swap["base_index"],
                    "donor_step_index": swap["donor_index"],
                    "token_saving": swap["saving"],
                    "gate_result": {"passed": False, "reasons": rejection} if rejection else None,
                    "settled_proxy": None,
                    "accepted": False,
                    "reason": "static gate failed" if rejection else None,
                }
                if rejection:
                    row_attempts.append(attempt)
                    continue
                if cold_attempts >= max_hybrids:
                    break
                cold_attempts += 1
                cold = _checked(checker, best["name"], hybrid_proof)
                cold["recorded_proxy"] = cold.get("proxy")
                reasons = gate(manifest[best["name"]], hybrid_proof, cold)
                measured = cold.get("proxy")
                attempt["settled_proxy"] = measured
                if reasons:
                    attempt["gate_result"] = {"passed": False, "reasons": reasons, "cold": cold}
                    attempt["reason"] = "gate failed"
                elif not isinstance(measured, (int, float)) or isinstance(measured, bool) or measured <= best["proxy"]:
                    attempt["gate_result"] = {"passed": True, "reasons": [], "cold": cold}
                    attempt["reason"] = "settled proxy did not improve"
                else:
                    attempt["gate_result"] = {"passed": True, "reasons": [], "cold": cold}
                    attempt["accepted"] = True
                    attempt["reason"] = "accepted"
                    next_hybrid += 1
                    hybrid_id = f"{re.sub(r'[^A-Za-z0-9._-]+', '-', best['name'])}-{next_hybrid - 1}"
                    contributor_rows = list(contributors)
                    contributor_rows[swap["base_index"]] = {
                        "run": donor.run_id,
                        "node": donor.graph_id,
                        "step": donor.steps[swap["donor_index"]].get("id", f"s{swap['donor_index'] + 1}"),
                    }
                    best = {
                        **best,
                        "proof": hybrid_proof,
                        "steps": _hybrid_steps(
                            hybrid_proof,
                            [
                                *best["steps"][: swap["base_index"]],
                                donor.steps[swap["donor_index"]],
                                *best["steps"][swap["base_index"] + 1 :],
                            ],
                        ),
                        "source": "submit_merge",
                        "origin": "submit_merge",
                        "hybrid_id": hybrid_id,
                        "proxy": measured,
                        "recorded_proxy": measured,
                        "tokens": cold.get("tokens"),
                        "heartbeats": cold.get("heartbeats"),
                        "axes": cold.get("axes") or {},
                        "passed": cold.get("passed") or {},
                        "merged_from": contributor_rows,
                        "hybrid_cold": cold,
                        "hybrid_proof": hybrid_proof,
                        "accepted_hybrids": [
                            *(best.get("accepted_hybrids") or []),
                            {"hybrid_id": hybrid_id, "proof": hybrid_proof, "merged_from": contributor_rows},
                        ],
                        "contributing_run_ids": list(
                            dict.fromkeys([*(best.get("contributing_run_ids") or []), donor.run_id])
                        ),
                    }
                    contributors = contributor_rows
                    accepted_any = True
                    accepted = True
                row_attempts.append(attempt)
                if accepted:
                    break
            if not accepted or cold_attempts >= max_hybrids:
                break
        if accepted_any:
            row = best
        result.append(row)
    return result, attempts_by_row
