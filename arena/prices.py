"""Pure pricing helpers for proof tokens, heartbeats, and graph changes."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from arena.steps import Step, split_steps


def rates(reference_tokens: int, reference_heartbeats: int, total_versions: int) -> dict:
    return {
        "points_per_token": 100 / 3 / reference_tokens,
        "points_per_1k_hb": 100 / 3 / reference_heartbeats * 1000,
        "points_per_version": 100 / 3 / total_versions,
    }


def fmt_hb(n: int | float | None) -> str:
    if n is None:
        return "n/a"
    if abs(n) < 1000:
        return str(int(n)) if int(n) == n else str(n)
    return f"{n / 1000:.1f}K"


def fmt_signed(n: int | float | None, unit: str = "") -> str:
    if n is None:
        return "n/a"
    sign = "+" if n >= 0 else "−"
    value = fmt_hb(abs(n))
    return f"{sign}{value}{unit}"


def snippet_tokens(text: str) -> int:
    from arena.engine import _proof_length

    return _proof_length("theorem x : True := " + text)


def step_table(
    proof: str,
    profile: dict | None,
    rates: dict,
    total_tokens: int,
    total_hb: int | None,
    versions: str | None,
) -> dict:
    entries = (profile or {}).get("entries") or []
    line_tokens = (profile or {}).get("line_tokens")
    can_attribute = bool((profile or {}).get("token_attribution_available")) and isinstance(line_tokens, dict)
    rows = []
    for step in split_steps(proof):
        if can_attribute:
            tokens = sum(
                int(line_tokens.get(line, line_tokens.get(str(line), 0)) or 0)
                for line in range(step.first_line, step.last_line + 1)
            )
        else:
            tokens = snippet_tokens(step.text)
        entry = next(
            (item for item in entries if item.get("depth") == 0 and item.get("proof_line") == step.first_line),
            None,
        )
        self_hb = entry.get("self_hb") if entry else None
        incl_hb = entry.get("hb") if entry else None
        points = tokens * rates["points_per_token"] + (incl_hb or 0) / 1000 * rates["points_per_1k_hb"]
        first_line = step.text.splitlines()[0].strip() if step.text.splitlines() else ""
        rows.append(
            {
                "id": step.id,
                "first_line": step.first_line,
                "last_line": step.last_line,
                "tokens": tokens,
                "self_hb": self_hb,
                "incl_hb": incl_hb,
                "pts_if_gone": round(points, 2),
                "text": first_line[:40],
            }
        )
    return {
        "rows": rows,
        "total": {"tokens": total_tokens, "heartbeats": total_hb, "versions": versions, "proxy": None},
        "rates": rates,
    }


def quote_tokens(name: str, items: list, against: dict | None = None, statement: str | None = None) -> dict:
    from arena import campaign
    from arena.engine import _proof_length

    statement = statement or campaign.problem(name)["statement"]
    results = []
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            results.append(
                {
                    "index": index,
                    "error": f"item {index} is not text (got {type(item).__name__}); pass a list of strings",
                }
            )
            continue
        body = item.lstrip()
        is_draft = body.startswith(statement) or body.startswith(":=") or re.match(r"by\b", body) is not None
        if is_draft:
            proof = campaign.normalize_draft(name, item)
            tokens = _proof_length(proof, statement)
            delta = None
            kind = "draft"
        else:
            tokens = snippet_tokens(item)
            delta = tokens - snippet_tokens(against["text"]) if against else None
            kind = "snippet"
        results.append({"index": index, "kind": kind, "tokens": tokens, "delta": delta})
    return {"items": results}


def changed_steps(
    old_steps: list[Step], new_steps: list[Step], old_hb: dict | None = None, new_hb: dict | None = None
) -> list[dict]:
    matcher = SequenceMatcher(
        None, [step.hash for step in old_steps], [step.hash for step in new_steps], autojunk=False
    )
    changes = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = old_steps[old_start:old_end]
        new = new_steps[new_start:new_end]
        item = {
            "ids": [step.id for step in new],
            "old_tokens": sum(snippet_tokens(step.text) for step in old),
            "new_tokens": sum(snippet_tokens(step.text) for step in new),
        }
        if (
            old_hb is not None
            and new_hb is not None
            and all(step.id in old_hb for step in old)
            and all(step.id in new_hb for step in new)
        ):
            item["old_hb"] = sum(old_hb[step.id] for step in old)
            item["new_hb"] = sum(new_hb[step.id] for step in new)
        changes.append(item)
    return changes


def price_row(node, parent, best, lines_changed: int, step_changes: list[dict]) -> dict:
    def difference(key: str, other) -> int | float | None:
        value = getattr(node, key)
        reference = getattr(other, key) if other is not None else None
        return value - reference if value is not None and reference is not None else None

    return {
        "label": node.label,
        "parent_label": parent.label if parent else None,
        "lines": lines_changed,
        "tokens": node.tokens,
        "tokens_vs_parent": difference("tokens", parent),
        "tokens_vs_best": difference("tokens", best),
        "hb": node.heartbeats,
        "hb_vs_parent": difference("heartbeats", parent),
        "hb_vs_best": difference("heartbeats", best),
        "versions": node.versions,
        "score_vs_best": difference("score", best),
        "changed": step_changes,
    }
