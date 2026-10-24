"""The idea log: one row per evaluated attempt in the run's `ideas.jsonl`, and what each actor reads from it.

Only the harness writes the file. `build_rows` derives every row from the run's history alone (the graph, the notes
filed with each node, the profiles), so the log can be rebuilt at any point of a run; `sync` keeps the file current.
A row is the change one attempt made to its parent (the steps that differ), its measured effect, its outcome and the
actor's `move` and `when`. Its status is computed again whenever the run changes: kept (in the lineage of the current
run best), win (better than its parent on the actor's objective), failed, or dead (the same change failed
`idea_dead_failures` times and never won).

Actors read the log three ways, all delta-only per actor: `push` (lines in the per-turn context), `digest` (the
orchestrator's grouped summary) and the `ideas` tool (`query`). Wording lives in agent-text/replies/ideas.yaml.
"""

from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from arena import campaign, text
from arena.graph import Graph
from arena.run_control import committed_history, committed_operation_ids, published_history

FILE = "ideas.jsonl"
LOCK = "ideas.lock"
SEP = "; "
# Heartbeats per token, the exchange the run report uses, ranks a gain on both axes.
HB_PER_TOKEN = 3.4
_TACTIC_WORDS = (
    "simp_all", "simp only", "simp?", "simp", "rw", "conv_lhs", "conv_rhs", "module", "ring", "abel", "linarith", "omega",
    "calc", "have", "let", "show", "exact", "apply", "refine", "dsimp", "unfold", "change", "suffices", "nth_rewrite",
    "congr", "ext", "intro", "by_cases", "rcases", "obtain", "induction", "aesop", "grind", "decide", "norm_num",
    "field_simp", "linear_combination",
)
_TACTICS = re.compile(r"\b(" + "|".join(re.escape(word) for word in _TACTIC_WORDS) + r")(?![\w?])")
_NODE_REF = re.compile(r"(?:\s+(?:on|from|to|of|at|than|vs|with))?\s+n\d+(?:\.h\d+)?\b")  # log: matches node ids
_ERROR_PREFIX = re.compile(r"^line \d+ \(proof line \d+\): ")  # log: matches Lean headline text


def _render(key: str, **values) -> str:
    return text.render(f"replies/ideas.{key}", **values)


def _heads(steps: list) -> set[str]:
    """The tactic words used in these steps."""
    return {word for step in steps for word in _TACTICS.findall(step.text)}


def _signed(value: int) -> str:
    return f"{value:+d}"


# --- rows ---------------------------------------------------------------------------------------------------------


def job_table(published: list[dict]) -> dict[str, dict]:
    """Job id to {label, scope, objective, actor, role}, labelled `jobN` in delegation order (as orchestration does)."""
    jobs: dict[str, dict] = {}
    for row in published:
        if row.get("type") != "delegation" or not row.get("job_id"):
            continue
        job = jobs.setdefault(row["job_id"], {
            "label": f"job{len(jobs) + 1}", "scope": row.get("scope"), "objective": row.get("objective"),
            "actor": row.get("worker_actor_id"),
        })
        job["role"] = job["objective"] or ("family" if job["scope"] == "island" else job["scope"])
    return jobs


def _first_error(result: dict | None) -> str:
    compat = next(iter(((result or {}).get("compat") or {}).values()), {})
    lines = compat.get("error_headlines") or [
        str(item.get("message", "")).splitlines()[0] for item in compat.get("diagnostics") or [] if item.get("message")
    ]
    return _ERROR_PREFIX.sub("", str(lines[0]))[:120] if lines else ""


