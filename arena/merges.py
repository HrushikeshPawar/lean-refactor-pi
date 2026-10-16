"""Report verified harness combinations and whether the run selected one for submission."""

from __future__ import annotations

import json
from pathlib import Path

from arena import text


def merge_report(history: list[dict], directory: Path | None = None) -> list[dict]:
    """One row per merge check whose combined proof compiled, with submission status when available.

    Each row: the two parent candidates (as #n), their best proxies, the combined candidate and its
    verified proxy, whether the combination beats both parents, and whether it is the run's
    selected submission candidate.
    """
    try:
        submission = json.loads((directory / "submission.json").read_text(encoding="utf-8")) if directory else {}
    except (OSError, ValueError):
        submission = {}
    submitted_id = submission.get("candidate_id") if isinstance(submission, dict) else None
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
        rows.append(
            {
                "candidate": labels.get(merged),
                "parents": [labels[parent] for parent in parents],
                "parent_proxies": parent_best,
                "verified": bool(event.get("full_passed")),
                "proxy": combined,
                "beats_parents": combined is not None and bool(parent_best) and combined > max(parent_best),
                "submitted": merged == submitted_id,
            }
        )
    return rows


def merge_text(rows: list[dict]) -> str:
    """One line for the run summary."""
    useful = [row for row in rows if row["beats_parents"]]
    if not rows:
        return text.render("replies/merge.none_checked")
    return (
        text.render("replies/merge.summary", count=len(rows), verified=len(useful))
        + (
            ": "
            + "; ".join(
                text.render(
                    "replies/merge.entry",
                    candidate=row["candidate"],
                    parents=" + ".join(row["parents"]),
                    proxy=row["proxy"],
                )
                for row in useful
            )
            if useful
            else ""
        )
        + "".join(
            text.render("replies/merge.submitted", candidate=row["candidate"]) for row in rows if row["submitted"]
        )
        + ("" if any(row["submitted"] for row in rows) else text.render("replies/merge.not_submitted"))
    )
