"""Reference cards for proof steps: feature extraction, ranking by tag overlap, position-aware rendering.

The cards are data (research/strategy-bank/cards.json); every model-facing sentence comes from agent-text.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from arena import text
from arena.steps import split_steps

CARDS_PATH = Path(__file__).resolve().parents[1] / "research/strategy-bank/cards.json"
POSITIONS = ("opening", "middle", "closing")
_CONFIDENCE = {"high": 2, "medium": 1, "low": 0}
# Tags that occur in almost every step carry no signal.
_GENERIC = frozenset({"by", "at", "if"})
# Tags whose syntax is not the bare word.
_SPECIAL = {
    "simp only": r"\bsimp\s+only\b",
    "simp [*]": r"\bsimp\w*\s*(?:only\s*)?\[[^\]]*\*",
    "<;>": r"<;>",
    "<|": r"<\|",
    "exact?": r"\bexact\?",
    "bullets": r"(?m)^\s*[·•]",
    "fun": r"\bfun\b|λ",
    "lambda": r"λ|\bfun\b",
    "anonymous-constructor": r"⟨",
    "exists": r"\bexists\b|∃",
    "ascription": r"\(\s*[\w']+\s*:\s*[^)]+\)",
    "underscore": r"(?<![\w.])_(?!\w)",
    "dot-notation": r"\b[hH]\w*\.(?:1|2|left|right|mp|mpr)\b",
    "sum": r"∑",
    "cast": r"\bcast\b|↑",
}


@lru_cache(maxsize=1)
def load_cards(path: Path = CARDS_PATH) -> tuple[dict, ...]:
    return tuple(json.loads(path.read_text())["cards"])


def _pattern(tag: str) -> re.Pattern:
    return re.compile(_SPECIAL.get(tag) or rf"(?<![\w.]){re.escape(tag)}(?![\w'])")


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, re.Pattern]:
    return {tag: _pattern(tag) for card in load_cards() for tag in card["tags"] if tag not in _GENERIC}


def features(step_text: str) -> set[str]:
    """The cards' tag vocabulary that occurs in the step text."""
    return {tag for tag, pattern in _vocabulary().items() if pattern.search(step_text)}


def position(index: int, count: int) -> str:
    """Bucket of the step at `index` among `count` steps; the same rule as research/strategy-bank/mine_moves.py."""
    relative = (index + 0.5) / max(count, 1)
    if index == 0 or relative < 0.2:
        return "opening"
    if index + 1 >= count or relative >= 0.8:
        return "closing"
    return "middle"


def rank(step_text: str, limit: int = 5) -> list[dict]:
    """Cards sharing at least one tag with the step, most overlap first; ties go to higher confidence, then bank order."""
    found = features(step_text)
    scored = [(len(found & set(card["tags"])), card) for card in load_cards()]
    scored = [(score, card) for score, card in scored if score]
    scored.sort(key=lambda pair: (-pair[0], -_CONFIDENCE.get(pair[1]["effect"]["confidence"], 0)))
    return [card for _score, card in scored[:limit]]


def render_card(card: dict, where: str) -> str:
    effect = card["effect"]
    return text.render(
        "replies/patterns.card",
        title=card["title"], when=card["when"], how=card["how"],
        tokens=text.render(f"replies/patterns.{effect['tokens']}"),
        position=where, heartbeats=text.render(f"replies/patterns.{effect['heartbeats'][where]}"),
        before=card["before"], after=card["after"],
    )


def render_cards(step_text: str, where: str, limit: int = 3) -> str:
    cards = rank(step_text, limit)
    if not cards:
        return text.render("replies/patterns.none")
    return "\n\n".join(render_card(card, where) for card in cards)


def costliest_step(theorem: str, run_id: str, node) -> tuple[str, str, str] | None:
    """(step id, step text, position) of the node's costliest step by the price table, or None."""
    from arena import campaign

    steps = split_steps(node.proof_text)
    if not steps:
        return None
    rows = {row["id"]: row for row in campaign.price_table(theorem, run_id, node.id)["rows"]}

    def cost(step) -> tuple[float, int]:
        row = rows.get(step.id) or {}
        return (row.get("pts_if_gone") if row.get("pts_if_gone") is not None else -1.0, row.get("tokens") or 0)

    step = max(steps, key=cost)
    return step.id, step.text, position(steps.index(step), len(steps))


def patterns_tool(theorem: str, run_id: str, request: dict) -> dict:
    """The `patterns` tool: cards for a saved step (node + step) or a snippet (text, optional position)."""
    from arena import tools

    unknown = sorted(set(request) - {"node", "step", "text", "position"})
    where = request.get("position") or "middle"
    if unknown or where not in POSITIONS or bool(request.get("text")) == bool(request.get("node") and request.get("step")):
        return {"ok": False, "category": "invalid_input", "text": text.render("replies/patterns.bad_input")}
    if request.get("text"):
        return {"ok": True, "text": render_cards(str(request["text"]), where)}
    try:
        node = tools._node(run_id, request["node"])
        steps = split_steps(node.proof_text)
        index = next(i for i, step in enumerate(steps) if step.id == request["step"])
    except (ValueError, StopIteration):
        return {"ok": False, "category": "invalid_input",
                "text": text.render("replies/patterns.unknown_node", target=f"{request['node']} {request['step']}")}
    return {"ok": True, "text": render_cards(steps[index].text, position(index, len(steps)))}