def _snippet(old: str, new: str) -> dict | None:
    """The smallest token span that differs between two step texts, as {old, new}; a pure insertion or deletion
    keeps one neighbouring token so it reads as a change. None when either side is too long."""
    before, after = old.split(), new.split()
    ops = [op for op in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not ops:
        return None
    i1, i2, j1, j2 = ops[0][1], ops[-1][2], ops[0][3], ops[-1][4]
    if i1 == i2 or j1 == j2:
        if i1 > 0:
            i1, j1 = i1 - 1, j1 - 1
        elif i2 < len(before):
            i2, j2 = i2 + 1, j2 + 1
    cut_old, cut_new = " ".join(before[i1:i2]) or "∅", " ".join(after[j1:j2]) or "∅"
    limit = text.numbers()["idea_snippet_chars"]
    return {"old": cut_old, "new": cut_new} if max(len(cut_old), len(cut_new)) <= limit else None


def _changed(parent, child) -> dict:
    """The steps that differ between a parent and its child, aligned by step hash."""
    left, right = [step.hash for step in parent.steps], [step.hash for step in child.steps]
    old: list = []
    new: list = []
    anchors: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old += parent.steps[i1:i2]
        new += child.steps[j1:j2]
        anchors += left[i1:i2] or ["+" + (left[i1] if i1 < len(left) else "end")]
    return {"old": old, "new": new, "anchors": anchors}


def _span_hb(steps: list, profile: dict) -> int:
    """The heartbeats a set of steps spent: the profile's outermost entries that start on their lines (an entry's
    `hb` includes its children, and a calc segment's entries sit below the calc's own)."""
    lines = {number for step in steps for number in range(step.first_line, step.last_line + 1)}
    spans: dict[tuple[int, int], dict] = {}
    for entry in profile.get("entries") or []:
        if entry.get("proof_line") in lines and entry.get("hb") is not None:
            key = (entry["proof_line"], entry.get("end_proof_line", entry["proof_line"]))
            if key not in spans or entry.get("depth", 0) < spans[key].get("depth", 0):
                spans[key] = entry
    return sum(entry["hb"] for (first, last), entry in spans.items()
               if not any((a, b) != (first, last) and a <= first and last <= b for a, b in spans))


def _step_hb(parent, child, profiles: dict, change: dict) -> int | None:
    """The heartbeats the changed steps spend now minus before, from the two nodes' profiles; None without both."""
    before, after = profiles.get(parent.proof_id), profiles.get(child.proof_id)
    if not before or not after:
        return None
    return _span_hb(change["new"], after) - _span_hb(change["old"], before)


def _improves(child, parent, objective: str | None) -> bool | None:
    """True when the child beats its parent on the actor's objective; None while the child has no measure yet."""
    measure = (lambda node: getattr(node, objective)) if objective in ("tokens", "heartbeats") else None
    if measure is None:
        if child.score is None:
            return None
        return parent.score is None or child.score > parent.score + 1e-9
    if measure(child) is None:
        return None
    return measure(parent) is None or measure(child) < measure(parent)


def build_rows(history: list[dict], read_text, committed, jobs: dict[str, dict]) -> list[dict]:
    """Every idea row of a run, derived from its history: one per non-root edge, oldest first, statuses current."""
    published = committed_history(history, committed)
    graph = Graph.from_history(history, read_text, committed_operations=committed)
    nodes = {node.proof_id: node for node in graph.nodes}
    total = len((history[0].get("versions") if history else None) or [1])
    results: dict[str, dict] = {}
    moves: dict[str, str] = {}
    whens: dict[str, str] = {}
    profiles: dict[str, dict] = {}
    full_at: dict[str, float] = {}
    verified_at: dict[str, float] = {}
    edges: dict[str, dict] = {}
    for event in published:
        kind = event.get("kind")
        proof_id = event.get("proof_id") or event.get("candidate_id")
        if kind in ("probe", "evaluation") and isinstance(event.get("result"), dict):
            results[proof_id] = event["result"]
        if kind in ("probe", "candidate"):
            # Runs before move/when carry the one free note, filed as the candidate's hypothesis.
            move = event.get("note") if kind == "probe" else event.get("hypothesis")
            if move and proof_id not in moves:
                moves[proof_id] = move
            if event.get("when") and proof_id not in whens:
                whens[proof_id] = event["when"]
        elif kind == "profile" and isinstance(event.get("result"), dict):
            profiles[proof_id] = event["result"]
        elif kind == "edge":
            edges.setdefault(proof_id, event)
        elif kind == "evaluation" and event.get("mode") == "full" and isinstance(event.get("result"), dict):
            full_at.setdefault(proof_id, event["ts"])
            compat = event["result"].get("compat") or {}
            if len(compat) == total and all(item.get("passed") for item in compat.values()):
                verified_at.setdefault(proof_id, event["ts"])
    now = max((event.get("ts", 0.0) for event in published), default=0.0)

    # The run best as it stood over time: a verified node scoring above every earlier verified node.
    best_ts: dict[str, float] = {}
    top = None
    for proof_id in sorted(verified_at, key=verified_at.get):
        score = nodes[proof_id].score if proof_id in nodes else None
        if score is not None and (top is None or score > top + 1e-9):
            top = score
            best_ts[proof_id] = verified_at[proof_id]

    rows: list[dict] = []
    by_proof: dict[str, dict] = {}
    for proof_id, edge in edges.items():
        child = nodes.get(proof_id)
        named = nodes.get((edge.get("from") or [None])[0])
        if child is None or named is None:
            continue
        # The filing parent is where the attempt was saved; the closest saved proof is what it actually changed.
        closest = nodes.get(edge.get("measured_parent"))
        parent, change = named, _changed(named, child)
        if closest is not None and closest is not named:
            other = _changed(closest, child)
            if len(other["old"]) + len(other["new"]) < len(change["old"]) + len(change["new"]):
                parent, change = closest, other
        attempt = child.attempts[0] if child.attempts else {}
        job = jobs.get(attempt.get("job_id")) or {}
        before, after = _heads(change["old"]), _heads(change["new"])
        removed, added = sorted(before - after), sorted(after - before)
        harness = edge.get("type") == "salvaged_from" or child.origin != "model"
        closed = child.status == "closed"
        old_text = "\n".join(s.text for s in change["old"])
        new_text = "\n".join(s.text for s in change["new"])
        fingerprint = hashlib.sha1(new_text.encode()).hexdigest()[:8]
        anchors = [anchor.lstrip("+") for anchor in change["anchors"]]
        signature = None if harness or not change["anchors"] \
            else "+".join(change["anchors"]) + "|" + ",".join(removed) + "|" + ",".join(added)
        if signature is not None and not removed and not added:
            signature += "|" + fingerprint
        step_hb = _step_hb(parent, child, profiles, change) if closed else None
        d_hb = child.heartbeats - parent.heartbeats if closed and child.heartbeats and parent.heartbeats else None
        row = {
            "id": f"i{len(rows) + 1}", "ts": edge["ts"], "actor": attempt.get("actor_id"), "job": job.get("label"),
            "role": job.get("role") or "sol", "node": child.id, "parent": parent.id,
            "steps": [s.id for s in (change["new"] or change["old"])],
            "pstep": (change["old"] or change["new"] or [None])[0].id if (change["old"] or change["new"]) else None,
            "change": _snippet(old_text, new_text) if len(change["old"]) <= 1 and len(change["new"]) <= 1 else None,
            "removed": removed, "added": added, "anchors": anchors, "sig": signature, "fp": fingerprint,
            "d_tokens": child.tokens - parent.tokens if closed and child.tokens and parent.tokens else None,
            "d_hb": d_hb, "step_hb": step_hb, "tokens": child.tokens, "hb": child.heartbeats,
            "score": child.score, "verified": child.verified,
            "outcome": "closed" if closed else f"holes {len(child.holes)}" if child.status == "sketch"
            else _first_error(results.get(proof_id)) or "does not compile",
            "closed": closed, "move": moves.get(proof_id, ""), "when": whens.get(proof_id, ""),
            "harness": harness,
            "sources": (edge.get("operation") or {}).get("from") or edge.get("from") if harness else [],
            "kind": edge["type"], "from": [parent.proof_id, *(edge.get("from") or [])],
            "new_best": proof_id in best_ts, "best_ts": best_ts.get(proof_id),
            "settled": not closed or proof_id in full_at or now - edge["ts"] > 120,
            "win": _improves(child, parent, job.get("objective")) if closed and not harness else False,
        }
        rows.append(row)
        by_proof[proof_id] = row
    for row in rows:
        if row["harness"]:
            sources = " + ".join((by_proof.get(pid) or {}).get("id") or nodes[pid].id for pid in row["sources"])
            row["move"] = (_render("harness_salvage", source=sources) if row["kind"] == "salvaged_from"
                           else _render("harness_assembly", sources=sources) if len(row["sources"]) > 1
                           else _render("harness_other", source=sources))
    _statuses(rows, nodes, {proof_id: row["from"] for proof_id, row in by_proof.items()})
    return rows


def snapshot(history: list[dict], read_text, committed) -> tuple[list[dict], dict[str, dict]]:
    """(rows, jobs) of a run as its history stands: what `sync` writes and `lines_from` reads."""
    jobs = job_table(committed_history(history, committed))
    return build_rows(history, read_text, committed, jobs), jobs


def _statuses(rows: list[dict], nodes: dict, parents: dict[str, list[str]]) -> None:
    """Set kept, status and dead_trigger on every row from the current run best and the failures so far."""
    scored = [node for node in nodes.values() if node.verified and node.score is not None]
    lineage: set[str] = set()
    pending = [max(scored, key=lambda node: node.score).proof_id] if scored else []
    while pending:
        proof_id = pending.pop()
        if proof_id not in lineage:
            lineage.add(proof_id)
            pending += parents.get(proof_id, [])
    limit = text.numbers()["idea_dead_failures"]
    fails: dict[str, int] = {}
    wins: dict[str, int] = {}
    proof_of = {nodes_row.id: proof_id for proof_id, nodes_row in nodes.items()}
    for row in rows:
        row["kept"] = proof_of.get(row["node"]) in lineage
        row["dead_trigger"] = False
        sig = row["sig"]
        if sig is None:
            continue
        if row["win"] or row["kept"]:
            wins[sig] = wins.get(sig, 0) + 1
        elif row["win"] is False and row["settled"]:
            fails[sig] = fails.get(sig, 0) + 1
            row["dead_trigger"] = fails[sig] == limit and not wins.get(sig)
    for row in rows:
        sig = row["sig"]
        dead = sig is not None and fails.get(sig, 0) >= limit and not wins.get(sig)
        row["status"] = ("kept" if row["kept"] else "win" if row["win"] else "pending" if not row["settled"]
                         else "dead" if dead and row["win"] is False else "failed")


# --- the file -----------------------------------------------------------------------------------------------------


@contextmanager
def _lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _marker(history: list[dict]) -> list[int]:
    """What changes the rows: counts of the events they read."""
    kinds = ("edge", "probe", "candidate", "evaluation", "profile")
    counts = [sum(1 for event in history if event.get("kind") == kind) for kind in kinds]
    return [*counts, sum(1 for event in history if event.get("type") == "delegation")]


def sync(directory: Path) -> list[dict]:
    """The run's idea rows, rebuilt and written to `ideas.jsonl` when the run changed since the file was written."""
    with _lock(directory):
        history = campaign.events(directory)
        marker = _marker(history)
        path = directory / FILE
        try:
            lines = path.read_text().splitlines()
            meta = json.loads(lines[0]) if lines else {}
        except (OSError, ValueError):
            lines, meta = [], {}
        if meta.get("marker") == marker:
            return [json.loads(line) for line in lines[1:]]
        rows = snapshot(history, campaign._proof_reader(directory), committed_operation_ids(directory))[0]
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text("\n".join([json.dumps({"marker": marker}), *(json.dumps(row, ensure_ascii=False) for row in rows)]) + "\n")
        os.replace(temporary, path)
        return rows


# --- lines --------------------------------------------------------------------------------------------------------


def _effect(row: dict) -> str:
    """Tokens and heartbeats gained: the changed steps' heartbeats when profiled, else the whole proof's, flagged."""
    parts = []
    if row["d_tokens"] is not None:
        parts.append(_render("effect_tok", value=_signed(row["d_tokens"])))
    if row["step_hb"] is not None:
        parts.append(_render("effect_hb", value=_signed(row["step_hb"])))
    elif row["d_hb"] is not None:
        parts.append(_render("effect_hb_proof", value=_signed(row["d_hb"])))
    return ", ".join(parts)


def _gain(row: dict, objective: str | None = None) -> float:
    """What the row saved, in tokens, on one axis or on both at the report's exchange."""
    tokens = -(row["d_tokens"] or 0)
    heartbeats = -(row["step_hb"] if row["step_hb"] is not None else row["d_hb"] or 0)
    return tokens if objective == "tokens" else heartbeats if objective == "heartbeats" \
        else tokens + heartbeats / HB_PER_TOKEN


def _significant(row: dict) -> bool:
    numbers = text.numbers()
    heartbeats = row["step_hb"] if row["step_hb"] is not None else row["d_hb"]
    return ((row["d_tokens"] or 0) <= -numbers["idea_win_tokens"]
            or (heartbeats or 0) <= -numbers["idea_win_heartbeats"])


def _change(row: dict) -> str:
    if row["change"]:
        return _render("change", old=row["change"]["old"], new=row["change"]["new"])
    return ""


def _line(head: str, *parts: str) -> str:
    return SEP.join([head, *(part for part in parts if part)])


def best_line(row: dict) -> str:
    where = _render("where", step=row["pstep"], node=row["parent"]) if row["pstep"] else ""
    return _line(_render("best_head", node=row["node"], score=round(row["score"], 2) if row["score"] is not None else "-",
                         parent=row["parent"]), ": ".join(part for part in (where, _change(row)) if part),
                 _effect(row), row["move"])


def _bare(note: str) -> str:
    """A note without node ids (older runs wrote them): technique lines are for actors that cannot see those nodes."""
    return " ".join(_NODE_REF.sub("", note).split())


def technique_line(row: dict) -> str:
    when = _bare(row["when"])
    return _line(_render("technique_head"), _bare(row["move"]), _render("when", when=when) if when else "",
                 _change(row), _effect(row))


def dead_line(rows: list[dict], sig: str) -> str:
    group = [row for row in rows if row["sig"] == sig and row["status"] in ("failed", "dead")]
    first = group[0]
    error = next((row["outcome"] for row in group if row["outcome"] != "closed" and not row["outcome"].startswith("holes")), "")
    # A change too long to show as a snippet is named by the tactic words it swaps, else by what its first try said.
    tactics = _render("change_tactics", old=", ".join(first["removed"]) or "∅", new=", ".join(first["added"]) or "∅") \
        if first["removed"] or first["added"] else _bare(first["move"])
    return _line(_render("dead_head", where=_render("where", step=first["pstep"], node=first["parent"])),
                 _change(first) or tactics, _render("fails", count=len(group)), _render("error", error=error) if error else "")


# --- push and digest ----------------------------------------------------------------------------------------------


def _cut(items: list[tuple], state: dict) -> list[str]:
    """Items as (priority, rank, key, line) become at most `idea_push_lines` lines, the overflow one "+N more" line.
    Every item is marked sent, shown or not: a row reaches an actor at most once."""
    cap = text.numbers()["idea_push_lines"]
    items = sorted(items, key=lambda item: (item[0], -item[1]))
    state["sent"] = sorted({*state.get("sent", []), *(item[2] for item in items)})
    shown = items if len(items) <= cap else items[: cap - 1]
    state["last"] = {"shown": [item[2] for item in shown], "more": [item[2] for item in items[len(shown) :]]}
    lines = [item[3] for item in shown]
    return lines + ([_render("more", count=len(items) - len(shown))] if len(shown) < len(items) else [])


def _reached(rows: list[dict], state: dict) -> int:
    """The newest row id number up to which every row is settled."""
    reached = 0
    for row in rows:
        if not row["settled"]:
            break
        reached = int(row["id"][1:])
    return reached


def push(rows: list[dict], role: str, job: str | None, state: dict) -> list[str]:
    """Lines for one actor's next turn, and its cursor moved past them (`state` is the actor's delivery bucket entry).

    Trim and merge get the row behind each new run best; islands get other actors' significant wins as technique
    lines; everyone, the authors of the failures included, gets dead ends. A change reaches an actor once."""
    first = "cursor" not in state
    sent = set(state.get("sent", []))
    if first:  # a new actor's packet already names the run best
        state["since"] = max((row["best_ts"] for row in rows if row["new_best"]), default=0.0)
    cursor = state.get("cursor", 0)
    items: list[tuple] = []
    for row in rows:
        number = int(row["id"][1:])
        if row["new_best"] and role in ("trim", "merge") and row["job"] != job and f"b:{number}" not in sent \
                and row["best_ts"] > state["since"]:
            items.append((0, row["best_ts"], f"b:{number}", best_line(row)))
        if number <= cursor or row["harness"] or not row["settled"] or row["sig"] is None:
            continue
        sig = row["sig"]
        if row["dead_trigger"] and f"d:{sig}" not in sent:
            group = [other for other in rows if other["sig"] == sig and other["status"] in ("failed", "dead")]
            items.append((1, len(group), f"d:{sig}", dead_line(rows, sig)))
        elif role in ("tokens", "heartbeats", "family") and row["job"] != job and row["status"] in ("win", "kept") \
                and row["closed"] and _significant(row) and (_bare(row["move"]) or row["change"]) \
                and f"t:{sig}" not in sent \
                and not any(other["sig"] == sig and other["status"] == "dead" for other in rows):
            objective = role if role in ("tokens", "heartbeats") else None
            items.append((2, _gain(row, objective), f"t:{sig}", technique_line(row)))
    # Several wins of one change in the same turn: keep the best one.
    kept: dict[str, tuple] = {}
    for item in items:
        if item[2] not in kept or (item[0], -item[1]) < (kept[item[2]][0], -kept[item[2]][1]):
            kept[item[2]] = item
    # A newer run best makes the older ones moot: say the newest, and count the rest as sent.
    bests = sorted((item for item in kept.values() if item[0] == 0), key=lambda item: item[1])
    superseded = [item[2] for item in bests[:-1]]
    for key in superseded:
        del kept[key]
    state["cursor"] = max(cursor, _reached(rows, state))
    lines = _cut(list(kept.values()), state)
    state["sent"] = sorted({*state["sent"], *superseded})
    state["last"]["superseded"] = superseded
    return lines


def _island_status(rows: list[dict], job: str, role: str) -> tuple[dict | None, int]:
    """The job's best closed row on its objective and the number of its rows since the last one that improved it."""
    def measure(row: dict) -> float | None:
        value = row["tokens"] if role == "tokens" else row["hb"] if role == "heartbeats" else row["score"]
        return None if value is None or not row["closed"] or not row["verified"] else \
            (-value if role in ("tokens", "heartbeats") else value)

    best, stale = None, 0
    for row in (row for row in rows if row["job"] == job and not row["harness"]):
        value = measure(row)
        if value is not None and (best is None or value > measure(best) + 1e-9):
            best, stale = row, 0
        else:
            stale += 1
    return best, stale


def digest(rows: list[dict], jobs: dict[str, dict], state: dict) -> list[str]:
    """The orchestrator's lines since its previous turn: kept changes, dead ends, one status line per active job."""
    limit = text.numbers()["idea_digest_lines"]
    sent = set(state.get("sent", []))
    cursor = state.get("cursor", 0)
    fresh = [row for row in rows if int(row["id"][1:]) > cursor and not row["harness"]]
    kept = sorted((row for row in rows if row["status"] == "kept" and not row["harness"] and f"k:{row['id']}" not in sent),
                  key=lambda row: -_gain(row))
    dead = []
    for row in fresh:
        if row["dead_trigger"] and f"d:{row['sig']}" not in sent and row["settled"]:
            dead.append((f"d:{row['sig']}", dead_line(rows, row["sig"])))
    lines = [_line(_render("kept_head", id=row["id"], node=row["node"]),
                   ": ".join(part for part in (_render("where", step=row["pstep"], node=row["parent"]) if row["pstep"] else "",
                                               _change(row)) if part), _effect(row), row["move"])
             for row in kept[:limit]]
    if len(kept) > limit:
        lines.append(_render("more", count=len(kept) - limit))
    lines += [line for _, line in dead[:limit]]
    if len(dead) > limit:
        lines.append(_render("more", count=len(dead) - limit))
    for job_id, job in jobs.items():
        if job["role"] not in ("tokens", "heartbeats", "family", "trim", "merge") \
                or not any(row["job"] == job["label"] for row in fresh):
            continue
        best, stale = _island_status(rows, job["label"], job["role"])
        # Say it when its best moved, then again each `island_stale_turns` attempts without a gain.
        mark = [best["node"] if best else None, stale // text.numbers()["island_stale_turns"]]
        if state.setdefault("islands", {}).get(job["label"], [object()])[0:2] == mark:
            continue
        state["islands"][job["label"]] = mark
        if best is None:
            shown = _render("island_none")
        else:
            axis = job["role"] if job["role"] in ("tokens", "heartbeats") else "score"
            value = best["tokens"] if axis == "tokens" else best["hb"] if axis == "heartbeats" else round(best["score"], 2)
            shown = _render(f"island_best_{axis}", node=best["node"], value=value)
        lines.append(_line(_render("island", job=job["label"], role=_render(f"role_{job['role']}"), best=shown),
                           _render("island_stale", count=stale)))
    state["sent"] = sorted({*sent, *(f"k:{row['id']}" for row in kept), *(key for key, _ in dead)})
    state["cursor"] = max(cursor, _reached(rows, state))
    return lines


def lines_from(rows: list[dict], jobs: dict[str, dict], actor: str, bucket: dict) -> tuple[str, list[str]]:
    """(role, lines): an actor's attempt log lines for this turn (see push and digest), its cursor kept in `bucket`."""
    state = bucket.setdefault("ideas", {})
    if actor == "sol":
        return "sol", digest(rows, jobs, state)
    job = next((item for item in jobs.values() if item["actor"] == actor), None)
    role = job["role"] if job else "sol"
    return role, push(rows, role, job["label"] if job else None, state)


def lines_for(directory: Path, actor: str, bucket: dict) -> tuple[str, list[str]]:
    """lines_from for the run as it stands in `directory`; nothing when the run cannot be read."""
    try:
        rows = sync(directory)
        jobs = job_table(published_history(directory, campaign.events(directory)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):  # the log never breaks a tool call
        return "sol", []
    return lines_from(rows, jobs, actor, bucket)


# --- the ideas tool -----------------------------------------------------------------------------------------------


def query(rows: list[dict], anchor: str | None, tactic: str | None) -> list[str]:
    """Distinct changes tried on a step (by its hash) and/or with a tactic word, grouped with counts and best effect."""
    word = (tactic or "").strip().lower()

    def matches(row: dict) -> bool:
        if row["harness"]:
            return False
        if anchor is not None and anchor not in row["anchors"]:
            return False
        if word:
            shown = " ".join([*row["removed"], *row["added"], row["move"], *(row["change"] or {}).values()]).lower()
            return word in shown
        return True

    found = [row for row in rows if matches(row)]
    groups: dict[str, list[dict]] = {}
    for row in found:
        groups.setdefault(row["sig"], []).append(row)
    ranked = sorted(groups.values(), key=lambda group: (-sum(row["status"] in ("kept", "win") for row in group), -len(group)))
    numbers = text.numbers()
    lines = []
    for group in ranked[: numbers["idea_query_rows"]]:
        best = max(group, key=lambda row: (row["status"] in ("kept", "win"), _gain(row)))
        status = next(name for name in ("kept", "win", "dead", "failed", "pending") if any(row["status"] == name for row in group))
        order = sorted(group, key=lambda row: (row["status"] not in ("kept", "win"), -int(row["id"][1:])))
        lines.append(_render("query_row", change=_change(best), count=len(group), status=_render(f"status_{status}"),
                             effect=_effect(best) or "-", ids=" ".join(row["id"] for row in order[: numbers["idea_query_ids"]])))
    if len(ranked) > numbers["idea_query_rows"]:
        lines.append(_render("more", count=len(ranked) - numbers["idea_query_rows"]))
    return lines


def ideas_tool(run_id: str, request: dict) -> dict:
    """The `ideas` tool: what was tried on a step (node + step, default node: the caller's focus) and/or a tactic word."""
    from arena import tools

    step, tactic, node_ref = request.get("step"), request.get("tactic"), request.get("node")
    if set(request) - {"node", "step", "tactic"} or not (step or tactic) \
            or not all(isinstance(value, str) or value is None for value in (step, tactic, node_ref)):
        return {"ok": False, "category": "invalid_input", "text": _render("query_bad")}
    anchor = target = None
    if step:
        try:
            node = tools._node(run_id, node_ref or tools._focus_ref(run_id))
            anchor = next(item.hash for item in node.steps if item.id == step)
        except (ValueError, StopIteration, KeyError):
            return {"ok": False, "category": "invalid_input",
                    "text": _render("query_unknown", target=f"{node_ref or ''} {step}".strip())}
        target = f"{node.id} {step}"
    lines = query(sync(campaign.run_dir(run_id)), anchor, tactic)
    if not lines:
        return {"ok": True, "text": _render("query_none")}
    return {"ok": True, "text": "\n".join([_render("query_head", target=target or tactic), *lines])}
