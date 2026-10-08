"""Route fingerprints: which proof strategy a compiled candidate uses, computed by the harness.

A route is a family of proofs with the same strategy. The model never labels routes, so renaming an
idea cannot hide or fake one. A fingerprint has three parts, all read from the proof text:

* ``induction``: whether the proof recurses (induction, a recursor, or a call to the theorem itself);
* ``lemmas``: the project and library lemmas it uses, matched against the kickoff's lemma index;
* ``skeleton``: the head tactic of each top-level line, in order.

Candidates are clustered in arrival order: a new proof joins the route of the most similar earlier proof
when the similarity reaches ``SAME_ROUTE``, otherwise it starts a new route.
"""

from __future__ import annotations

import re

SAME_ROUTE = 0.5
MAX_SKELETON = 24
LABEL_LEMMAS = 3

_COMMENT_BLOCK = re.compile(r"/-.*?-/", re.S)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_IDENT = re.compile(r"[A-Za-z_Ͱ-Ͽ][A-Za-z0-9_'.!?₀-₉]*")
_RECURSION = re.compile(r"(?<![\w.])(induction'?|induct|fun_induction|fun_cases|termination_by|decreasing_by)(?![\w'])"
                        r"|\.(rec|recOn|casesOn|brecOn)(?![\w'])")


def _strip_comments(text: str) -> str:
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", text))


def proof_body(proof: str) -> str:
    """The text after the declaration's own `:=` (the first one outside brackets)."""
    text = _strip_comments(proof)
    depth = 0
    for index, char in enumerate(text):
        if char in "([{⟨":
            depth += 1
        elif char in ")]}⟩":
            depth = max(0, depth - 1)
        elif char == ":" and depth == 0 and text.startswith(":=", index):
            return text[index + 2:]
    return text


def _heads(body: str) -> list[str]:
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return []
    first, rest = lines[0], lines[1:]
    # `:= by tac` keeps its first tactic on the statement line; it has no indentation of its own.
    top = [re.sub(r"^\s*by\b", "", first).strip()] if re.sub(r"^\s*by\b", "", first).strip() else []
    if rest:
        indent = min(len(line) - len(line.lstrip()) for line in rest)
        top += [line.strip() for line in rest if len(line) - len(line.lstrip()) == indent]
    heads: list[str] = []
    for line in top:
        if line.startswith("|"):  # a case arm of the preceding induction or match, not a tactic
            continue
        line = re.sub(r"^[·.<;>()\s*]+", "", line)
        match = re.match(r"[A-Za-z_][A-Za-z0-9_'?!]*", line)
        head = match.group(0) if match else line[:1]
        if head and (not heads or heads[-1] != head):
            heads.append(head)
    return heads[:MAX_SKELETON]


def fingerprint(proof: str, vocabulary: set[str] | frozenset[str] = frozenset(), theorem: str | None = None) -> dict:
    """Route fingerprint of one proof. `vocabulary` is the set of lemma names (qualified or short) to count."""
    body = proof_body(proof)
    short = {name.rsplit(".", 1)[-1] for name in vocabulary}
    lemmas = set()
    recursive = bool(_RECURSION.search(body))
    own = theorem.rsplit(".", 1)[-1] if theorem else None
    for token in _IDENT.findall(body):
        token = token.rstrip(".")
        tail = token.rsplit(".", 1)[-1]
        if own and tail == own:
            recursive = True
        elif token in vocabulary or tail in short:
            lemmas.add(tail)
    return {"induction": recursive, "lemmas": sorted(lemmas), "skeleton": _heads(body)}


def _jaccard(left: set, right: set) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def similarity(left: dict, right: dict) -> float:
    """0 when exactly one proof recurses; else lemma overlap, or tactic-skeleton overlap if neither uses lemmas."""
    if bool(left["induction"]) != bool(right["induction"]):
        return 0.0
    lemmas = (set(left["lemmas"]), set(right["lemmas"]))
    if lemmas[0] or lemmas[1]:
        return _jaccard(*lemmas)
    return _jaccard(set(left["skeleton"]), set(right["skeleton"]))


