"""The merge job's price sheet: each chosen node's prices and, for each record node, the steps where it is cheaper or
dearer than the run best. The harness measures and points; the merge worker writes and compiles the combination."""
from __future__ import annotations

import difflib
from pathlib import Path

from arena import campaign, orchestration, reply, text


def _render(key: str, **values) -> str:
    return text.render(f"replies/team.{key}", **values)


def _outer(steps: list) -> list:
    """The steps of a block that no other step of the block contains (a parent's cost already holds its children's)."""
    return [s for s in steps if not any(o is not s and o.first_line <= s.first_line and s.last_line <= o.last_line
                                        and (o.first_line, o.last_line) != (s.first_line, s.last_line) for o in steps)]


def _sum(steps: list, costs: dict[str, dict], key: str) -> int | None:
    values = [costs[s.id][key] for s in _outer(steps) if s.id in costs]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _span(steps: list) -> str:
    ids = [s.id for s in steps]
    return "-" if not ids else ids[0] if len(ids) == 1 else f"{ids[0]}-{ids[-1]}"


def _verdict(base: str, other: str, tokens: tuple, heartbeats: tuple) -> str:
    """Which node is cheaper on each axis and by how much; each pair is (base value, other value), None when unmeasured.
    Axes won by the same node are said together."""
    won: dict[str, list[str]] = {}
    for unit, (mine, theirs) in (("tokens", tokens), ("HB", heartbeats)):
        if mine is not None and theirs is not None and mine != theirs:
            won.setdefault(other if theirs < mine else base, []).append(f"{abs(mine - theirs)} {unit}")
    return ", ".join(_render("recipe_axis", who=who, amount=" and ".join(amounts)) for who, amounts in won.items()) \
        or _render("recipe_same")


def _price(node, costs: dict[str, dict], steps: list) -> tuple:
    return _sum(steps, costs, "tokens"), _sum(steps, costs, "heartbeats")


def _rows(base, other, base_costs: dict, other_costs: dict) -> list[str] | None:
    """Rows for the blocks where the two nodes' steps differ (aligned by step hash, as the attempt log does), largest
    relative difference first; None when no step of one node matches a step of the other."""
    limits = text.numbers()
    left, right = [s.hash for s in base.steps], [s.hash for s in other.steps]
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    if not left or not right or not any(tag == "equal" for tag, *_ in matcher.get_opcodes()):
        return None
    total_tokens = base.tokens or 1
    total_hb = base.heartbeats or 1
    scored = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        mine, theirs = base.steps[i1:i2], other.steps[j1:j2]
        (bt, bh), (ot, oh) = _price(base, base_costs, mine), _price(other, other_costs, theirs)
        if not mine:  # a side with no step there costs nothing
            bt, bh = 0, 0
        if not theirs:
            ot, oh = 0, 0
        dt = abs(bt - ot) if bt is not None and ot is not None else 0
        dh = abs(bh - oh) if bh is not None and oh is not None else 0
        if dt < limits["merge_recipe_min_tokens"] and 100.0 * dh / total_hb < limits["merge_recipe_min_hb_pct"]:
            continue
        line = _render("recipe_row", base_step=_span(mine), base=base.id, base_tokens=reply.shown(bt),
                       base_hb=reply.shown(bh), step=_span(theirs), node=other.id, tokens=reply.shown(ot),
                       hb=reply.shown(oh), verdict=_verdict(base.id, other.id, (bt, ot), (bh, oh)))
        other_wins = (ot is not None and bt is not None and ot < bt) or (oh is not None and bh is not None and oh < bh)
        scored.append((other_wins, dt / total_tokens + dh / total_hb, line))
    # Steps where the record node is cheaper come first: those are what the merge can take from it.
    ranked = sorted(scored, key=lambda item: (not item[0], -item[1]))
    return [line for _, _, line in ranked[: limits["merge_recipe_steps"]]]


def _overall(base, other, costs: dict[str, dict], other_costs: dict) -> str:
    """The comparison when no step matches: which node is cheaper overall, and the cheaper node's own costliest steps."""
    verdict = _verdict(base.id, other.id, (base.tokens, other.tokens), (base.heartbeats, other.heartbeats))
    cheaper_tokens = (other.tokens or 0) < (base.tokens or 0)
    owner, owner_costs = (other, other_costs) if cheaper_tokens else (base, costs)
    ranked = sorted(owner_costs.values(), key=lambda r: -(r["tokens"] or 0))[: text.numbers()["merge_recipe_steps"]]
    steps = ", ".join(_render("recipe_own_step", step=r["step"], tokens=reply.shown(r["tokens"]),
                              hb=reply.shown(r["heartbeats"])) for r in ranked)
    return _render("recipe_unmatched", base=base.id, node=other.id, verdict=verdict, owner=owner.id, steps=steps)


def lines(directory: Path, ids: list[str]) -> list[str]:
    """The merge task's price lines: each node's prices, then per record node the steps with a real price difference
    against the run best (ids[0]). [] when the nodes are unknown."""
    by_id = {node.id: node for node in orchestration.proof_nodes(directory).values()}
    chosen = [by_id[i] for i in ids if i in by_id]
    if len(chosen) < 2:
        return []
    labels = orchestration.job_labels(directory)
    out = [_render("recipe_nodes_head")]
    for position, node in enumerate(chosen):
        out.append(_render("recipe_node_base" if position == 0 else "recipe_node", node=node.id,
                           score=reply.shown(round(node.score, 2) if node.score is not None else None),
                           tokens=reply.shown(node.tokens), hb=reply.shown(node.heartbeats),
                           job=labels.get(orchestration.node_author_job(node), "-")))
    costs: dict[str, dict[str, dict]] = {}
    for node in chosen:
        try:
            costs[node.id] = {r["step"]: r for r in campaign.step_costs(directory, node.proof_id)}
        except (OSError, ValueError, KeyError):
            costs[node.id] = {}
    base = chosen[0]
    for node in chosen[1:]:
        if not costs[node.id] or not costs[base.id]:  # a node saved moments ago has no step prices yet
            out.append(_render("recipe_unpriced", node=(node if not costs[node.id] else base).id))
            continue
        rows = _rows(base, node, costs[base.id], costs[node.id])
        if rows is None:
            out.append(_overall(base, node, costs[base.id], costs[node.id]))
        elif rows:
            out += [_render("recipe_head", base=base.id, node=node.id), *rows]
        else:
            out.append(_render("recipe_none", base=base.id, node=node.id))
    return out
