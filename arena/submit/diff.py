"""Diff a submission against the previous one's proofs and manifest."""

from __future__ import annotations

import json
from pathlib import Path

from arena.package import _jsonl


def _proxies(directory: Path) -> dict[str, float | None]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {}
    for row in manifest.get("rows") or []:
        if isinstance(row, dict) and row.get("name"):
            found[row["name"]] = row.get("proxy")
    return found


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def diff_submissions(new_rows: list[dict], previous_dir: Path | None) -> dict:
    """Per-row proxy delta. Rows that got worse, including rows dropped since last time, come first."""
    if previous_dir is None:
        return {
            "previous": None,
            "worse": [],
            "rows": [],
            "text": "no previous submission\n",
        }
    old_proofs = {row["name"]: row.get("proof") for row in _jsonl(previous_dir / "proofs.jsonl") if row.get("name")}
    old_proxy = _proxies(previous_dir)
    new = {row["name"]: row for row in new_rows}
    compared = []
    names = sorted(set(old_proofs) | set(new))
    for name in names:
        current = new.get(name)
        previous = old_proxy.get(name)
        if current is None:
            compared.append(
                {
                    "name": name,
                    "status": "dropped",
                    "old_proxy": previous,
                    "new_proxy": None,
                    "delta": None,
                    "worse": True,
                }
            )
            continue
        measured = _number(current.get("proxy"))
        before = _number(previous)
        changed = old_proofs.get(name) != current.get("proof") or measured != before
        delta = None if measured is None or before is None else round(measured - before, 2)
        worse = before is not None and measured is not None and measured < before
        if not changed:
            continue
        compared.append(
            {
                "name": name,
                "status": "worse" if worse else "changed",
                "old_proxy": before,
                "new_proxy": measured,
                "delta": delta,
                "worse": worse,
            }
        )
    compared.sort(key=lambda row: (not row["worse"], row["name"]))
    worse = [row["name"] for row in compared if row["worse"]]
    return {
        "previous": previous_dir.name,
        "worse": worse,
        "rows": compared,
        "text": _markdown(compared),
    }


def _line(row: dict) -> str:
    if row["status"] == "dropped":
        shown = "unrecorded" if row["old_proxy"] is None else row["old_proxy"]
        return f"- {row['name']}: dropped (was {shown})"
    delta = "unrecorded" if row["delta"] is None else f"{row['delta']:+.2f}"
    return f"- {row['name']}: proxy {row['old_proxy']} -> {row['new_proxy']} (delta {delta})"


def _markdown(rows: list[dict]) -> str:
    worse = [row for row in rows if row["worse"]]
    other = [row for row in rows if not row["worse"]]
    lines = ["# Diff against previous", "", "## WORSE", ""]
    lines.extend(_line(row) for row in worse)
    if not worse:
        lines.append("- none")
    lines.extend(["", "## Other changes", ""])
    lines.extend(_line(row) for row in other)
    if not other:
        lines.append("- none")
    return "\n".join(lines) + "\n"