def assign(earlier: list[dict], current: dict) -> tuple[str, float]:
    """Route id for `current` given earlier route events ({route, fingerprint}); a new id if none is close enough."""
    best_route, best = None, 0.0
    for event in earlier:
        score = similarity(event["fingerprint"], current)
        if score > best:
            best_route, best = event["route"], score
    if best_route is not None and best >= SAME_ROUTE:
        return best_route, round(best, 3)
    routes = {event["route"] for event in earlier}
    return f"r{len(routes) + 1}", round(best, 3)


def label(print_: dict, reference: dict | None = None) -> str:
    """A short deterministic name: how it recurses plus the lemmas that set it apart from the original."""
    own = print_["lemmas"]
    fresh = [name for name in own if not reference or name not in reference["lemmas"]] or own
    kind = "induction" if print_["induction"] else "no induction"
    return kind + (": " + ", ".join(fresh[:LABEL_LEMMAS]) if fresh else "")


def vocabulary(context: dict) -> set[str]:
    """Lemma names worth fingerprinting: the file's earlier theorems and defs, and non-library constants of the proof."""
    names = {item["name"] for item in context.get("earlier", []) if item.get("decl") in ("theorem", "def")}
    names |= {item["name"] for item in context.get("constant", [])
              if item.get("kind") in ("theorem", "def") and item.get("tag") not in ("core", "generated", "instance", "tactic")}
    return names


def route_table(history: list[dict]) -> list[dict]:
    """Per route: label, number of model proof attempts, best candidate and proxy. Pure function of the ledger."""
    labels: dict[str, str] = {}
    origin: dict[str, str] = {}
    for event in history:
        if event.get("kind") == "candidate":
            labels[event["candidate_id"]] = f"#{len(labels) + 1}"
            origin[event["candidate_id"]] = event.get("origin", "model")
    score: dict[str, tuple[bool, float]] = {}
    for event in history:
        if event.get("kind") != "evaluation":
            continue
        metrics = (event.get("result") or {}).get("metrics") or {}
        verified = event.get("mode") == "full" and metrics.get("proxy") is not None
        value = metrics.get("proxy") if verified else metrics.get("estimated_proxy")
        if value is not None and (event["candidate_id"] not in score or (verified, value) > score[event["candidate_id"]]):
            score[event["candidate_id"]] = (verified, value)
    table: dict[str, dict] = {}
    for event in history:
        if event.get("kind") != "route":
            continue
        row = table.setdefault(event["route"], {"route": event["route"], "label": event.get("label") or event["route"],
                                                "original": False, "attempts": 0, "best_candidate": None,
                                                "best_proxy": None, "verified": False})
        identifier = event["proof_id"]
        kind = origin.get(identifier)
        if kind == "reference":
            row["original"] = True
            continue
        if kind == "auto_merge":
            continue
        row["attempts"] += 1
        if identifier in score and (row["best_proxy"] is None or (score[identifier][0], score[identifier][1]) >
                                    (row["verified"], row["best_proxy"])):
            row["verified"], row["best_proxy"] = score[identifier]
            row["best_candidate"] = labels.get(identifier)
    return list(table.values())


def routes_text(table: list[dict]) -> str:
    """One line for the model: the routes with attempts and best proxy (the original's route is marked)."""
    parts = []
    for row in table:
        if not row["attempts"] and not row["original"]:
            continue
        best = f"best proxy {row['best_proxy']} ({row['best_candidate']})" if row["best_proxy"] is not None else "no scored proof"
        tag = " [the original proof's route]" if row["original"] else ""
        parts.append(f"{row['route']} \"{row['label']}\"{tag}: {row['attempts']} attempt{'s' if row['attempts'] != 1 else ''}, {best}")
    return "; ".join(parts) if parts else "none"
