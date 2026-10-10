"""Goal-state signatures: what Lean says is still open after an attempt, in a form that survives cosmetic edits.

An attempt's signature is a hash of the sorted multiset of its normalized remaining goals (the traced goals at
`sorry` holes and the goals inside error messages) plus its normalized error classes. A compiled proof is
"closed". Two attempts with the same signature leave Lean in the same state, whatever names, spacing or goal
order the edit changed. Normalization renames each goal's hypotheses by position, drops hygiene marks
(`x✝¹`), metavariable numbers (`?m.123`), case tags and source positions, and reduces an error to its first
line with quoted names blanked (so a mistyped identifier is not a new state).
"""

from __future__ import annotations

import hashlib
import json
import re

CLOSED = "closed"
_TOKEN = re.compile(r"[\w'✝!?]+")
_HYGIENE = re.compile(r"✝[⁰¹²³⁴⁵⁶⁷⁸⁹]*")
_META = re.compile(r"\?(?:m|_uniq|u)\.\d+|_uniq\.\d+|_hyg\.\d+|@\.\d+")
_POSITION = re.compile(r"\b\d+:\d+\b|\bline \d+\b(?:,? column \d+)?", re.I)
_QUOTED = re.compile(r"`[^`\n]*`|'[^'\n]*'|\"[^\"\n]*\"")
_BINDER = re.compile(r"^([^\s:][^:]*?) :(?: |$)")


def _plain(text: str) -> str:
    return _META.sub("?m", _POSITION.sub("", text))


def _goal(block: str) -> str | None:
    """One goal block (context lines then `⊢ target`) with hypothesis names renamed by position; None if it has no `⊢`."""
    entries: list[str] = []
    for line in _plain(block).splitlines():
        if line.startswith("case ") and not entries:
            continue
        if line[:1].isspace() and entries:
            entries[-1] += " " + line.strip()
        elif line.strip():
            entries.append(line.strip())
    if not any(item.startswith("⊢") for item in entries):
        return None
    names: dict[str, str] = {}
    for item in entries:
        match = _BINDER.match(item)
        if match and not item.startswith("⊢"):
            for name in match[1].split():
                names[name] = f"_{len(names)}"
    rename = lambda token: names.get(token[0], token[0])  # noqa: E731
    return "\n".join(_HYGIENE.sub("", _TOKEN.sub(rename, " ".join(item.split()))) for item in entries)


def _blocks(text: str) -> list[str]:
    return [goal for goal in (_goal(block) for block in re.split(r"\n\s*\n", text.strip())) if goal]


def error_class(message: str) -> str:
    """First line of an error with quoted names, positions and hygiene marks removed."""
    head = _HYGIENE.sub("", _plain(message.strip().splitlines()[0] if message.strip() else ""))
    return " ".join(_QUOTED.sub("_", head).split())


def parts(result: dict | None) -> tuple[list[str], list[str]]:
    """(sorted normalized goals, sorted error classes) of one compile result (a probe or an evaluation)."""
    compat = (result or {}).get("compat") or {}
    primary = next(iter(compat.values()), {}) if compat else {}
    goals: list[str] = []
    classes: list[str] = []
    for item in primary.get("goals") or (result or {}).get("goals") or []:
        goals += _blocks(item.get("goals", ""))
    for item in primary.get("diagnostics") or []:
        if item.get("severity") != "error":
            continue
        message = item.get("message", "")
        head, _, rest = message.partition("\n")
        goals += _blocks(rest)
        classes.append(error_class(head))
    return sorted(goals), sorted(classes)


def closed(result: dict | None) -> bool:
    """A compile that passed with no error and no `sorry`."""
    compat = (result or {}).get("compat") or {}
    primary = next(iter(compat.values()), {}) if compat else {}
    if not primary.get("passed") or (result or {}).get("contains_sorry"):
        return False
    return not any(
        item.get("severity") == "error" or "`sorry`" in item.get("message", "")
        for item in primary.get("diagnostics") or []
    )


def signature(result: dict | None) -> str:
    """`closed` for a compiled proof, else a short hash of the remaining goals and error classes."""
    if closed(result):
        return CLOSED
    goals, classes = parts(result)
    return hashlib.sha256(json.dumps([goals, classes], ensure_ascii=False).encode()).hexdigest()[:16]
