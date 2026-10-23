"""Reference cards for proof steps: feature extraction, ranking, position-aware rendering, per-actor memory.

The cards are data (research/strategy-bank/cards.json); every model-facing sentence comes from agent-text.

Ranking: score = tactic tags shared with the step + GOAL_WEIGHT per goal tag found in the goal text (the saved
step's goal before and after when `{node, step}` is sent, else the snippet itself). Cards may carry `goal_tags`:
constants such as `List.zip` (also matched as `.zip`) or symbols such as `∈`. Ties go to higher confidence.

Already-applied rule: a card is dropped when its `after` introduces tactic tags (tags in `after` but not in
`before`) and the step already has all of them, or when it removes tags (in `before` but not in `after`), none
of them is in the step, and no goal tag matched (what it replaces is not there).

Memory: the tool remembers per run dir and actor which card ids it returned (`patterns-seen/<actor>.json`) and
shows only unseen ones; with none left it says so.
"""

from __future__ import annotations

import json
import os
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


GOAL_WEIGHT = 2


@lru_cache(maxsize=None)
def _goal_pattern(tag: str) -> re.Pattern:
    if not re.search(r"\w", tag):
        return re.compile(re.escape(tag))
    if "." not in tag:
        return re.compile(rf"(?<![\w.]){re.escape(tag)}(?![\w'])")
    last = re.escape(tag.rsplit(".", 1)[1])
    return re.compile(rf"(?<![\w.']){re.escape(tag)}(?![\w'])|(?<=[\w)\]])\.{last}(?![\w'])")


def goal_hits(card: dict, goal_text: str) -> int:
    """How many of the card's goal tags occur in the goal text."""
    return sum(1 for tag in card.get("goal_tags", ()) if _goal_pattern(tag).search(goal_text))


@lru_cache(maxsize=None)
def _moves(card_id: str) -> tuple[frozenset, frozenset]:
    """(tags the card's after introduces, tags its before removes), from the cards' tag vocabulary."""
    card = next(item for item in load_cards() if item["id"] == card_id)
    before, after = features(card["before"]), features(card["after"])
    return frozenset(after - before), frozenset(before - after)


def already_applied(card: dict, found: set[str], hits: int = 0) -> bool:
    """The step already makes the card's move (see the module docstring)."""
    introduced, removed = _moves(card["id"])
    if introduced and introduced <= found:
        return True
    return bool(removed) and not removed & found and not hits


def _favoured(card: dict, objective: str | None, where: str) -> bool:
    """The card is said to lower the island's measure at this position (tokens, or heartbeats at `where`)."""
    if objective == "tokens":
        return card["effect"]["tokens"] == "down"
    if objective == "heartbeats":
        return card["effect"]["heartbeats"].get(where) == "down"
    return False


def rank(step_text: str, limit: int = 5, goal: str = "", seen: frozenset | set = frozenset(),
         objective: str | None = None, where: str = "middle") -> list[dict]:
    """Relevant cards, best first: tactic overlap plus GOAL_WEIGHT per goal tag, then, for an axis island, the cards
    that lower its measure, then confidence, then bank order.

    Cards the step already applies are dropped; ids in `seen` are left out."""
    found = features(step_text)
    goal_text = f"{goal}\n{step_text}"
    scored = []
    for card in load_cards():
        hits = goal_hits(card, goal_text)
        score = len(found & set(card["tags"])) + GOAL_WEIGHT * hits
        if score and card["id"] not in seen and not already_applied(card, found, hits):
            scored.append((score, card))
    scored.sort(key=lambda pair: (-pair[0], not _favoured(pair[1], objective, where),
                                  -_CONFIDENCE.get(pair[1]["effect"]["confidence"], 0)))
    return [card for _score, card in scored[:limit]]


def render_card(card: dict, where: str) -> str:
    effect = card["effect"]
    return text.render(
        "replies/patterns.card",
        title=card["title"], when=card["when"], how=card["how"],
        tokens=text.render(f"replies/patterns.{effect['tokens']}"),
        position=where, heartbeats=text.render(f"replies/patterns.{effect['heartbeats'][where]}"),
        before=card["before"], after=card["after"],
    ) + (("\n" + text.render("replies/patterns.card_at", position=where, note=card["at"][where]))
         if card.get("at", {}).get(where) else "")


def render_cards(step_text: str, where: str, limit: int = 3, goal: str = "", objective: str | None = None) -> str:
    cards = rank(step_text, limit, goal, objective=objective, where=where)
    if not cards:
        return text.render("replies/patterns.none")
    return "\n\n".join(render_card(card, where) for card in cards)


def _seen_file(directory: Path, actor: str) -> Path:
    return directory / "patterns-seen" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', actor)}.json"


def _load_seen(directory: Path, actor: str) -> list[str]:
    try:
        return list(json.loads(_seen_file(directory, actor).read_text()))
    except (OSError, ValueError):
        return []


def _remember(directory: Path, actor: str, ids: list[str]) -> None:
    path = _seen_file(directory, actor)
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(sorted(set(_load_seen(directory, actor)) | set(ids))))
    temporary.replace(path)


def render_fresh(step_text: str, where: str, goal: str, directory: Path | None, actor: str, limit: int = 3) -> str:
    """Cards for the step that this actor has not been shown in this run dir; says so when none are left.

    Memory is skipped when `directory` does not exist."""
    memory = directory is not None and directory.is_dir()
    seen = set(_load_seen(directory, actor)) if memory else set()
    cards = rank(step_text, limit, goal, seen)
    if not cards:
        old = rank(step_text, 99, goal)
        if not old:
            return text.render("replies/patterns.none")
        return text.render("replies/patterns.seen_all", titles="; ".join(card["title"] for card in old))
    if memory:
        _remember(directory, actor, [card["id"] for card in cards])
    return "\n\n".join(render_card(card, where) for card in cards)


def costliest_step(theorem: str, run_id: str, node, objective: str | None = None) -> tuple[str, str, str] | None:
    """(step id, step text, position) of the node's costliest step by the price table, or None.

    An axis island (objective tokens or heartbeats) takes the costliest step in that measure instead of in points."""
    from arena import campaign

    steps = split_steps(node.proof_text)
    if not steps:
        return None
    rows = {row["id"]: row for row in campaign.price_table(theorem, run_id, node.id)["rows"]}

    def cost(step) -> tuple[float, int]:
        row = rows.get(step.id) or {}
        if objective == "tokens":
            return (row.get("tokens") or 0, 0)
        if objective == "heartbeats":
            return (row.get("incl_hb") or 0, 0)
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
    from arena import campaign

    try:
        directory = campaign.run_dir(run_id)
    except ValueError:
        directory = None
    actor = os.environ.get("ARENA_ACTOR_ID") or "sol"
    if request.get("text"):
        body = str(request["text"])
        return {"ok": True, "text": render_fresh(body, where, body, directory, actor)}
    try:
        node = tools._node(run_id, request["node"])
        steps = getattr(node, "steps", None) or split_steps(node.proof_text)  # node.steps carries the step goals
        index = next(i for i, step in enumerate(steps) if step.id == request["step"])
    except (ValueError, StopIteration):
        return {"ok": False, "category": "invalid_input",
                "text": text.render("replies/patterns.unknown_node", target=f"{request['node']} {request['step']}")}
    step = steps[index]
    goal = "\n".join(part for part in (step.before, step.after) if part)
    return {"ok": True, "text": render_fresh(step.text, position(index, len(steps)), goal, directory, actor)}
