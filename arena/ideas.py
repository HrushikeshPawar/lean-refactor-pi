"""Source-derived proof ideas and deterministic exploration scheduling."""

from __future__ import annotations

from collections import Counter
import re


def idea_shape_issue(idea_id: str, proof: str) -> str | None:
    """Check only mechanical claims whose proof shape is unambiguous."""
    if idea_id != "induct-first":
        return None
    body = proof.split(":= by", 1)[-1]
    induction = re.search(r"\b(?:induction|cases)\b", body)
    witness = re.search(r"\bexists\b|\brefine\s*⟨|\bexact\s*⟨", body)
    if not induction or (witness and witness.start() < induction.start()):
        return ("induct-first requires an induction or cases step before the first "
                "existential witness; use arena_probe to repair the draft")
    return None


def source_ideas(statement: str, original: str) -> list[dict]:
    """Offer proof structures, not previously discovered candidate proofs."""
    ideas = []
    if "∃" in statement and "induction" in original:
        ideas.append({"id": "induct-first", "title": "Induct before selecting a witness",
                      "goal": "Inspect the induction hypothesis for a usable witness or tail proof; avoid committing to the existential witness before induction.",
                      "idea_kind": "structural"})
    ideas.extend([
        {"id": "factor-premises", "title": "Factor repeated source premises",
         "goal": "Find the longest repeated lemma chain in the original proof and share its result across distinct obligations.",
         "idea_kind": "structural"},
        {"id": "focused-goals", "title": "Rebuild the longest side goal",
         "goal": "Use the exact Lean goal and pinned declarations to replace a broad simplification or manual contradiction with a focused proof.",
         "idea_kind": "structural"},
        {"id": "local-golf", "title": "Compress a validated proof",
         "goal": "After the structural lanes have been tested, shorten a primary-valid proof while tracking heartbeats and compatibility.",
         "idea_kind": "local"},
    ])
    return ideas


def scheduled_ideas(ideas: list[dict], nodes: list[dict], probes: list[dict] | None = None) -> list[dict]:
    """Give each structural idea two development attempts, then rotate stalled work."""
    model = [node for node in nodes if node.get("origin") == "model"]
    attempts = Counter(node.get("idea_id") for node in model)
    probe_counts = Counter(item.get("idea_id") for item in probes or [])
    by_id = {idea["id"]: idea for idea in ideas}
    untested = [idea for idea in ideas if attempts[idea["id"]] < 2 and
                attempts[idea["id"]] + probe_counts[idea["id"]] < 4]
    best_global = max((node.get("local_proxy") or 0 for node in model
                       if node.get("status") == "full"), default=0)
    def priority(idea: dict) -> float:
        lane = [node for node in model if node.get("idea_id") == idea["id"]]
        development = attempts[idea["id"]] + probe_counts[idea["id"]]
        best = max((node.get("local_proxy") or 0 for node in lane
                    if node.get("status") == "full"), default=0)
        shortest = min((node["tokens"] for node in lane if node.get("status") in ("full", "primary")
                        and node.get("tokens") is not None), default=None)
        return round((60 * best / best_global if best_global else 0)
                     + (12 if shortest is not None and best == 0 else 0)
                     + 12 / (1 + max(0, development - 2))
                     + (8 if best == 0 else 0), 2)
    if untested:
        first = untested[0]["id"]
    else:
        recent = [node.get("idea_id") for node in model[-4:]]
        saturated = {idea_id for idea_id, count in Counter(recent).items()
                     if idea_id is not None and len(recent) == 4 and count >= 3}
        viable = [idea for idea in ideas if idea["id"] not in saturated] or ideas
        first = max(viable, key=lambda idea: (priority(idea),
                                              -attempts[idea["id"]] - probe_counts[idea["id"]],
                                              -ideas.index(idea)))["id"]
    ordered = [by_id[first]] + sorted((idea for idea in ideas if idea["id"] != first),
                                     key=lambda idea: -priority(idea))
    result = []
    reference = next((node for node in nodes if node.get("origin") == "reference"), nodes[0] if nodes else None)
    for idea in ordered:
        candidates = [node for node in nodes if node.get("status") in ("full", "primary")
                      and node.get("decision") != "park"
                      and (idea["id"] == "local-golf" or node.get("idea_id") == idea["id"])]
        seed = max(candidates, key=lambda node: (node.get("status") == "full",
                                                node.get("local_proxy") or 0,
                                                -(node.get("tokens") or 10**9)), default=reference)
        result.append({**idea, "attempts": attempts[idea["id"]],
                       "probes": probe_counts[idea["id"]],
                       "priority": priority(idea),
                       "selection_reason": "breadth quota" if untested and idea["id"] == first else
                                           "ranked after breadth" if idea["id"] == first else "alternative",
                       "seed_candidate_id": seed["id"] if seed else None,
                       "seed_node": seed["index"] if seed else None,
                       "best_tokens": min((node["tokens"] for node in candidates if node.get("tokens") is not None), default=None),
                       "next_action": ("Repair the current proof structure using its complete Lean diagnostics."
                                       if attempts[idea["id"]] == 1 and not candidates else idea["goal"])})
    return result
