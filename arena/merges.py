"""Merge report: verified model candidates whose edits the harness could combine, as analysis only.

The submission must be a proof the model wrote. A harness-composed combination of two model proofs is
therefore never submitted, whatever it scores; `submission` skips `auto_merge` candidates. This module only
reports what the harness's own merge checks found, so a reviewer can see what a combination would have
been worth and decide what to do with it.
"""

from __future__ import annotations


def merge_report(history: list[dict]) -> list[dict]:
    """One row per merge check whose combined proof compiled, from the ledger alone (no Lean).

    Each row: the two parent candidates (as #n), their best proxies, the combined candidate and its
    verified proxy, and whether the combination beats both parents. Always `submitted: False`.
    """
    labels: dict[str, str] = {}
    best: dict[str, float] = {}
    verified: dict[str, bool] = {}
    for event in history:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
        elif event.get("kind") == "evaluation":
            metrics = (event.get("result") or {}).get("metrics") or {}
            full = event.get("mode") == "full" and metrics.get("proxy") is not None
            value = metrics.get("proxy") if full else None
            if value is not None and value > best.get(event["candidate_id"], float("-inf")):
                best[event["candidate_id"]] = value
                verified[event["candidate_id"]] = True
    rows = []
    for event in history:
        if event.get("kind") != "merge_check" or not event.get("candidate_id"):
            continue
        merged = event["candidate_id"]
        parents = [parent for parent in event.get("parents", []) if parent in labels]
        parent_best = [best[parent] for parent in parents if parent in best]
        combined = best.get(merged) if event.get("full_passed") else None
        rows.append({"candidate": labels.get(merged), "parents": [labels[parent] for parent in parents],
                     "parent_proxies": parent_best, "verified": bool(event.get("full_passed")), "proxy": combined,
                     "beats_parents": combined is not None and bool(parent_best) and combined > max(parent_best),
                     "submitted": False})
    return rows


def merge_text(rows: list[dict]) -> str:
    """One line for the run summary."""
    useful = [row for row in rows if row["beats_parents"]]
    if not rows:
        return "none checked"
    return (f"{len(rows)} combined proof(s) compiled, {len(useful)} verified above both parents"
            + (": " + "; ".join(f"{row['candidate']} = {' + '.join(row['parents'])} proxy {row['proxy']}" for row in useful) if useful else "")
            + " (report only, never submitted: submissions are model-written)")
